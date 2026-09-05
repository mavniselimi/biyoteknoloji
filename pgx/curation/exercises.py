# -*- coding: utf-8 -*-
"""The inter-curator exercise and its comparison (WP-09).

Two scientists answer the same questions independently, and the two answers are
compared field by field. That is the whole design, and every constraint on it
follows from one observation: **agreement is not correctness**. Two curators
who agree may both be wrong, and a comparison that treated agreement as
validity would manufacture confidence out of a coincidence.

So this module reports differences and stops. It does not decide who is right,
merge two answers, generate a consensus, score agreement, or adjudicate. An
adjudication is a separate act by a named third person who keeps both original
responses intact.

Case selection is deterministic: the same evidence build yields the same packet
byte for byte. A packet that varied between runs could not be shown to be
representative rather than convenient.

Legacy hints are **blinded**. A curator who has seen what the project
previously concluded is no longer forming an independent view of the evidence,
and the comparison would be measuring agreement with the legacy answer.
"""

from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass, field
from typing import (Any, Dict, Iterable, List, Mapping, Optional, Sequence,
                    Tuple)

from pgx.curation.errors import CurationError, RoleSeparationError
from pgx.curation.vocabulary import (Applicability, CaseRole, ConclusionState,
                                     ConflictState, EffectDimension,
                                     ExclusionReason)
from pgx.domain.hashing import sha256_digest

__all__ = [
    "EXERCISE_STATUS_AWAITING",
    "EXERCISE_VERSION",
    "COMPARISON_VERSION",
    "COMPARED_FIELDS",
    "AdjudicationTemplate",
    "ComparisonReport",
    "CuratorResponse",
    "ExerciseCase",
    "ExercisePacket",
    "build_exercise_packet",
    "compare_responses",
    "response_template",
]

EXERCISE_VERSION = "pgx-inter-curator-exercise/1"
COMPARISON_VERSION = "pgx-inter-curator-comparison/1"

#: The state the real exercise stays in until two named humans complete it.
EXERCISE_STATUS_AWAITING = "AWAITING_HUMAN_CURATORS"

#: The fields the comparison reports on, and how each is compared. Set-valued
#: fields are compared as sets because the order a curator listed evidence in
#: is not a disagreement.
COMPARED_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("included_evidence", "set"),
    ("excluded_evidence", "set"),
    ("exclusion_reasons", "mapping"),
    ("normalized_phenotypes", "set"),
    ("effect_dimension", "scalar"),
    ("conclusion_state", "scalar"),
    ("applicability", "scalar"),
    ("conflict_state", "scalar"),
    ("insufficiency_reasons", "set"),
)

#: Case selection targets these situations, in this order. Each names a place
#: the protocol makes a demand that a straightforward case would not exercise.
#:
#: Several selectors pin a record type deliberately. Natural keys sort with
#: DRUG_LABEL_ANNOTATION first, so an unpinned "unknown version" selector would
#: keep returning drug labels and the packet would be alphabetically skewed
#: rather than representative. Pinning the type makes the situation the
#: selector describes the thing that actually varies.
CASE_SELECTORS: Tuple[Tuple[str, str], ...] = (
    ("GUIDELINE_WITH_STATED_ORIGIN",
     "A guideline annotation naming the body that asserted it."),
    ("VARIANT_ANNOTATION_WITH_PUBLICATION",
     "A variant annotation citing a publication, with a source-reported "
     "significance and score the curator must not read as a conclusion."),
    ("MULTIPLE_PUBLICATIONS",
     "A record citing several distinct publications."),
    ("MULTI_GENE_OR_MULTI_DRUG",
     "One record naming more than one gene or more than one drug."),
    ("UNKNOWN_SOURCE_VERSION",
     "A variant annotation whose source version could not be recovered."),
    ("NO_STATED_ORIGIN",
     "A variant annotation that does not say who asserted it."),
    ("PENDING_RECORD_TYPE_MAPPING",
     "A record whose label/DrugLabel type mapping is unproven."),
    ("MULTIPLE_LOCATORS",
     "A record found under several containers, retained as several locators."),
    ("LINKED_LEGACY_HINT",
     "A record a legacy manual hint points at, with the hint blinded."),
)


