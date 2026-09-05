# -*- coding: utf-8 -*-
"""Extracting the legacy project interpretations, out of the evidence store (WP-08).

Standard library plus :mod:`pgx.domain` and :mod:`pgx.evidence`.

The legacy CSVs and ``clean_mvp_seed_dataset.py`` mix two different things: what
ClinPGx published, and what this project concluded from it. The first belongs in
the evidence store. The second - ``plain_language_mvp``, ``demo_risk_level``,
``risk_meaning``, ``drug_behavior_hint``, ``effect_direction``,
``normalized_phenotype_group``, ``evidence_strength``, ``usable_for_mvp`` and the
hand-written ``MANUAL_EFFECT_HINTS`` - is a set of unreviewed project claims,
and importing it as evidence would launder an opinion into a source fact.

So it is extracted **out** of the evidence path, into
``draft-curation-proposals.ndjson``, where every proposal is labelled with what
it is not:

``NOT_EVIDENCE``, ``NOT_SCIENTIFICALLY_REVIEWED``, ``NOT_EXECUTABLE``,
``DO_NOT_USE_FOR_ASSESSMENT``.

Status is always ``UNREVIEWED_LEGACY_MIGRATION_CANDIDATE``. No
``CuratedInterpretation`` is created, no ``created_by`` is filled in, and no
reviewer is named: nobody has reviewed these, and a name here would say
otherwise.

**The legacy script is read, never run.** ``MANUAL_EFFECT_HINTS`` is recovered
by parsing the file into an AST and evaluating only that one assignment's
literal value with :func:`ast.literal_eval`. Importing the module would execute
the whole of it - including its network and file-writing code - and importing a
legacy script to read a constant out of it is how a migration acquires the
behaviour it was meant to retire.

**Origins are kept, not deduplicated away.** Repeated proposals are grouped by
an explicit key, and every contributing row keeps its file, digest and line or
row number.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import io
import json
import os
from dataclasses import dataclass, field
from typing import (Any, Dict, Iterable, List, Mapping, Optional, Sequence,
                    Tuple)

from pgx.domain.hashing import sha256_digest
from pgx.evidence.errors import EvidenceError
from pgx.evidence.models import EvidenceNaturalKey

__all__ = [
    "DRAFT_CURATION_VERSION",
    "LEGACY_INTERPRETATION_FIELDS",
    "PROPOSAL_STATUS",
    "PROPOSAL_WARNINGS",
    "DraftCurationProposal",
    "DraftCurationResult",
    "ProposalOrigin",
    "extract_draft_curation",
    "read_manual_effect_hints",
]

#: Bumped when the extraction or the proposal shape changes.
DRAFT_CURATION_VERSION = "pgx-draft-curation/1"

#: The only status a WP-08 proposal may carry. There is no other value, and no
#: argument that sets one: WP-08 reviews nothing.
PROPOSAL_STATUS = "UNREVIEWED_LEGACY_MIGRATION_CANDIDATE"

#: Stamped on every proposal. Present in the artifact itself so a reader who
#: opens the file without the documentation still cannot mistake what it is.
PROPOSAL_WARNINGS: Tuple[str, ...] = (
    "NOT_EVIDENCE",
    "NOT_SCIENTIFICALLY_REVIEWED",
    "NOT_EXECUTABLE",
    "DO_NOT_USE_FOR_ASSESSMENT",
)

#: The project-authored columns to lift out, per legacy file. Exact names only:
#: guessing which column is an interpretation would either miss one or drag a
#: source fact out with it.
LEGACY_INTERPRETATION_FIELDS: Mapping[str, Tuple[str, ...]] = {
    "clinpgx_mvp_seed/phenotype_effect_rules.csv": (
        "normalized_phenotype_group",
        "drug_behavior_hint",
        "effect_direction",
        "risk_meaning",
        "demo_risk_level",
        "evidence_strength",
        "plain_language_mvp",
        "usable_for_mvp",
    ),
    "clinpgx_mvp_seed/drug_gene_guidelines.csv": (
        "evidence_tier",
        "usable_for_mvp",
    ),
}

#: Columns that identify which source record a legacy row was derived from, so
#: a proposal can name the evidence it would be about.
_LINK_FIELDS = ("annotation_id", "gene", "drug", "pair_key")


@dataclass(frozen=True, slots=True)
class ProposalOrigin:
    """Exactly where one legacy value was read from.

    A file digest is recorded beside the path so a later reader can tell
    whether the file has changed since the proposal was written.
    """

    relative_path: str
    file_sha256: str
    row_number: Optional[int] = None
    line_number: Optional[int] = None
    ast_path: Optional[str] = None

    def to_json(self) -> Dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "file_sha256": self.file_sha256,
            "row_number": self.row_number,
            "line_number": self.line_number,
            "ast_path": self.ast_path,
        }

    @property
    def key(self) -> Tuple[str, int, int]:
        return (self.relative_path, self.row_number or 0, self.line_number or 0)


@dataclass(frozen=True)
class DraftCurationProposal:
    """One unreviewed legacy interpretation, with its origins and its warnings.

    ``linked_evidence`` holds the natural keys of evidence records this
    proposal would be about, when the legacy row named a source record that the
    evidence build actually contains. When it did not, ``linkage_note`` says so
    and the list stays empty - an unlinkable proposal is reported, never
    attached to a plausible neighbour.
    """

    proposal_id: str
    subject: str
    legacy_values: Mapping[str, Any]
    origins: Tuple[ProposalOrigin, ...]
    linked_evidence: Tuple[str, ...] = ()
    linked_record_uuids: Tuple[str, ...] = ()
    linkage_note: str = ""
    status: str = PROPOSAL_STATUS
    warnings: Tuple[str, ...] = PROPOSAL_WARNINGS
    draft_curation_version: str = DRAFT_CURATION_VERSION

    def __post_init__(self) -> None:
        if self.status != PROPOSAL_STATUS:
            raise EvidenceError(
                "a WP-08 draft curation proposal is always %r; %r would claim a "
                "review nobody performed" % (PROPOSAL_STATUS, self.status))
        if tuple(self.warnings) != PROPOSAL_WARNINGS:
            raise EvidenceError(
                "the proposal warnings are fixed; a proposal that dropped one "
                "would read as safer than it is")
        if not self.origins:
            raise EvidenceError(
                "a proposal with no origin cannot be traced to the legacy "
                "value it came from")
        object.__setattr__(self, "origins", tuple(
            sorted(self.origins, key=lambda item: item.key)))
        object.__setattr__(self, "linked_evidence",
                           tuple(sorted(set(self.linked_evidence))))
        object.__setattr__(self, "linked_record_uuids",
                           tuple(sorted(set(self.linked_record_uuids))))

    def content_identity(self) -> Dict[str, Any]:
        return {
            "draft_curation_version": self.draft_curation_version,
            "proposal_id": self.proposal_id,
            "subject": self.subject,
            "status": self.status,
            "warnings": list(self.warnings),
            "legacy_values": dict(sorted(self.legacy_values.items())),
            "origins": [item.to_json() for item in self.origins],
            "linked_evidence": list(self.linked_evidence),
            "linked_record_uuids": list(self.linked_record_uuids),
            "linkage_note": self.linkage_note,
        }

    def content_hash(self) -> str:
        return sha256_digest(self.content_identity())

    def to_json(self) -> Dict[str, Any]:
        payload = self.content_identity()
        payload["content_hash"] = self.content_hash()
        payload["note"] = (
            "A legacy project interpretation, extracted so it is not mistaken "
            "for evidence. Nobody has reviewed it, it is not executable, and "
            "it must not be used for assessment.")
        return payload


@dataclass(frozen=True)
class DraftCurationResult:
    """Every proposal found, and what was read to find them."""

    proposals: Tuple[DraftCurationProposal, ...]
    sources_read: Tuple[Mapping[str, Any], ...]
    field_categories: Mapping[str, int]
    unlinked_count: int
    draft_curation_version: str = DRAFT_CURATION_VERSION

    def content_hash(self) -> str:
        return sha256_digest([item.content_identity()
                              for item in self.proposals])

    def to_json(self) -> Dict[str, Any]:
        return {
            "draft_curation_version": self.draft_curation_version,
            "proposal_count": len(self.proposals),
            "linked_proposal_count": sum(1 for item in self.proposals
                                         if item.linked_evidence),
            "unlinked_proposal_count": self.unlinked_count,
            "field_categories": dict(sorted(self.field_categories.items())),
            "sources_read": [dict(item) for item in self.sources_read],
            "content_hash": self.content_hash(),
            "status": PROPOSAL_STATUS,
            "warnings": list(PROPOSAL_WARNINGS),
        }


def read_manual_effect_hints(repo_root: str,
                             relative_path: str =
                             "clean_mvp_seed_dataset.py"
                             ) -> Tuple[Mapping[Tuple[str, str], Any],
                                        ProposalOrigin, Optional[int]]:
    """Recover ``MANUAL_EFFECT_HINTS`` without executing the legacy script.

    The file is parsed into an AST and only the one assignment's value is
    evaluated, with :func:`ast.literal_eval`, which evaluates literals and
    nothing else - no calls, no attribute access, no imports.

    Importing the module instead would run every top-level statement in it,
    which for this script includes its own file writing. A migration that
    executed the code it was retiring in order to read a constant out of it
    would have acquired exactly the behaviour it set out to remove.
    """
    path = os.path.join(repo_root, relative_path)
    if not os.path.isfile(path):
        raise EvidenceError("no legacy script at %s" % path)
    with io.open(path, "r", encoding="utf-8") as handle:
        source = handle.read()
    digest = "sha256:" + hashlib.sha256(source.encode("utf-8")).hexdigest()
    tree = ast.parse(source, filename=relative_path)

    for node in tree.body:
        targets: List[ast.AST] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if not any(isinstance(target, ast.Name)
                   and target.id == "MANUAL_EFFECT_HINTS"
                   for target in targets):
            continue
        if node.value is None:
            break
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, SyntaxError, TypeError) as exc:
            raise EvidenceError(
                "MANUAL_EFFECT_HINTS at %s:%d is not a literal and will not be "
                "evaluated any other way: %s"
                % (relative_path, node.lineno, exc)) from exc
        if not isinstance(value, Mapping):
            raise EvidenceError(
                "MANUAL_EFFECT_HINTS is a %s, not a mapping"
                % type(value).__name__)
        origin = ProposalOrigin(
            relative_path=relative_path, file_sha256=digest,
            line_number=node.lineno, ast_path="MANUAL_EFFECT_HINTS")
        return dict(value), origin, node.lineno

    raise EvidenceError(
        "no MANUAL_EFFECT_HINTS assignment found in %s" % relative_path)


def extract_draft_curation(repo_root: str,
                           evidence_records: Sequence[Any] = ()
                           ) -> DraftCurationResult:
    """Read every legacy project interpretation into unreviewed proposals.

    ``evidence_records`` is an optional sequence of built evidence records,
    used only to link a proposal to the evidence it would be about.

    Linking is exact and uses two source-declared identifiers, because the
    legacy CSVs and the evidence store spell a record's identity differently.
    A variant annotation's ``id`` is the numeric one the source returns, and
    that is what the evidence record is keyed on; the legacy flattening wrote
    the ``accessionId`` (``PA166338861``) into its ``annotation_id`` column
    instead. Both are fields the source itself published, so matching on either
    is a lookup rather than a guess.

    A row naming neither produces an unlinked proposal with a note. It is never
    attached to a plausible neighbour.
    """
    by_source_id: Dict[str, List[Any]] = {}
    for record in evidence_records:
        by_source_id.setdefault(
            record.natural_key.source_record_id, []).append(record)
        accession = record.raw_source_payload.get("accessionId") \
            if isinstance(record.raw_source_payload, Mapping) else None
        if isinstance(accession, str) and accession.strip():
            by_source_id.setdefault(accession.strip(), []).append(record)

    proposals: Dict[str, Dict[str, Any]] = {}
    sources_read: List[Dict[str, Any]] = []
    categories: Dict[str, int] = {}

    for relative_path, fields in sorted(LEGACY_INTERPRETATION_FIELDS.items()):
        path = os.path.join(repo_root, relative_path)
        if not os.path.isfile(path):
            sources_read.append({"relative_path": relative_path,
                                 "read": False,
                                 "note": "absent from this checkout"})
            continue
        digest = _file_digest(path)
        rows = 0
        with io.open(path, "r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            present = tuple(name for name in fields
                            if name in (reader.fieldnames or ()))
            for row_number, row in enumerate(reader, start=1):
                rows += 1
                values = {name: row.get(name) for name in present
                          if (row.get(name) or "").strip()}
                if not values:
                    continue
                subject = _row_subject(row)
                key = "|".join((relative_path, subject,
                                _stable_value_key(values)))
                entry = proposals.setdefault(key, {
                    "subject": subject, "legacy_values": values,
                    "origins": [], "annotation_ids": set()})
                entry["origins"].append(ProposalOrigin(
                    relative_path=relative_path, file_sha256=digest,
                    row_number=row_number))
                annotation_id = (row.get("annotation_id") or "").strip()
                if annotation_id:
                    entry["annotation_ids"].add(annotation_id)
                for name in values:
                    categories[name] = categories.get(name, 0) + 1
        sources_read.append({"relative_path": relative_path, "read": True,
                             "file_sha256": digest, "row_count": rows,
                             "interpretation_columns": list(present)})

    hints, hint_origin, line_number = read_manual_effect_hints(repo_root)
    sources_read.append({
        "relative_path": hint_origin.relative_path,
        "read": True, "file_sha256": hint_origin.file_sha256,
        "entry_count": len(hints), "line_number": line_number,
        "note": ("read by AST and ast.literal_eval; the legacy script was not "
                 "imported or executed")})
    for pair, payload in hints.items():
        gene, drug = (pair if isinstance(pair, tuple) and len(pair) == 2
                      else (str(pair), ""))
        subject = "%s::%s" % (gene, drug)
        values = {"manual_%s" % name: value
                  for name, value in sorted(dict(payload).items())}
        key = "|".join((hint_origin.relative_path, subject,
                        _stable_value_key(values)))
        entry = proposals.setdefault(key, {
            "subject": subject, "legacy_values": values,
            "origins": [], "annotation_ids": set()})
        entry["origins"].append(hint_origin)
        for name in values:
            categories[name] = categories.get(name, 0) + 1

    built: List[DraftCurationProposal] = []
    unlinked = 0
    for key in sorted(proposals):
        entry = proposals[key]
        linked_keys: List[str] = []
        linked_uuids: List[str] = []
        for annotation_id in sorted(entry["annotation_ids"]):
            for record in by_source_id.get(annotation_id, ()):
                linked_keys.append(record.natural_key.to_string())
                if record.record_uuid:
                    linked_uuids.append(record.record_uuid)
        if linked_keys:
            note = ("linked by the legacy row's annotation_id to evidence "
                    "records carrying the same source record id")
        else:
            unlinked += 1
            note = ("no evidence record in this build carries the source "
                    "record id this legacy row names, so the proposal is left "
                    "unlinked rather than attached to a plausible neighbour")
        built.append(DraftCurationProposal(
            proposal_id="MIGRATION-PROPOSAL-%s"
                        % sha256_digest(key).split(":", 1)[-1][:16],
            subject=entry["subject"],
            legacy_values=dict(sorted(entry["legacy_values"].items())),
            origins=tuple(entry["origins"]),
            linked_evidence=tuple(linked_keys),
            linked_record_uuids=tuple(linked_uuids),
            linkage_note=note))

    return DraftCurationResult(
        proposals=tuple(sorted(built, key=lambda item: item.proposal_id)),
        sources_read=tuple(sources_read),
        field_categories=categories,
        unlinked_count=unlinked)


# -- helpers ------------------------------------------------------------


def _row_subject(row: Mapping[str, Any]) -> str:
    """A readable name for what a legacy row is about."""
    for name in _LINK_FIELDS:
        value = (row.get(name) or "").strip()
        if value:
            gene = (row.get("gene") or "").strip()
            drug = (row.get("drug") or "").strip()
            if gene and drug:
                return "%s::%s/%s" % (gene, drug, value) \
                    if name == "annotation_id" else "%s::%s" % (gene, drug)
            return value
    return "unattributed legacy row"


def _stable_value_key(values: Mapping[str, Any]) -> str:
    return sha256_digest(dict(sorted(values.items()))).split(":", 1)[-1][:16]


def _file_digest(path: str) -> str:
    digest = hashlib.sha256()
    with io.open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()
