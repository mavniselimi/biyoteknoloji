# -*- coding: utf-8 -*-
"""What the project would like to say, and what would justify it (WP-25).

A claim registry is the inverse of a feature list. A feature list says what
was built; this says what may be *asserted* on the strength of it, which is a
much smaller set and the only one that matters to a reviewer.

Each claim carries three things a reader can check independently:

* **a statement**, written the way it would appear outwardly;
* **a conjunction of evidence** - every listed item must resolve to a present
  artifact of an admissible type. There is no weighting and no partial credit
  that rounds up, because a claim supported by four of five conditions is a
  claim nobody may make;
* **contradiction probes** - a field in a named artifact whose value would
  make the claim false. This is what separates ``UNSUPPORTED`` from
  ``CONTRADICTED``: the first means nothing was found, the second means
  something was found and it says no.

The probes are the part worth arguing about, so they are spelled as data:
artifact path, field, and the value that refutes the claim. A reviewer can
open the file and check. ``release_may_proceed: false`` in WP-24's own
release-validation aggregate refutes "a release has been validated"; it does
not merely fail to support it, and reporting it as UNSUPPORTED would lose the
distinction between an unfinished job and a finished job that said no.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.ths6.evidence_registry import (DECLARED_EVIDENCE, field_at,
                                        field_is_missing, read_document,
                                        resolve_evidence)
from pgx.ths6.models import ClaimRecord, repository_relative
from pgx.ths6.vocabulary import ClaimSupport, EvidenceType

__all__ = [
    "CLAIMS",
    "CLAIM_REGISTRY_VERSION",
    "ContradictionProbe",
    "build_claim_registry",
    "evaluate_claim",
]

CLAIM_REGISTRY_VERSION = "pgx-wp25-claim-registry/1"


@dataclass(frozen=True)
class ContradictionProbe:
    """One field whose value would refute a claim.

    ``refuting_value`` is compared with ``==``. JSON ``null`` is a legitimate
    refuting value for a claim of the form "a number exists", and it is
    distinguished from an absent field by ``field_is_missing``: a probe whose
    field is not in the artifact at all yields no verdict, because a schema
    that changed is not an observation.
    """

    source_path: str
    field: str
    refuting_value: object
    explanation: str

    def __post_init__(self) -> None:
        repository_relative(self.source_path)
        if not self.explanation.strip():
            raise ValueError("a probe explains what its value means")

    def refutes(self, root: str) -> Optional[bool]:
        document = read_document(root, self.source_path)
        if document is None:
            return None
        value = field_at(document, self.field)
        if field_is_missing(value):
            return None
        return value == self.refuting_value

    def to_json(self) -> Mapping[str, object]:
        return {"source_path": self.source_path, "field": self.field,
                "refuting_value": self.refuting_value,
                "explanation": self.explanation}


@dataclass(frozen=True)
class ClaimDeclaration:
    """A claim before it has been evaluated against the working tree."""

    claim_id: str
    statement: str
    origin: str
    required_evidence_ids: Tuple[str, ...]
    gate_id: Optional[str]
    dod_ids: Tuple[str, ...]
    outward_facing: bool
    probes: Tuple[ContradictionProbe, ...] = ()


def _c(claim_id, statement, origin, evidence, gate, dods, outward=False,
       probes=()):
    return ClaimDeclaration(
        claim_id=claim_id, statement=statement, origin=origin,
        required_evidence_ids=tuple(evidence), gate_id=gate,
        dod_ids=tuple(dods), outward_facing=outward, probes=tuple(probes))


_P = ContradictionProbe

#: Twenty-four claims. Seventeen trace to a Definition of Done bullet; the
#: remaining seven are the gate-level statements a reader would take a passing
#: gate to mean, written down so they can be refuted rather than assumed.
CLAIMS: Tuple[ClaimDeclaration, ...] = (
    _c("THS6-CLAIM-001",
       "One integrated web prototype runs the representative workflow from "
       "input to report.",
       "architecture.md §21 bullet 1",
       ("EV-WP16-001", "EV-WP17-001", "EV-WP17-002", "EV-WP16-003"),
       "GATE-C", ("P0-DOD-001",), outward=True,
       probes=(_P("data/api/wp16-real-gate-status.json",
                  "real_api_assessment_count", 0,
                  "the API has never computed an assessment, so no workflow "
                  "has run end to end through it"),)),
    _c("THS6-CLAIM-002",
       "Assessment facts are deterministic for the same release and the same "
       "input.",
       "architecture.md §21 bullet 2",
       ("EV-WP14-001", "EV-WP14-002", "EV-WP15-003"),
       "GATE-C", ("P0-DOD-002",), outward=True,
       probes=(_P("data/safety/wp20-real-gate-status.json",
                  "active_release_available", False,
                  "no release exists, so 'for the same release' has no "
                  "referent"),)),
    _c("THS6-CLAIM-003",
       "Every finding in a report carries traceable evidence back to a "
       "governed source record.",
       "architecture.md §21 bullet 3",
       ("EV-WP08-002", "EV-WP15-001", "EV-WP15-005"),
       "GATE-C", ("P0-DOD-003",), outward=True,
       probes=(_P("data/reports/wp15-real-gate-status.json",
                  "real_report_count", 0,
                  "no report has been produced, so no finding exists to "
                  "trace"),)),
    _c("THS6-CLAIM-004",
       "Missing data is never presented as low or no risk, and coverage is "
       "reported separately from risk.",
       "architecture.md §21 bullet 4",
       ("EV-WP13-002", "EV-WP13-003", "EV-WP20-005"),
       "GATE-C", ("P0-DOD-004",), outward=True),
    _c("THS6-CLAIM-005",
       "Software, dataset and ruleset are versioned independently of one "
       "another.",
       "architecture.md §21 bullet 5",
       ("EV-WP03-003", "EV-WP24-004", "EV-WP06-002", "EV-WP11-001"),
       "GATE-F", ("P0-DOD-005",),
       probes=(_P("data/canonical/PGX-DATA-20260830-900/manifest.json",
                  "dataset_lifecycle_state", "BUILDING",
                  "the canonical dataset is still being built, so no "
                  "published dataset version exists to pin"),)),
    _c("THS6-CLAIM-006",
       "Rollback between released versions works and has been exercised.",
       "architecture.md §21 bullet 5",
       ("EV-WP24-016", "EV-WP24-003"),
       "GATE-E", ("P0-DOD-005",),
       probes=(_P("data/deployment/wp24-release-validation.json",
                  "release_may_proceed", False,
                  "no release may proceed, so there is no released version "
                  "to roll back from or to"),)),
    _c("THS6-CLAIM-007",
       "At least fifty serious validation cases exist.",
       "architecture.md §21 bullet 6",
       ("EV-WP18-001", "EV-WP18-003", "EV-WP21-002"),
       "GATE-D", ("P0-DOD-006",), outward=True,
       probes=(_P("data/validation/wp18-real-gate-status.json",
                  "real_patient_case_count", 0,
                  "zero validation cases exist against a stated P0 target of "
                  "fifty"),)),
    _c("THS6-CLAIM-008",
       "An independent holdout set exists and was not used to develop the "
       "rules.",
       "architecture.md §21 bullet 7",
       ("EV-WP18-002", "EV-WP18-003", "EV-WP18-006"),
       "GATE-D", ("P0-DOD-007",), outward=True,
       probes=(_P("data/validation/wp18-real-gate-status.json",
                  "holdout_case_count", 0,
                  "no holdout case exists, so separation is vacuous rather "
                  "than demonstrated"),)),
    _c("THS6-CLAIM-009",
       "All safety invariants pass in continuous integration.",
       "architecture.md §21 bullet 8",
       ("EV-WP20-001", "EV-WP20-004", "EV-WP20-007"),
       "GATE-C", ("P0-DOD-008",), outward=True,
       probes=(_P("data/safety/wp20-real-gate-status.json",
                  "ci_job_executed", False,
                  "the workflow is configured but no CI provider has run "
                  "it, so no invariant has passed in CI"),)),
    _c("THS6-CLAIM-010",
       "A blind-first expert review has been completed under an approved "
       "protocol.",
       "architecture.md §21 bullet 9",
       ("EV-WP22-001", "EV-WP22-002", "EV-WP22-006"),
       "GATE-D", ("P0-DOD-009",), outward=True,
       probes=(_P("data/expert-review/wp22-real-gate-status.json",
                  "expert_review_performed", False,
                  "the gate status states in its own words that no expert "
                  "review has been performed"),
               _P("data/expert-review/wp22-real-gate-status.json",
                  "protocol_approved", False,
                  "the protocol has no signatory, so there is no approved "
                  "protocol to review under"))),
    _c("THS6-CLAIM-011",
       "Experts used the representative workflow, not only static reports.",
       "architecture.md §21 bullet 10",
       ("EV-WP22-003", "EV-WP17-001", "EV-WP22-001"),
       "GATE-D", ("P0-DOD-010",), outward=True,
       probes=(_P("data/expert-review/wp22-real-gate-status.json",
                  "named_reviewer_count", 0,
                  "no expert has been named, so none has used anything"),)),
    _c("THS6-CLAIM-012",
       "Benchmark metrics are computed per release and are release-specific.",
       "architecture.md §21 bullet 11",
       ("EV-WP21-001", "EV-WP21-002", "EV-WP21-003"),
       "GATE-D", ("P0-DOD-011",), outward=True,
       probes=(_P("data/validation/wp21-real-gate-status.json",
                  "computed_metric_value_count", 0,
                  "definitions exist and values do not; a definition is not "
                  "a metric"),)),
    _c("THS6-CLAIM-013",
       "Every governed action is audited with actor, time, input hash, "
       "version bundle and output hash.",
       "architecture.md §21 bullet 12",
       ("EV-WP23-001", "EV-WP23-003", "EV-WP23-009"),
       "GATE-E", ("P0-DOD-012",), outward=True,
       probes=(_P("data/security/wp23-real-gate-status.json",
                  "audit_store_available", False,
                  "no audit store exists, so no governed action has ever "
                  "been recorded"),)),
    _c("THS6-CLAIM-014",
       "A staging prototype is deployed and answers health checks.",
       "architecture.md §21 bullet 13",
       ("EV-WP24-001", "EV-WP24-010", "EV-WP24-015"),
       "GATE-E", ("P0-DOD-013",),
       probes=(_P("data/deployment/wp24-real-gate-status.json",
                  "container_runtime_available", False,
                  "no container runtime answered, so no image was built and "
                  "nothing was deployed to observe"),)),
    _c("THS6-CLAIM-015",
       "A basic reliability report exists, produced from executed drills.",
       "architecture.md §21 bullet 13",
       ("EV-WP24-006", "EV-WP24-014", "EV-WP24-001"),
       "GATE-E", ("P0-DOD-013",),
       probes=(_P("data/deployment/wp24-real-gate-status.json",
                  "reliability_executed_count", None,
                  "the executed drill count is null - not zero - because no "
                  "drill run was ever attempted"),)),
    _c("THS6-CLAIM-016",
       "Every THS 6 claim links to a concrete artifact or metric.",
       "architecture.md §21 bullet 14",
       ("EV-WP00-001", "EV-WP19-005"),
       "GATE-F", ("P0-DOD-014",)),
    _c("THS6-CLAIM-017",
       "The core demonstration completes with the network unavailable, the "
       "LLM off and every P1 feature off.",
       "architecture.md §21 bullet 15",
       ("EV-WP17-001", "EV-WP17-002", "EV-WP16-001"),
       "GATE-F", ("P0-DOD-015",), outward=True,
       probes=(_P("data/web/wp17-real-gate-status.json",
                  "validation_dashboard_status", "EMPTY_STATE_ONLY",
                  "the interface renders an empty state because there is no "
                  "governed content behind it"),)),
    _c("THS6-CLAIM-018",
       "The scientific source registry contains sources approved by a named "
       "reviewer.",
       "Gate A",
       ("EV-WP05-002", "EV-WP05-005"),
       "GATE-A", (),
       probes=(_P("data/rulesets/wp11-real-gate-status.json",
                  "upstream_state.source_registry_approved", 0,
                  "every registered source is still PENDING_REVIEW"),)),
    _c("THS6-CLAIM-019",
       "A canonical dataset has been published and is immutable.",
       "Gate A",
       ("EV-WP06-002", "EV-WP04-002"),
       "GATE-A", (),
       probes=(_P("data/canonical/PGX-DATA-20260830-900/manifest.json",
                  "snapshot_complete", False,
                  "the snapshot behind the dataset is incomplete and "
                  "quarantined"),)),
    _c("THS6-CLAIM-020",
       "An executable ruleset built from curated content is registered and "
       "usable.",
       "Gate B",
       ("EV-WP11-001", "EV-WP11-002"),
       "GATE-B", (),
       probes=(_P("data/rulesets/wp11-real-gate-status.json",
                  "rule_state.executable_rulesets_in_default_registry", 0,
                  "the default registry contains no executable ruleset"),)),
    _c("THS6-CLAIM-021",
       "Coverage is computed over governed content and reported separately "
       "from risk.",
       "Gate C",
       ("EV-WP13-001", "EV-WP13-002"),
       "GATE-C", (),
       probes=(_P("data/coverage/wp13-real-gate-status.json",
                  "coverage_state.real_coverage_executions", 0,
                  "no coverage execution has been performed over governed "
                  "content"),)),
    _c("THS6-CLAIM-022",
       "The claim boundary has been approved by a named clinical safety "
       "authority.",
       "Gate C",
       ("EV-WP20-001", "EV-WP15-002", "EV-WP00-003"),
       "GATE-C", (), outward=True,
       probes=(_P("data/safety/wp20-real-gate-status.json",
                  "claim_boundary_approved", False,
                  "the boundary is a draft awaiting human and scientific "
                  "review"),)),
    _c("THS6-CLAIM-023",
       "The security control set has been exercised against real governed "
       "stores.",
       "Gate E",
       ("EV-WP23-001", "EV-WP23-002", "EV-WP23-005"),
       "GATE-E", (),
       probes=(_P("data/security/wp23-real-gate-status.json",
                  "database_available", False,
                  "no database is reachable, so no control has been "
                  "exercised against a real store"),)),
    _c("THS6-CLAIM-024",
       "A release has been validated and may proceed.",
       "Gate F",
       ("EV-WP24-003", "EV-WP24-012"),
       "GATE-F", (), outward=True,
       probes=(_P("data/deployment/wp24-release-validation.json",
                  "release_may_proceed", False,
                  "the release validation aggregate states that no release "
                  "may proceed"),)),
)


def _admissible_ids(root: str) -> Mapping[str, bool]:
    """Which declared evidence ids resolve to something a claim may cite."""
    return {item.evidence_id:
            (resolved.present
             and resolved.evidence_type.may_support_a_ths6_claim)
            for item, resolved in
            ((item, resolve_evidence(root, item))
             for item in DECLARED_EVIDENCE)}


def evaluate_claim(root: str, declaration: ClaimDeclaration,
                   admissible: Optional[Mapping[str, bool]] = None
                   ) -> ClaimRecord:
    """Decide one claim's support, refusing to round anything up."""
    known = dict(admissible if admissible is not None
                 else _admissible_ids(root))
    missing = tuple(sorted(
        evidence_id for evidence_id in declaration.required_evidence_ids
        if not known.get(evidence_id, False)))
    refuted: List[str] = []
    for probe in declaration.probes:
        verdict = probe.refutes(root)
        if verdict is True:
            refuted.append("%s.%s: %s"
                           % (probe.source_path, probe.field,
                              probe.explanation))
    if refuted:
        support = ClaimSupport.CONTRADICTED
        notes = ("refuted by this repository's own artifacts: "
                 + "; ".join(refuted))
    elif not missing:
        support = ClaimSupport.SUPPORTED
        notes = ("every required item resolves to a real executed or "
                 "observed artifact")
    elif len(missing) == len(declaration.required_evidence_ids):
        support = ClaimSupport.UNSUPPORTED
        notes = ("no required item resolves to a real executed or observed "
                 "artifact")
    else:
        support = ClaimSupport.PARTIALLY_SUPPORTED
        notes = ("%d of %d required items resolve to a real executed or "
                 "observed artifact; a partially supported claim is one "
                 "nobody may make"
                 % (len(declaration.required_evidence_ids) - len(missing),
                    len(declaration.required_evidence_ids)))
    return ClaimRecord(
        claim_id=declaration.claim_id, statement=declaration.statement,
        origin=declaration.origin,
        required_evidence_ids=declaration.required_evidence_ids,
        gate_id=declaration.gate_id, dod_ids=declaration.dod_ids,
        outward_facing=declaration.outward_facing, support=support,
        missing_evidence_ids=missing, notes=notes)