@dataclass(frozen=True)
class ExerciseCase:
    """One question put to both curators.

    Carries evidence identifiers and the neutral facts a curator needs to find
    the evidence. It carries no expected answer, no legacy conclusion and no
    hint about what the answer should be - a packet that did would be
    measuring recall of the packet.
    """

    case_id: str
    selector: str
    selector_reason: str
    case_role: CaseRole
    evidence_record_uuids: Tuple[str, ...]
    natural_keys: Tuple[str, ...]
    gene_canonical_keys: Tuple[str, ...]
    drug_canonical_keys: Tuple[str, ...]
    record_types: Tuple[str, ...]
    source_version_statuses: Tuple[str, ...]
    origin_statuses: Tuple[str, ...]
    publication_identities: Tuple[str, ...]
    locator_count: int
    linked_legacy_proposal_ids: Tuple[str, ...] = ()
    legacy_hint_blinded: bool = True

    def __post_init__(self) -> None:
        if not str(self.case_id).strip():
            raise CurationError("case_id is required")
        if not isinstance(self.case_role, CaseRole):
            raise CurationError("case_role must be a CaseRole")
        if not self.evidence_record_uuids:
            raise CurationError(
                "case %s cites no evidence; there would be nothing to curate"
                % self.case_id)
        if not self.legacy_hint_blinded:
            raise CurationError(
                "case %s would reveal the legacy conclusion before the "
                "curator forms their own. The hint is revealed after the "
                "response, for migration comparison only." % self.case_id)
        for name in ("evidence_record_uuids", "natural_keys",
                     "gene_canonical_keys", "drug_canonical_keys",
                     "record_types", "source_version_statuses",
                     "origin_statuses", "publication_identities",
                     "linked_legacy_proposal_ids"):
            object.__setattr__(self, name, tuple(getattr(self, name)))

    def content_identity(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "selector": self.selector,
            "selector_reason": self.selector_reason,
            "case_role": self.case_role.value,
            "evidence_record_uuids": list(self.evidence_record_uuids),
            "natural_keys": list(self.natural_keys),
            "gene_canonical_keys": list(self.gene_canonical_keys),
            "drug_canonical_keys": list(self.drug_canonical_keys),
            "record_types": list(self.record_types),
            "source_version_statuses": list(self.source_version_statuses),
            "origin_statuses": list(self.origin_statuses),
            "publication_identities": list(self.publication_identities),
            "locator_count": self.locator_count,
            "linked_legacy_proposal_ids": list(self.linked_legacy_proposal_ids),
            "legacy_hint_blinded": self.legacy_hint_blinded,
        }

    def to_json(self) -> Dict[str, Any]:
        payload = self.content_identity()
        payload["note"] = (
            "No expected answer is included. The linked legacy proposal ids "
            "name hints that stay blinded until after the response is "
            "recorded.")
        return payload


@dataclass(frozen=True)
class ExercisePacket:
    """The complete exercise: cases, status, and what it is not.

    ``status`` stays ``AWAITING_HUMAN_CURATORS`` until two named people have
    completed it. Nothing in this package can move it, because moving it would
    be asserting that the review happened.
    """

    exercise_id: str
    cases: Tuple[ExerciseCase, ...]
    evidence_build_key: str
    evidence_build_content_hash: str
    unmatched_selectors: Tuple[Mapping[str, str], ...] = ()
    status: str = EXERCISE_STATUS_AWAITING
    exercise_version: str = EXERCISE_VERSION

    def __post_init__(self) -> None:
        ids = [item.case_id for item in self.cases]
        if len(set(ids)) != len(ids):
            raise CurationError("a case id appears twice in the packet")
        if not self.cases:
            raise CurationError("an exercise with no cases asks nothing")
        roles = {item.case_role for item in self.cases}
        if roles != {CaseRole.INTER_CURATOR_EXERCISE}:
            raise CurationError(
                "every case in an exercise packet holds the "
                "INTER_CURATOR_EXERCISE role; found %s"
                % ", ".join(sorted(item.value for item in roles)))

    def content_identity(self) -> Dict[str, Any]:
        return {
            "exercise_version": self.exercise_version,
            "exercise_id": self.exercise_id,
            "evidence_build_key": self.evidence_build_key,
            "evidence_build_content_hash": self.evidence_build_content_hash,
            "cases": [item.content_identity() for item in self.cases],
            "unmatched_selectors": [dict(sorted(item.items()))
                                    for item in self.unmatched_selectors],
        }

    def content_hash(self) -> str:
        return sha256_digest(self.content_identity())

    def to_json(self) -> Dict[str, Any]:
        payload = self.content_identity()
        payload["status"] = self.status
        payload["case_count"] = len(self.cases)
        payload["content_hash"] = self.content_hash()
        payload["note"] = (
            "Two named scientists complete this independently. Agreement "
            "between them is not evidence that either is correct, and this "
            "packet contains no expected answers.")
        return payload


