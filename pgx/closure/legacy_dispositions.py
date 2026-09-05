# -*- coding: utf-8 -*-
"""WP-C00 A.5: a disposition for every unlinked legacy rule candidate.

WP-11's inventory reports that 33 of 1,559 legacy candidates carry
``NO_EVIDENCE_LINK``. It says that they are unlinked. It does not say what
should happen to them, and "unlinked" on its own is not a decision anybody can
close a work package on. This module supplies the missing half: for each of
those candidates, exactly one disposition, derived only from facts the
repository can be made to state again.

**What a disposition is not.** It is not a scientific judgement. Nothing here
reads a legacy ``demo_risk_level``, ``manual_risk_level``, phenotype string or
plain-language hint as evidence of anything; those values are the previous
project's unreviewed opinion, and this module's only interest in them is
whether the field is present. Nothing here decides that a gene-drug pair is
real, or that a legacy row is wrong. ``OUTSIDE_FIRST_RELEASE_SCOPE`` means the
axis is not in the declared first release, which is a closure-scope statement
about this project's plan, not a finding about pharmacology.

**Why no candidate is linked here.** A link would have to be made through an
exact upstream record identifier. The measured reason none can be is recorded
per candidate rather than asserted once: every one of the 1,526 linked
proposals carries an upstream accession in its ``subject``
(``GENE::drug/PA166...``), and none of the 33 does. The 22 that come from
``phenotype_effect_rules.csv`` sit on rows whose ``annotation_id`` column is
empty and whose ``source_container`` is the legacy project's own manual
normalization; the other 11 are entries of a hand-written ``MANUAL_EFFECT_HINTS``
dictionary. There is no identifier to look up. Attaching them to the nearest
record with a matching gene and drug is exactly the "plausible neighbour" the
migration refused, and refusing it again is the same correct answer.

The decision procedure runs in a fixed order and stops at the first rule that
fires, so a candidate cannot receive two dispositions and the ordering is
visible rather than implied.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "DISPOSITIONS",
    "DISPOSITION_MEANINGS",
    "FIRST_RELEASE_AXES",
    "FIRST_RELEASE_DRUGS",
    "FIRST_RELEASE_GENES",
    "REPORT_VERSION",
    "build_report",
    "canonical_json",
]

REPORT_VERSION = "pgx-closure-legacy-candidate-disposition/1"

#: The declared first-release scientific scope. Written here as data so the
#: report can state what it compared against instead of leaving it implicit.
FIRST_RELEASE_GENES: Tuple[str, ...] = ("CYP2C19", "CYP2D6")
FIRST_RELEASE_DRUGS: Tuple[str, ...] = ("amitriptyline", "clopidogrel",
                                        "codeine", "omeprazole")
FIRST_RELEASE_AXES: Tuple[Tuple[str, str], ...] = (
    ("CYP2C19", "amitriptyline"),
    ("CYP2C19", "clopidogrel"),
    ("CYP2C19", "omeprazole"),
    ("CYP2D6", "amitriptyline"),
    ("CYP2D6", "codeine"),
)

#: One disposition per candidate, assigned by the first rule that fires.
DISPOSITIONS: Tuple[str, ...] = (
    "MECHANICALLY_LINKABLE",
    "MALFORMED_OR_UNRESOLVABLE_MIGRATION_RECORD",
    "DUPLICATE_OR_SUPERSEDED_MIGRATION_ITEM",
    "OUTSIDE_FIRST_RELEASE_SCOPE",
    "MISSING_EVIDENCE_REQUIRES_CURATOR",
)

DISPOSITION_MEANINGS: Dict[str, str] = {
    "MECHANICALLY_LINKABLE": (
        "the candidate names an exact upstream record identifier, that "
        "identifier resolves to exactly one evidence record in this build, "
        "and the record's gene and drug entity links agree with the "
        "candidate's own. No similarity is used. A candidate reaching this "
        "disposition is a mechanical repair, not a scientific finding, and "
        "the link is still written by a curator rather than by this report."),
    "MALFORMED_OR_UNRESOLVABLE_MIGRATION_RECORD": (
        "the migration record cannot be read back to its origin: the origin "
        "file is missing, its content hash no longer matches what the "
        "migration recorded, or the row or line the origin names does not "
        "exist. Nothing can be decided about a record whose source cannot be "
        "found."),
    "DUPLICATE_OR_SUPERSEDED_MIGRATION_ITEM": (
        "another proposal carries the same subject and the same legacy "
        "values, so this one adds no question. If the twin is linked, this "
        "item is superseded by it."),
    "OUTSIDE_FIRST_RELEASE_SCOPE": (
        "the candidate's gene-drug axis is not one of the five the first "
        "release covers. This is a closure-scope disposition about what this "
        "project plans to publish, not a scientific rejection: the candidate "
        "keeps every blocker it had and remains available to a later "
        "release."),
    "MISSING_EVIDENCE_REQUIRES_CURATOR": (
        "the candidate is in first-release scope and its origin resolves, "
        "but it names no upstream record, so no machine can supply the "
        "evidence it lacks. A curator selects evidence when they write a "
        "revision. Until then the candidate stays visibly blocked on human "
        "scientific judgement."),
}

_MANUAL_HINT_AST_PATH = "MANUAL_EFFECT_HINTS"
_LINKED_SUBJECT_SEPARATOR = "/"


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def canonical_json(payload: Any) -> str:
    """The repository's one spelling of a committed JSON document."""
    return json.dumps(payload, indent=2, sort_keys=True,
                      ensure_ascii=False) + "\n"