def build_claim_registry(root: str = ".") -> Mapping[str, object]:
    """Evaluate every claim and summarise, without a headline verdict.

    There is deliberately no ``all_supported`` boolean. The document reports
    the counts and lists the identifiers; a caller that wants a verdict must
    ask a gate, which is the only place a conjunction is allowed to be drawn.
    """
    admissible = _admissible_ids(root)
    records = [evaluate_claim(root, item, admissible) for item in CLAIMS]
    by_support: Dict[str, int] = {}
    for record in records:
        by_support[record.support.value] = (
            by_support.get(record.support.value, 0) + 1)
    return {
        "claim_registry_version": CLAIM_REGISTRY_VERSION,
        "claim_count": len(records),
        "counts_by_support": dict(sorted(by_support.items())),
        "supported_claim_ids": sorted(
            item.claim_id for item in records if item.support.is_sufficient),
        "contradicted_claim_ids": sorted(
            item.claim_id for item in records
            if item.support is ClaimSupport.CONTRADICTED),
        "outward_facing_claim_ids": sorted(
            item.claim_id for item in CLAIMS if item.outward_facing),
        "claims": [item.to_json() for item in records],
        "probes": {item.claim_id: [probe.to_json() for probe in item.probes]
                   for item in CLAIMS},
        "probe_count": sum(len(item.probes) for item in CLAIMS),
        "unresolvable_probes": [dict(entry) for entry in
                                unresolvable_probes(root)],
        "note": (
            "A claim is SUPPORTED only when every required item resolves to "
            "a real executed or observed artifact. CONTRADICTED means an "
            "artifact in this repository states the opposite."),
    }


def unresolvable_probes(root: str = ".") -> Tuple[Mapping[str, str], ...]:
    """Probes whose artifact or field could not be found.

    This exists because of a defect found while writing this module: a probe
    naming ``state`` on an artifact whose field is ``dataset_lifecycle_state``
    silently returned "no verdict", and the claim it guarded reported as
    merely UNSUPPORTED instead of CONTRADICTED. A probe that can never fire is
    worse than no probe, because it looks like diligence.

    Reported rather than raised: an artifact may legitimately be absent in a
    partial checkout, and the pack should say so rather than refuse to build.
    A test asserts this is empty for the committed tree.
    """
    broken = []
    for declaration in CLAIMS:
        for probe in declaration.probes:
            document = read_document(root, probe.source_path)
            if document is None:
                broken.append({"claim_id": declaration.claim_id,
                               "source_path": probe.source_path,
                               "field": probe.field,
                               "reason": "ARTIFACT_UNREADABLE"})
                continue
            if field_is_missing(field_at(document, probe.field)):
                broken.append({"claim_id": declaration.claim_id,
                               "source_path": probe.source_path,
                               "field": probe.field,
                               "reason": "FIELD_ABSENT"})
    return tuple(broken)