@dataclass(frozen=True)
class CuratorResponse:
    """One curator's answers to one packet.

    ``is_complete`` is what the comparison consults. A template with blank
    answers is a template; treating it as a response would let a comparison
    report perfect agreement between two people who answered nothing.
    """

    exercise_id: str
    curator_label: str
    curator_name: Optional[str]
    answers: Mapping[str, Mapping[str, Any]]
    completed: bool = False

    def __post_init__(self) -> None:
        if not str(self.curator_label).strip():
            raise CurationError("curator_label is required")
        if not isinstance(self.answers, Mapping):
            raise CurationError("answers must be a mapping of case id to answer")
        object.__setattr__(self, "answers", {
            key: dict(value) for key, value in sorted(self.answers.items())})

    @property
    def is_complete(self) -> bool:
        """Whether a person actually answered.

        Requires a name and a non-empty answer for every case. Absent either,
        this is a blank form, and the comparison refuses it rather than
        producing a report about nothing.
        """
        if not (self.curator_name or "").strip():
            return False
        if not self.answers:
            return False
        for answer in self.answers.values():
            if not _answered(answer):
                return False
        return bool(self.completed)

    def content_identity(self) -> Dict[str, Any]:
        return {
            "exercise_id": self.exercise_id,
            "curator_label": self.curator_label,
            "curator_name": self.curator_name,
            "answers": {key: dict(value)
                        for key, value in sorted(self.answers.items())},
            "completed": self.completed,
        }

    def to_json(self) -> Dict[str, Any]:
        payload = self.content_identity()
        payload["is_complete"] = self.is_complete
        return payload


def _answered(answer: Mapping[str, Any]) -> bool:
    """Whether one case answer carries anything at all."""
    required = ("conclusion_state", "effect_dimension", "applicability",
                "conflict_state")
    for name in required:
        value = answer.get(name)
        if value is None or not str(value).strip():
            return False
    return bool(answer.get("included_evidence"))


def response_template(packet: ExercisePacket,
                      curator_label: str) -> Dict[str, Any]:
    """A blank response form for one curator.

    Every answer field is present and empty. Present, so the curator sees what
    is being asked; empty, so nothing here can be mistaken for an answer, and
    ``is_complete`` is false until a person fills it in.
    """
    answers = {}
    for case in packet.cases:
        answers[case.case_id] = {
            "included_evidence": [],
            "excluded_evidence": [],
            "exclusion_reasons": {},
            "normalized_phenotypes": [],
            "effect_dimension": None,
            "conclusion_state": None,
            "applicability": None,
            "conflict_state": None,
            "insufficiency_reasons": [],
            "rationale_notes": None,
        }
    return {
        "exercise_version": EXERCISE_VERSION,
        "exercise_id": packet.exercise_id,
        "curator_label": curator_label,
        "curator_name": None,
        "curator_role": "SCIENTIFIC_CURATOR",
        "completed": False,
        "completed_at": None,
        "answers": answers,
        "instructions": [
            "Answer from the cited evidence alone.",
            "Do not consult the other curator's response.",
            "The legacy project's previous conclusion is deliberately "
            "withheld; it is revealed only after this response is recorded.",
            "INSUFFICIENT is a valid answer and is not a weaker form of "
            "SUPPORTED.",
            "If evidence conflicts, say so; do not prefer a source by its "
            "organisation, its recency or its score.",
        ],
        "note": ("A blank template is not a response. This file counts as a "
                 "curator response only when a named person has completed "
                 "every case."),
    }