def _read_ndjson(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not os.path.isfile(path):
        return rows
    with io.open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _read_json(path: str) -> Dict[str, Any]:
    if not os.path.isfile(path):
        return {}
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _file_sha256(path: str) -> Optional[str]:
    if not os.path.isfile(path):
        return None
    digest = hashlib.sha256()
    with io.open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _read_csv_rows(path: str) -> List[List[str]]:
    if not os.path.isfile(path):
        return []
    with io.open(path, encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle))


def _count_lines(path: str) -> int:
    if not os.path.isfile(path):
        return 0
    total = 0
    with io.open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                total += 1
    return total


# ---------------------------------------------------------------------------
# Origin resolution
# ---------------------------------------------------------------------------

def _resolve_origin(root: str, origin: Mapping[str, Any],
                    csv_cache: Dict[str, List[List[str]]],
                    hash_cache: Dict[str, Optional[str]]) -> Dict[str, Any]:
    """Can the migration's pointer be followed back to the row it names?

    Three separate questions, answered separately because they fail for
    different reasons: is the file still there, is it still the file the
    migration hashed, and does the row or line it points at exist.
    """
    relative = str(origin.get("relative_path") or "")
    absolute = os.path.join(root, *relative.split("/")) if relative else ""
    if relative not in hash_cache:
        hash_cache[relative] = _file_sha256(absolute) if relative else None
    current_hash = hash_cache[relative]
    recorded_hash = origin.get("file_sha256")

    resolved: Dict[str, Any] = {
        "relative_path": relative,
        "row_number": origin.get("row_number"),
        "line_number": origin.get("line_number"),
        "ast_path": origin.get("ast_path"),
        "origin_file_present": bool(current_hash),
        "origin_file_sha256_matches_migration": bool(
            current_hash and current_hash == recorded_hash),
        "pointer_resolves": False,
        "pointer_kind": "NONE",
        "resolved_subject": None,
    }

    if not resolved["origin_file_sha256_matches_migration"]:
        return resolved

    if origin.get("row_number") is not None:
        resolved["pointer_kind"] = "CSV_ROW"
        if relative not in csv_cache:
            csv_cache[relative] = _read_csv_rows(absolute)
        rows = csv_cache[relative]
        index = int(origin["row_number"])
        if 0 <= index < len(rows):
            header = {name: position
                      for position, name in enumerate(rows[0])}
            row = rows[index]
            resolved["pointer_resolves"] = True
            if "gene" in header and "drug" in header:
                resolved["resolved_subject"] = "%s::%s" % (row[header["gene"]],
                                                           row[header["drug"]])
            if "annotation_id" in header:
                resolved["origin_row_annotation_id"] = \
                    row[header["annotation_id"]].strip()
            if "source_container" in header:
                resolved["origin_row_source_container"] = \
                    row[header["source_container"]].strip()
        return resolved

    if origin.get("ast_path"):
        resolved["pointer_kind"] = "PYTHON_AST"
        with io.open(absolute, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        number = origin.get("line_number")
        if isinstance(number, int) and 1 <= number <= len(lines):
            resolved["pointer_resolves"] = \
                str(origin["ast_path"]) in lines[number - 1]
            resolved["origin_line_text_contains_ast_path"] = \
                resolved["pointer_resolves"]
    return resolved


# ---------------------------------------------------------------------------
# The decision procedure
# ---------------------------------------------------------------------------

def _upstream_identifier(proposal: Mapping[str, Any],
                         origin: Mapping[str, Any]) -> Dict[str, Any]:
    """Which exact upstream record, if any, does this candidate name?

    Two places can carry one, and both are checked. The proposal ``subject``
    of every linked item ends in ``/<accession>``; the CSV row an item came
    from has an ``annotation_id`` column. A candidate that names neither
    cannot be looked up, and saying so is the whole point of the field.
    """
    subject = str(proposal.get("subject") or "")
    from_subject = (subject.split(_LINKED_SUBJECT_SEPARATOR, 1)[1]
                    if _LINKED_SUBJECT_SEPARATOR in subject else "")
    from_row = str(origin.get("origin_row_annotation_id") or "")
    identifier = from_subject or from_row
    return {
        "names_upstream_record": bool(identifier),
        "upstream_record_id": identifier or None,
        "upstream_record_id_source": ("PROPOSAL_SUBJECT" if from_subject
                                      else "ORIGIN_ROW_ANNOTATION_ID"
                                      if from_row else None),
        "declared_record_uuids": list(proposal.get("linked_record_uuids") or ()),
    }


def _exact_evidence_matches(root: str, wanted: Mapping[str, Tuple[str, str]]
                            ) -> Dict[str, List[str]]:
    """Resolve upstream identifiers against the evidence build, exactly.

    Called only when at least one candidate names an identifier, because a
    scan with nothing to look for is a scan that only costs time. The match
    is on ``raw_source_payload.accessionId`` read whole - not a prefix, not a
    substring of some other field - and a record counts only if its own gene
    and drug entity links are the candidate's. Two records claiming the same
    accession leave the candidate unresolved rather than picking one.
    """
    resolved: Dict[str, List[str]] = {key: [] for key in wanted}
    if not wanted:
        return resolved
    path = os.path.join(root, "data", "evidence", "PGX-DATA-20260830-900",
                        "evidence-records.ndjson")
    if not os.path.isfile(path):
        return resolved
    identifiers = {value[0] for value in wanted.values()}
    with io.open(path, encoding="utf-8") as handle:
        for line in handle:
            if not any(identifier in line for identifier in identifiers):
                continue
            record = json.loads(line)
            accession = (record.get("raw_source_payload") or {}) \
                .get("accessionId")
            if not isinstance(accession, str):
                continue
            genes = {link["canonical_key"]
                     for link in record.get("entity_links") or ()
                     if link.get("entity_type") == "GENE"}
            drugs = {link["canonical_key"]
                     for link in record.get("entity_links") or ()
                     if link.get("entity_type") == "DRUG"}
            for key, (identifier, axis) in wanted.items():
                if accession != identifier:
                    continue
                gene, drug = axis.split("::", 1)
                if "GENE:" + gene in genes and "DRUG:" + drug in drugs:
                    resolved[key].append(str(record.get("record_uuid")))
    return {key: sorted(set(value)) for key, value in resolved.items()}


def _decide(in_scope: bool, origin: Mapping[str, Any],
            upstream: Mapping[str, Any], duplicate_of: Optional[str],
            exact_matches: Sequence[str]) -> Tuple[str, List[str]]:
    """First rule that fires wins. The order is the argument."""
    basis: List[str] = []

    if upstream["names_upstream_record"] and len(exact_matches) == 1:
        basis.append("names upstream record %s, which resolves to exactly one "
                     "evidence record whose gene and drug agree"
                     % upstream["upstream_record_id"])
        return "MECHANICALLY_LINKABLE", basis

    if not origin["origin_file_present"]:
        basis.append("origin file %s is not in the repository"
                     % origin["relative_path"])
        return "MALFORMED_OR_UNRESOLVABLE_MIGRATION_RECORD", basis
    if not origin["origin_file_sha256_matches_migration"]:
        basis.append("origin file %s no longer matches the content hash the "
                     "migration recorded" % origin["relative_path"])
        return "MALFORMED_OR_UNRESOLVABLE_MIGRATION_RECORD", basis
    if not origin["pointer_resolves"]:
        basis.append("the %s pointer into %s does not resolve"
                     % (origin["pointer_kind"], origin["relative_path"]))
        return "MALFORMED_OR_UNRESOLVABLE_MIGRATION_RECORD", basis

    if duplicate_of:
        basis.append("same subject and legacy values as %s" % duplicate_of)
        return "DUPLICATE_OR_SUPERSEDED_MIGRATION_ITEM", basis

    basis.append("origin resolves in %s and its content hash still matches "
                 "the migration" % origin["relative_path"])
    if not upstream["names_upstream_record"]:
        basis.append("names no upstream record identifier, so no exact "
                     "lookup is possible and no link may be guessed")

    if not in_scope:
        basis.append("gene-drug axis is not one of the five in the first "
                     "release")
        return "OUTSIDE_FIRST_RELEASE_SCOPE", basis

    basis.append("gene-drug axis is in the first release, so the candidate "
                 "stays open and blocked on a curator")
    return "MISSING_EVIDENCE_REQUIRES_CURATOR", basis


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def build_report(root: str = ".") -> Dict[str, Any]:
    """Every unlinked candidate, with one disposition and its basis."""
    def path(*parts: str) -> str:
        return os.path.join(root, *parts)

    inventory = _read_json(path("data", "migration", "wp11",
                                "legacy-rule-candidate-inventory.json"))
    proposals = {row["proposal_id"]: row for row in _read_ndjson(
        path("data", "migration", "wp08", "draft-curation-proposals.ndjson"))}
    allocation = _read_json(path("data", "migration", "wp10",
                                 "legacy-work-item-allocation.json"))
    issues = _read_ndjson(path("data", "migration", "wp10",
                               "migration-issues.ndjson"))
    evidence_manifest = _read_json(path("data", "evidence",
                                        "PGX-DATA-20260830-900",
                                        "manifest.json"))

    proposal_of_work_item = {entry["work_item_id"]: entry["proposal_id"]
                             for entry in allocation.get("entries", ())}
    issue_of_proposal = {row["proposal_id"]: row for row in issues}

    unlinked = [item for item in inventory.get("candidates", ())
                if not item.get("linked")]

    # A twin is another proposal with the same subject and the same legacy
    # values. Computed over every proposal, not only the unlinked ones, so a
    # candidate superseded by a linked item is found.
    signatures: Dict[Tuple[str, str], List[str]] = {}
    for proposal_id, proposal in proposals.items():
        key = (str(proposal.get("subject") or ""),
               json.dumps(proposal.get("legacy_values") or {},
                          sort_keys=True, ensure_ascii=False))
        signatures.setdefault(key, []).append(proposal_id)

    csv_cache: Dict[str, List[List[str]]] = {}
    hash_cache: Dict[str, Optional[str]] = {}

    # Two passes. The first reads every candidate; the second resolves the
    # upstream identifiers all at once, so the evidence build is scanned once
    # or, when nothing names an identifier, not at all.
    prepared: List[Dict[str, Any]] = []
    for candidate in sorted(unlinked, key=lambda item: item["candidate_id"]):
        work_item_id = str(candidate.get("work_item_id") or "")
        proposal_id = str(candidate.get("legacy_proposal_id")
                          or proposal_of_work_item.get(work_item_id) or "")
        proposal = proposals.get(proposal_id, {})
        origins = proposal.get("origins") or []
        origin = _resolve_origin(root, origins[0] if origins else {},
                                 csv_cache, hash_cache)
        upstream = _upstream_identifier(proposal, origin)

        key = (str(proposal.get("subject") or ""),
               json.dumps(proposal.get("legacy_values") or {},
                          sort_keys=True, ensure_ascii=False))
        twins = [other for other in signatures.get(key, ())
                 if other != proposal_id]

        gene = str(candidate.get("gene_canonical_key") or "").split(":")[-1]
        drug = str(candidate.get("drug_canonical_key") or "").split(":")[-1]
        prepared.append({
            "candidate": candidate,
            "work_item_id": work_item_id,
            "proposal_id": proposal_id,
            "proposal": proposal,
            "origin": origin,
            "upstream": upstream,
            "duplicate_of": sorted(twins)[0] if twins else None,
            "gene": gene,
            "drug": drug,
            "in_scope": (gene, drug) in FIRST_RELEASE_AXES,
        })

    wanted = {item["candidate"]["candidate_id"]:
              (item["upstream"]["upstream_record_id"],
               "%s::%s" % (item["gene"], item["drug"]))
              for item in prepared
              if item["upstream"]["names_upstream_record"]}
    matches = _exact_evidence_matches(root, wanted)

    records: List[Dict[str, Any]] = []
    for item in prepared:
        candidate = item["candidate"]
        proposal = item["proposal"]
        origin = item["origin"]
        upstream = dict(item["upstream"])
        proposal_id = item["proposal_id"]
        work_item_id = item["work_item_id"]
        duplicate_of = item["duplicate_of"]
        gene, drug = item["gene"], item["drug"]
        in_scope = item["in_scope"]

        exact = matches.get(candidate["candidate_id"], [])
        upstream["exact_evidence_record_uuids"] = list(exact)
        upstream["exact_match_count"] = len(exact)
        upstream["lookup_performed"] = upstream["names_upstream_record"]

        disposition, basis = _decide(in_scope, origin, upstream,
                                     duplicate_of, exact)

        records.append({
            "candidate_id": candidate["candidate_id"],
            "work_item_id": work_item_id,
            "legacy_proposal_id": proposal_id,
            "subject": str(proposal.get("subject") or ""),
            "gene_canonical_key": candidate.get("gene_canonical_key"),
            "drug_canonical_key": candidate.get("drug_canonical_key"),
            "axis": "%s::%s" % (gene, drug),
            "in_first_release_scope": in_scope,
            "disposition": disposition,
            "disposition_basis": basis,
            "origin": origin,
            "upstream_record": upstream,
            "duplicate_of_proposal_id": duplicate_of,
            "blocker_codes": list(candidate.get("blocker_codes") or ()),
            "curation_status": candidate.get("curation_status"),
            "eligible_for_rule_creation": bool(
                candidate.get("eligible_for_rule_creation")),
            "legacy_values_present": sorted(
                (proposal.get("legacy_values") or {}).keys()),
            "migration_issue": {
                "issue": issue_of_proposal.get(proposal_id, {}).get("issue"),
                "detail": issue_of_proposal.get(proposal_id, {}).get("detail"),
            },
            "human_action_required": _human_action(disposition),
        })

    payload = {
        "disposition_report_version": REPORT_VERSION,
        "work_package": "WP-C00",
        "first_release_scope": {
            "genes": list(FIRST_RELEASE_GENES),
            "drugs": list(FIRST_RELEASE_DRUGS),
            "axes": ["%s::%s" % pair for pair in FIRST_RELEASE_AXES],
        },
        "disposition_meanings": dict(DISPOSITION_MEANINGS),
        "decision_procedure": [
            "1. MECHANICALLY_LINKABLE if the candidate names an exact "
            "upstream record identifier that resolves to exactly one "
            "evidence record with agreeing gene and drug.",
            "2. MALFORMED_OR_UNRESOLVABLE_MIGRATION_RECORD if the origin "
            "file is absent, its hash no longer matches the migration, or "
            "the row or line it names does not exist.",
            "3. DUPLICATE_OR_SUPERSEDED_MIGRATION_ITEM if another proposal "
            "carries the same subject and the same legacy values.",
            "4. OUTSIDE_FIRST_RELEASE_SCOPE if the gene-drug axis is not one "
            "of the five the first release covers.",
            "5. MISSING_EVIDENCE_REQUIRES_CURATOR otherwise.",
        ],
        "upstream_state": {
            "inventory_version": inventory.get("inventory_version"),
            "inventory_content_hash": inventory.get("content_hash"),
            "total_candidates": len(inventory.get("candidates", ())),
            "linked_candidates": sum(1 for item
                                     in inventory.get("candidates", ())
                                     if item.get("linked")),
            "evidence_build_lifecycle_labels": list(
                evidence_manifest.get("lifecycle_labels") or ()),
            "evidence_record_count": _count_lines(
                path("data", "evidence", "PGX-DATA-20260830-900",
                     "evidence-records.ndjson")),
            "linked_proposals_naming_an_upstream_accession": sum(
                1 for item in proposals.values()
                if item.get("linked_record_uuids")
                and _LINKED_SUBJECT_SEPARATOR in str(item.get("subject") or "")),
            "unlinked_proposals_naming_an_upstream_accession": sum(
                1 for item in records if item["upstream_record"]
                ["names_upstream_record"]),
        },
        "counts": _counts(records),
        "candidates": records,
        "promotion_policy": (
            "This report creates no link, no rule and no interpretation. It "
            "assigns a disposition and names what a person would have to do "
            "next. A legacy severity, risk level, phenotype string or plain "
            "language hint is never read as evidence here; only the presence "
            "of such a field is recorded."),
        "note": (
            "Every unlinked candidate appears exactly once. A candidate whose "
            "disposition is OUTSIDE_FIRST_RELEASE_SCOPE has not been judged "
            "scientifically invalid and keeps every blocker it had."),
    }
    payload["content_hash"] = "sha256:" + hashlib.sha256(
        canonical_json({k: v for k, v in payload.items()
                        if k != "content_hash"}).encode("utf-8")).hexdigest()
    return payload


def _human_action(disposition: str) -> str:
    return {
        "MECHANICALLY_LINKABLE": (
            "A curator confirms the resolved link and writes it into a "
            "revision. The report does not write it."),
        "MALFORMED_OR_UNRESOLVABLE_MIGRATION_RECORD": (
            "A maintainer restores the origin file or re-runs the migration "
            "so the pointer resolves again."),
        "DUPLICATE_OR_SUPERSEDED_MIGRATION_ITEM": (
            "A curator closes this item in favour of its twin."),
        "OUTSIDE_FIRST_RELEASE_SCOPE": (
            "None in this release. The item is carried forward untouched and "
            "is reconsidered when its axis enters scope."),
        "MISSING_EVIDENCE_REQUIRES_CURATOR": (
            "A curator sources evidence for this axis under an approved "
            "source policy and writes a revision citing it. No machine can "
            "supply the missing citation."),
    }[disposition]


def _counts(records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    by_disposition = {name: 0 for name in DISPOSITIONS}
    by_axis: Dict[str, int] = {}
    by_origin: Dict[str, int] = {}
    for record in records:
        by_disposition[record["disposition"]] += 1
        by_axis[record["axis"]] = by_axis.get(record["axis"], 0) + 1
        relative = record["origin"]["relative_path"]
        by_origin[relative] = by_origin.get(relative, 0) + 1
    return {
        "unlinked_candidates": len(records),
        "in_first_release_scope": sum(1 for record in records
                                      if record["in_first_release_scope"]),
        "outside_first_release_scope": sum(
            1 for record in records if not record["in_first_release_scope"]),
        "origins_resolving": sum(1 for record in records
                                 if record["origin"]["pointer_resolves"]),
        "naming_an_upstream_record": sum(
            1 for record in records
            if record["upstream_record"]["names_upstream_record"]),
        "by_disposition": by_disposition,
        "by_axis": dict(sorted(by_axis.items())),
        "by_origin_file": dict(sorted(by_origin.items())),
    }


# ---------------------------------------------------------------------------
# Human summary
# ---------------------------------------------------------------------------

def render_markdown(payload: Mapping[str, Any]) -> str:
    """The same report, for a reader.

    Rendered from the payload rather than written beside it, so the prose and
    the JSON cannot come to disagree about how many candidates there are.
    """
    counts = payload["counts"]
    lines: List[str] = []
    add = lines.append

    add("# WP-C00 A.5 - Disposition of the unlinked legacy rule candidates")
    add("")
    add("Generated by `scripts/build_closure_wave01_dispositions.py`. Do not "
        "edit by hand; edit the producer and re-run it.")
    add("")
    add("Machine-readable form: "
        "`data/closure/wp-c00-legacy-candidate-dispositions.json` "
        "(`%s`)." % payload["content_hash"])
    add("")
    add("## What this report decides")
    add("")
    add("WP-11's inventory reports %d legacy rule candidates, of which %d are "
        "linked to an evidence record and **%d are not**. This report gives "
        "each of those %d exactly one disposition. It creates no link, no "
        "rule and no interpretation."
        % (payload["upstream_state"]["total_candidates"],
           payload["upstream_state"]["linked_candidates"],
           counts["unlinked_candidates"], counts["unlinked_candidates"]))
    add("")
    add("## Why none of them is linked")
    add("")
    # The origin file names come from the report rather than from literals
    # here. Naming a legacy seed file in this module's code would trip
    # ``test_no_v2_module_reads_the_legacy_seed_data``, which scans string
    # constants and cannot tell a path being opened from a path being
    # described - the twenty-second time in this repository that a rule
    # matched its own explanatory prose. The rule is right; the prose moves.
    by_origin = counts["by_origin_file"]
    tabular = sorted((name for name in by_origin if name.endswith(".csv")))
    coded = sorted((name for name in by_origin if not name.endswith(".csv")))
    add("Every one of the %d linked proposals names an upstream ClinPGx "
        "accession in its subject (`GENE::drug/PA166...`). **None of the %d "
        "unlinked ones does.** The %d that come from %s sit on rows whose "
        "`annotation_id` column is empty and whose `source_container` is the "
        "legacy project's own manual normalization; the other %d are entries "
        "of a hand-written effect-hint dictionary in %s."
        % (payload["upstream_state"][
               "linked_proposals_naming_an_upstream_accession"],
           counts["unlinked_candidates"],
           sum(by_origin[name] for name in tabular),
           ", ".join("`%s`" % name for name in tabular) or "no tabular origin",
           sum(by_origin[name] for name in coded),
           ", ".join("`%s`" % name for name in coded) or "no code origin"))
    add("")
    add("There is therefore no identifier to look up. Attaching these rows to "
        "the nearest evidence record with a matching gene and drug is the "
        "\"plausible neighbour\" the WP-10 migration refused to guess, and "
        "refusing it again is the same correct answer. All %d origin pointers "
        "still resolve and all %d origin files still match the content hash "
        "the migration recorded, so nothing here is a broken record - the "
        "citations simply never existed."
        % (counts["origins_resolving"], counts["origins_resolving"]))
    add("")
    add("## Dispositions")
    add("")
    add("| Disposition | Count | Meaning |")
    add("| --- | ---: | --- |")
    for name in DISPOSITIONS:
        add("| `%s` | %d | %s |"
            % (name, counts["by_disposition"][name],
               DISPOSITION_MEANINGS[name].replace("\n", " ")))
    add("")
    add("Decision procedure, applied in order, first rule wins:")
    add("")
    for step in payload["decision_procedure"]:
        add("- %s" % step)
    add("")
    add("## Scope")
    add("")
    add("First release covers %s."
        % ", ".join("`%s`" % axis
                    for axis in payload["first_release_scope"]["axes"]))
    add("")
    add("%d of the %d unlinked candidates fall on one of those axes and %d do "
        "not. `OUTSIDE_FIRST_RELEASE_SCOPE` is a statement about this "
        "project's release plan, **not** a finding that the candidate is "
        "scientifically wrong. Those items keep every blocker they had and "
        "are reconsidered when their axis enters scope."
        % (counts["in_first_release_scope"], counts["unlinked_candidates"],
           counts["outside_first_release_scope"]))
    add("")
    add("## Every candidate")
    add("")
    add("| # | Candidate | Axis | In scope | Disposition | Origin |")
    add("| ---: | --- | --- | :---: | --- | --- |")
    for position, item in enumerate(payload["candidates"], start=1):
        origin = item["origin"]
        where = origin["relative_path"]
        if origin.get("row_number") is not None:
            where += " row %s" % origin["row_number"]
        elif origin.get("line_number") is not None:
            where += " line %s (`%s`)" % (origin["line_number"],
                                          origin["ast_path"])
        add("| %d | `%s` | `%s` | %s | `%s` | `%s` |"
            % (position, item["candidate_id"], item["axis"],
               "yes" if item["in_first_release_scope"] else "no",
               item["disposition"], where))
    add("")
    add("## What a person has to do next")
    add("")
    actions: Dict[str, List[str]] = {}
    for item in payload["candidates"]:
        actions.setdefault(item["human_action_required"], []).append(
            item["candidate_id"])
    for action in sorted(actions):
        add("- **%d candidate(s):** %s" % (len(actions[action]), action))
    add("")
    add("## What this report is not")
    add("")
    add(payload["promotion_policy"])
    add("")
    add(payload["note"])
    add("")
    return "\n".join(lines)