@dataclass(frozen=True)
class ComparisonReport:
    """Field-level agreement between two completed responses.

    There is no verdict here, no consensus answer and no score. The report
    names what the two curators said and where they differ, and a human reads
    it. ``agreement_count`` is a count of fields, not a measure of correctness,
    and the note beside it says so.
    """

    exercise_id: str
    curator_a_label: str
    curator_b_label: str
    curator_a_name: str
    curator_b_name: str
    case_results: Tuple[Mapping[str, Any], ...]
    comparison_version: str = COMPARISON_VERSION

    def summary(self) -> Dict[str, Any]:
        agreed = disagreed = 0
        by_field: Dict[str, Dict[str, int]] = {}
        for case in self.case_results:
            for name, outcome in sorted(case["fields"].items()):
                bucket = by_field.setdefault(name, {"agree": 0, "differ": 0})
                if outcome["agree"]:
                    agreed += 1
                    bucket["agree"] += 1
                else:
                    disagreed += 1
                    bucket["differ"] += 1
        return {
            "case_count": len(self.case_results),
            "fields_compared": agreed + disagreed,
            "fields_in_agreement": agreed,
            "fields_differing": disagreed,
            "by_field": {name: dict(counts)
                         for name, counts in sorted(by_field.items())},
        }

    def to_json(self) -> Dict[str, Any]:
        return {
            "comparison_version": self.comparison_version,
            "exercise_id": self.exercise_id,
            "curators": [
                {"label": self.curator_a_label, "name": self.curator_a_name},
                {"label": self.curator_b_label, "name": self.curator_b_name},
            ],
            "cases": [dict(item) for item in self.case_results],
            "summary": self.summary(),
            "note": (
                "This report states where two curators agreed and where they "
                "differed. It does not say who is correct, does not merge the "
                "responses and does not produce a consensus. Agreement is not "
                "evidence of correctness: two curators may agree and both be "
                "wrong. Resolving a disagreement is an adjudication by a "
                "named third person, who keeps both responses intact."),
        }


def compare_responses(packet: ExercisePacket,
                      response_a: CuratorResponse,
                      response_b: CuratorResponse) -> ComparisonReport:
    """Compare two completed responses to one packet.

    Refuses anything that would make the comparison meaningless: a blank
    template, a mismatched packet, or two responses by the same person. The
    last is not pedantry - one person answering twice produces agreement that
    measures nothing at all.
    """
    for label, response in (("A", response_a), ("B", response_b)):
        if response.exercise_id != packet.exercise_id:
            raise CurationError(
                "response %s answers exercise %r, not %r"
                % (label, response.exercise_id, packet.exercise_id))
        if not response.is_complete:
            raise CurationError(
                "response %s is not a completed response: a comparison needs "
                "two named curators who answered every case. A blank template "
                "would report perfect agreement about nothing." % label)

    name_a = (response_a.curator_name or "").strip()
    name_b = (response_b.curator_name or "").strip()
    if name_a.lower() == name_b.lower():
        raise RoleSeparationError(
            "both responses are by %r. Two answers from one person are not "
            "two independent responses." % name_a)

    results = []
    for case in packet.cases:
        answer_a = response_a.answers.get(case.case_id) or {}
        answer_b = response_b.answers.get(case.case_id) or {}
        fields = {}
        for name, kind in COMPARED_FIELDS:
            fields[name] = _compare_field(kind, answer_a.get(name),
                                          answer_b.get(name))
        results.append({
            "case_id": case.case_id,
            "selector": case.selector,
            "fields": fields,
            "fields_differing": sorted(
                name for name, outcome in fields.items()
                if not outcome["agree"]),
        })

    return ComparisonReport(
        exercise_id=packet.exercise_id,
        curator_a_label=response_a.curator_label,
        curator_b_label=response_b.curator_label,
        curator_a_name=name_a, curator_b_name=name_b,
        case_results=tuple(results))


def _compare_field(kind: str, value_a: Any, value_b: Any) -> Dict[str, Any]:
    """Compare one field, reporting both values and whether they match.

    Both values are always reported, including when they agree. A report that
    printed only differences would let a reader assume the rest was verified,
    when what actually happened is that two people said the same thing.
    """
    if kind == "set":
        set_a = frozenset(value_a or ())
        set_b = frozenset(value_b or ())
        return {
            "agree": set_a == set_b,
            "a": sorted(set_a),
            "b": sorted(set_b),
            "only_a": sorted(set_a - set_b),
            "only_b": sorted(set_b - set_a),
        }
    if kind == "mapping":
        map_a = dict(value_a or {})
        map_b = dict(value_b or {})
        differing = sorted(key for key in set(map_a) | set(map_b)
                           if map_a.get(key) != map_b.get(key))
        return {
            "agree": not differing,
            "a": dict(sorted(map_a.items())),
            "b": dict(sorted(map_b.items())),
            "differing_keys": differing,
        }
    return {
        "agree": value_a == value_b,
        "a": value_a,
        "b": value_b,
    }


@dataclass(frozen=True)
class AdjudicationTemplate:
    """The form a named third person fills in to settle a disagreement.

    ``preserved_responses`` is the point. An adjudication that replaced the two
    original answers would erase the disagreement it was called to settle, and
    nobody could later check whether the adjudicator was right either.
    """

    exercise_id: str
    disputed_case_ids: Tuple[str, ...]
    preserved_responses: Tuple[Mapping[str, Any], ...]
    adjudicator_name: Optional[str] = None
    adjudicator_role: str = "ADJUDICATOR"
    decision: Optional[str] = None
    rationale: Optional[str] = None
    decided_at: Optional[str] = None

    def __post_init__(self) -> None:
        if len(self.preserved_responses) != 2:
            raise CurationError(
                "an adjudication preserves both original responses; %d given"
                % len(self.preserved_responses))
        object.__setattr__(self, "disputed_case_ids",
                           tuple(self.disputed_case_ids))
        object.__setattr__(self, "preserved_responses",
                           tuple(self.preserved_responses))
        if self.decision is not None and not (self.adjudicator_name or "").strip():
            raise RoleSeparationError(
                "an adjudication decision requires the name of the "
                "adjudicator who made it")

    @property
    def is_decided(self) -> bool:
        return bool(self.decision and (self.adjudicator_name or "").strip())

    def to_json(self) -> Dict[str, Any]:
        return {
            "exercise_id": self.exercise_id,
            "disputed_case_ids": list(self.disputed_case_ids),
            "preserved_responses": [dict(item)
                                    for item in self.preserved_responses],
            "adjudicator_name": self.adjudicator_name,
            "adjudicator_role": self.adjudicator_role,
            "decision": self.decision,
            "rationale": self.rationale,
            "decided_at": self.decided_at,
            "is_decided": self.is_decided,
            "note": ("Both original responses are preserved above and are not "
                     "replaced by the decision. An adjudication settles which "
                     "reading the project adopts; it does not erase the "
                     "disagreement or make the other reading disappear."),
        }


def _read_ndjson(path: str) -> List[Mapping[str, Any]]:
    if not os.path.isfile(path):
        raise CurationError("no such file: %s" % path)
    with io.open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _case_from_record(case_id: str, selector: str, reason: str,
                      record: Mapping[str, Any],
                      legacy_proposal_ids: Sequence[str] = ()) -> ExerciseCase:
    natural = record.get("natural_key") or {}
    links = record.get("entity_links") or ()
    return ExerciseCase(
        case_id=case_id,
        selector=selector,
        selector_reason=reason,
        case_role=CaseRole.INTER_CURATOR_EXERCISE,
        evidence_record_uuids=(record["record_uuid"],),
        natural_keys=(natural.get("natural_key"),),
        gene_canonical_keys=tuple(sorted({
            link["canonical_key"] for link in links
            if link.get("entity_type") == "GENE"})),
        drug_canonical_keys=tuple(sorted({
            link["canonical_key"] for link in links
            if link.get("entity_type") == "DRUG"})),
        record_types=(natural.get("record_type"),),
        source_version_statuses=((record.get("version") or {}).get("status"),),
        origin_statuses=((record.get("attribution") or {}).get("origin_status"),),
        publication_identities=tuple(sorted(
            item["identity"] for item in record.get("publications") or ()
            if item.get("identity"))),
        locator_count=len(record.get("locators") or ()),
        linked_legacy_proposal_ids=tuple(sorted(legacy_proposal_ids)))


def build_exercise_packet(
    evidence_build_path: str,
    proposals_path: Optional[str] = None,
    exercise_id: str = "wp09-inter-curator-1",
) -> ExercisePacket:
    """Select a small, representative, deterministic set of cases.

    Selection is by *situation*, not by sampling. Each selector names a place
    the protocol makes a demand - an unknown version, a pending type mapping, a
    record with no stated origin - and the first record satisfying it in
    natural-key order is taken. Sorting by natural key makes the choice
    reproducible; taking the first makes it independent of how many records
    happen to match.

    A record already used is not reused, so eight selectors yield up to eight
    distinct cases and a selector that finds nothing left is simply absent
    rather than forcing a duplicate.
    """
    records = _read_ndjson(os.path.join(evidence_build_path,
                                        "evidence-records.ndjson"))
    with io.open(os.path.join(evidence_build_path, "manifest.json"),
                 encoding="utf-8") as handle:
        manifest = json.load(handle)

    by_key = sorted(records,
                    key=lambda row: (row.get("natural_key") or {}).get(
                        "natural_key") or "")

    # Which evidence records a legacy hint points at, so the last selector can
    # find one. The hint itself is never carried into the case.
    legacy_by_uuid: Dict[str, List[str]] = {}
    if proposals_path and os.path.isfile(proposals_path):
        for row in _read_ndjson(proposals_path):
            for uuid_value in row.get("linked_record_uuids") or ():
                legacy_by_uuid.setdefault(uuid_value, []).append(
                    str(row.get("proposal_id")))

    def version_status(row):
        return (row.get("version") or {}).get("status")

    def origin_status(row):
        return (row.get("attribution") or {}).get("origin_status")

    def mapping_status(row):
        return (row.get("record_type_mapping") or {}).get("status")

    def record_type(row):
        return (row.get("natural_key") or {}).get("record_type")

    def entity_keys(row, kind):
        return {link["canonical_key"] for link in row.get("entity_links") or ()
                if link.get("entity_type") == kind}

    def identified_publications(row):
        return [item for item in row.get("publications") or ()
                if item.get("identity")]

    predicates = {
        "GUIDELINE_WITH_STATED_ORIGIN":
            lambda row: (record_type(row) == "GUIDELINE_ANNOTATION"
                         and origin_status(row) == "STATED_BY_SOURCE"),
        "VARIANT_ANNOTATION_WITH_PUBLICATION":
            lambda row: (record_type(row) == "VARIANT_ANNOTATION"
                         and bool(identified_publications(row))),
        "MULTIPLE_PUBLICATIONS":
            lambda row: len({item["identity"]
                             for item in identified_publications(row)}) > 1,
        "MULTI_GENE_OR_MULTI_DRUG":
            lambda row: (len(entity_keys(row, "GENE")) > 1
                         or len(entity_keys(row, "DRUG")) > 1),
        "UNKNOWN_SOURCE_VERSION":
            lambda row: (record_type(row) == "VARIANT_ANNOTATION"
                         and version_status(row) == "UNKNOWN_LEGACY"),
        "NO_STATED_ORIGIN":
            lambda row: (record_type(row) == "VARIANT_ANNOTATION"
                         and origin_status(row) == "NOT_STATED_BY_SOURCE"),
        "PENDING_RECORD_TYPE_MAPPING":
            lambda row: mapping_status(row) == "PENDING_REVIEW",
        "MULTIPLE_LOCATORS":
            lambda row: len(row.get("locators") or ()) > 2,
        "LINKED_LEGACY_HINT":
            lambda row: bool(legacy_by_uuid.get(row.get("record_uuid"))),
    }

    used: set = set()
    cases: List[ExerciseCase] = []
    unmatched: List[Dict[str, str]] = []
    for index, (selector, reason) in enumerate(CASE_SELECTORS, start=1):
        predicate = predicates[selector]
        for row in by_key:
            if row["record_uuid"] in used or not predicate(row):
                continue
            used.add(row["record_uuid"])
            cases.append(_case_from_record(
                "CASE-%02d-%s" % (index, selector), selector, reason, row,
                legacy_by_uuid.get(row["record_uuid"], ())))
            break
        else:
            # Recorded rather than skipped silently. A situation this corpus
            # does not contain is a fact about the corpus, and a packet that
            # quietly omitted it would look more representative than it is.
            unmatched.append({
                "selector": selector,
                "reason": reason,
                "note": "no record in this evidence build matches this "
                        "situation, so the exercise cannot cover it"})

    if not cases:
        raise CurationError(
            "no case matched any selector in %s" % evidence_build_path)

    return ExercisePacket(
        exercise_id=exercise_id,
        cases=tuple(cases),
        evidence_build_key=str(manifest.get("evidence_build_key")),
        evidence_build_content_hash=str(manifest.get("content_hash")),
        unmatched_selectors=tuple(unmatched))
