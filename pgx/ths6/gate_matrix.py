# -*- coding: utf-8 -*-
"""Gates A to F, rebuilt from the artifacts that own them (WP-25).

A gate here is a **conjunction with named sources**. Every condition says
which file it read and which field in it, so a reviewer can open the file and
disagree. Nothing is inferred from a work package's implementation status, and
nothing is inherited from a sibling gate: WP-24's own Gate E document already
makes that point about security and deployment, and this module extends it to
all six.

Three rules are enforced structurally rather than by convention:

**A gate passes only when every mandatory condition is met.** ``BLOCKED`` and
``NOT_EVALUATED`` never count towards a pass. There is no threshold, no
weighting and no "mostly".

**Gate F cannot pass while any of A to E is not PASS.** This is checked twice
on purpose: once as a condition of F, and again in ``build_gate_matrix`` after
F has been evaluated. Defence in depth, because the single most valuable thing
an attacker on this document could do is make F pass alone.

**There is no override.** No ``--force``, no ``--assume``, no ``--fixture``,
no ``--ignore-blocker``. A gate's result is a function of its conditions and
nothing else, and ``GateRecord`` refuses at construction to hold ``PASS``
beside an unmet condition, so the absence of an override is a property of the
type rather than a promise about the command line.

The last responsibility is **disagreement**. Where two authoritative artifacts
state different things about the same fact, WP-25 records the disagreement and
does not resolve it. Choosing the more favourable of two values is how an
evidence pack becomes advocacy.
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.ths6.evidence_registry import (field_at, field_is_missing,
                                        read_document)
from pgx.ths6.models import (Finding, GateCondition, GateRecord,
                             repository_relative)
from pgx.ths6.vocabulary import BLOCKER_CODES, Blocker, GateResult

__all__ = [
    "DISAGREEMENTS",
    "GATES",
    "GATE_MATRIX_VERSION",
    "build_gate_matrix",
    "detect_disagreements",
    "evaluate_gate",
]

GATE_MATRIX_VERSION = "pgx-wp25-gate-matrix/1"


# -- comparators -------------------------------------------------------------
#
# Each returns (met, observed_text). They are functions rather than operator
# strings so that "at least" cannot be applied to None: a null count means no
# measurement was taken, and treating it as zero would turn "nobody looked"
# into "we looked and found none".

def equals(expected: object) -> Callable[[object], Tuple[bool, str]]:
    def compare(value: object) -> Tuple[bool, str]:
        return value == expected, repr(value)
    compare.expectation = "== %r" % (expected,)  # type: ignore[attr-defined]
    return compare


def at_least(threshold: int) -> Callable[[object], Tuple[bool, str]]:
    def compare(value: object) -> Tuple[bool, str]:
        if value is None:
            return False, "null (no measurement was taken)"
        if not isinstance(value, int) or isinstance(value, bool):
            return False, repr(value)
        return value >= threshold, repr(value)
    compare.expectation = ">= %d" % threshold  # type: ignore[attr-defined]
    return compare


def is_true() -> Callable[[object], Tuple[bool, str]]:
    def compare(value: object) -> Tuple[bool, str]:
        return value is True, repr(value)
    compare.expectation = "is true"  # type: ignore[attr-defined]
    return compare


@dataclass(frozen=True)
class ConditionSpec:
    """One mandatory condition, declared before anything is read."""

    condition_id: str
    description: str
    source_path: str
    source_field: str
    comparator: Callable[[object], Tuple[bool, str]]
    blocker_code: str
    owner: str

    def __post_init__(self) -> None:
        repository_relative(self.source_path)
        if self.blocker_code not in BLOCKER_CODES:
            raise ValueError(
                "%s names undeclared blocker %r"
                % (self.condition_id, self.blocker_code))


@dataclass(frozen=True)
class GateSpec:
    """One gate: a title, a conjunction, and what it depends on."""

    gate_id: str
    title: str
    conditions: Tuple[ConditionSpec, ...]
    depends_on: Tuple[str, ...] = ()


def _c(condition_id, description, path, field, comparator, code, owner):
    return ConditionSpec(condition_id=condition_id, description=description,
                         source_path=path, source_field=field,
                         comparator=comparator, blocker_code=code,
                         owner=owner)


_WP11 = "data/rulesets/wp11-real-gate-status.json"
_WP13 = "data/coverage/wp13-real-gate-status.json"
_WP14 = "data/assessments/wp14-real-gate-status.json"
_WP15 = "data/reports/wp15-real-gate-status.json"
_WP16 = "data/api/wp16-real-gate-status.json"
_WP17 = "data/web/wp17-real-gate-status.json"
_WP18 = "data/validation/wp18-real-gate-status.json"
_WP19 = "data/verification/wp19-real-gate-status.json"
_WP20 = "data/safety/wp20-real-gate-status.json"
_WP21 = "data/validation/wp21-real-gate-status.json"
_WP22 = "data/expert-review/wp22-real-gate-status.json"
_WP23 = "data/security/wp23-real-gate-status.json"
_WP24 = "data/deployment/wp24-real-gate-status.json"
_WP24E = "data/deployment/wp24-gate-e-status.json"
_WP24RV = "data/deployment/wp24-release-validation.json"
_CANON = "data/canonical/PGX-DATA-20260830-900/manifest.json"

#: The six gates, named as architecture.md section 20 names them, with each
#: gate's PASS condition from that table expanded into the individual fields
#: that would have to hold. The expansion is where the work is: "immutable
#: dataset, complete source policy, canonical DQ report, traceable evidence"
#: is a sentence, and a sentence cannot be evaluated.
GATES: Tuple[GateSpec, ...] = (
    GateSpec(
        "GATE-A", "Gate A - Scientific Data",
        (
            _c("A1", "at least one scientific source is approved", _WP11,
               "upstream_state.source_registry_approved", at_least(1),
               "THS6_NO_APPROVED_SOURCE", "scientific source approver"),
            _c("A2", "a canonical dataset is published", _WP11,
               "upstream_state.canonical_dataset_published", is_true(),
               "THS6_DATASET_NOT_PUBLISHED", "data owner"),
            _c("A3", "the raw snapshot behind the dataset is complete",
               _CANON, "snapshot_complete", is_true(),
               "THS6_SNAPSHOT_QUARANTINED", "data owner"),
            # SEALED, not "VERIFIED": SEALED is the only affirmative value
            # SnapshotState defines. It also cannot be reached from
            # QUARANTINED - the lifecycle has no transition out - so this
            # condition is satisfied by re-ingesting under a new dataset ID
            # and by nothing else. Naming an invented target state here
            # would have made the gate unsatisfiable in a way no reader
            # could have traced.
            _c("A4", "the raw snapshot is SEALED, which for a QUARANTINED "
               "snapshot requires re-ingestion under a new dataset id "
               "because the lifecycle has no transition out of quarantine",
               _CANON, "snapshot_state", equals("SEALED"),
               "THS6_SNAPSHOT_QUARANTINED", "data owner"),
            _c("A5", "the evidence build is approved for rule construction",
               _WP11, "upstream_state.evidence_build_approved_for_rules",
               is_true(), "THS6_EVIDENCE_BUILD_NOT_APPROVED",
               "curation lead"),
        )),
    GateSpec(
        "GATE-B", "Gate B - Rules",
        (
            _c("B1", "the curation protocol is approved", _WP11,
               "upstream_state.curation_protocol_approved", is_true(),
               "THS6_CURATION_PROTOCOL_NOT_APPROVED", "expert reviewer"),
            _c("B2", "at least one interpretation has been curated", _WP11,
               "curation_state.curated_interpretations", at_least(1),
               "THS6_NO_CURATED_INTERPRETATION", "curation lead"),
            _c("B3", "at least one rule approval envelope is eligible",
               _WP11, "curation_state.eligible_rule_approval_envelopes",
               at_least(1), "THS6_NO_APPROVED_RULE", "curation lead"),
            _c("B4", "at least one rule is validated", _WP11,
               "rule_state.real_validated_rules", at_least(1),
               "THS6_NO_APPROVED_RULE", "curation lead"),
            _c("B5", "at least one ruleset is frozen", _WP11,
               "rule_state.real_frozen_rulesets", at_least(1),
               "THS6_NO_EXECUTABLE_RULESET", "curation lead"),
            _c("B6", "the default registry holds an executable ruleset",
               _WP11, "rule_state.executable_rulesets_in_default_registry",
               at_least(1), "THS6_NO_EXECUTABLE_RULESET", "curation lead"),
            _c("B7", "no legacy rule candidate is left unlinked", _WP11,
               "curation_state.unlinked_work_items", equals(0),
               "THS6_LEGACY_WORK_ITEMS_UNLINKED", "curation lead"),
        )),
    GateSpec(
        "GATE-C", "Gate C - Core Safety",
        (
            _c("C1", "at least one assessment has been computed from "
               "governed content", _WP14,
               "assessment_state.real_completed_assessments", at_least(1),
               "THS6_NO_REAL_ASSESSMENT", "curation lead"),
            _c("C2", "at least one coverage manifest has been executed",
               _WP13, "coverage_state.real_coverage_executions", at_least(1),
               "THS6_NO_COVERAGE_EXECUTION", "curation lead"),
            _c("C3", "at least one axis is supported by governed coverage",
               _WP13, "coverage_state.real_supported_axes", at_least(1),
               "THS6_NO_COVERAGE_EXECUTION", "curation lead"),
            _c("C4", "at least one report has been produced", _WP15,
               "real_report_count", at_least(1), "THS6_NO_REAL_ASSESSMENT",
               "curation lead"),
            _c("C5", "the safety gate reports PASS in its own artifact",
               _WP20, "safety_gate_status", equals("PASS"),
               "THS6_SAFETY_GATE_BLOCKED", "safety owner"),
            _c("C6", "the safety invariants have been executed by a CI "
               "provider", _WP20, "ci_job_executed", is_true(),
               "THS6_SAFETY_CI_NOT_EXECUTED", "platform owner"),
            _c("C7", "the claim boundary is approved", _WP20,
               "claim_boundary_approved", is_true(),
               "THS6_CLAIM_BOUNDARY_NOT_APPROVED",
               "clinical safety authority"),
            _c("C8", "a release is active", _WP20,
               "active_release_available", is_true(),
               "THS6_NO_ACTIVE_RELEASE", "release approver"),
            _c("C9", "the API has served at least one real assessment",
               _WP16, "real_api_assessment_count", at_least(1),
               "THS6_NO_REAL_ASSESSMENT", "platform owner"),
        )),
    GateSpec(
        "GATE-D", "Gate D - Validation",
        (
            _c("D1", "at least fifty validation cases exist", _WP18,
               "real_patient_case_count", at_least(50),
               "THS6_INSUFFICIENT_VALIDATION_CASES", "validation owner"),
            _c("D2", "an independent holdout set exists", _WP18,
               "holdout_case_count", at_least(1), "THS6_NO_HOLDOUT_SET",
               "validation owner"),
            _c("D3", "at least one validation metric has a computed value",
               _WP21, "computed_metric_value_count", at_least(1),
               "THS6_NO_COMPUTED_METRIC", "validation owner"),
            _c("D4", "at least one reference judgment exists", _WP21,
               "reference_judgment_count", at_least(1),
               "THS6_NO_COMPUTED_METRIC", "validation owner"),
            _c("D5", "a benchmark has been executed against the active "
               "release", _WP21, "benchmark_executed_against_active_release",
               is_true(), "THS6_BENCHMARK_NOT_EXECUTED", "validation owner"),
            _c("D6", "the expert review protocol has a signatory", _WP22,
               "protocol_signatory_count", at_least(1),
               "THS6_EXPERT_PROTOCOL_NOT_APPROVED", "expert review chair"),
            _c("D7", "at least one expert reviewer is named", _WP22,
               "named_reviewer_count", at_least(1),
               "THS6_NO_NAMED_REVIEWER", "expert review chair"),
            _c("D8", "at least one expert review is completed", _WP22,
               "completed_review_count", at_least(1),
               "THS6_NO_COMPLETED_REVIEW", "expert review chair"),
            _c("D9", "the expert review gate reports PASS in its own "
               "artifact", _WP22, "expert_review_gate_status", equals("PASS"),
               "THS6_NO_COMPLETED_REVIEW", "expert review chair"),
        )),
    GateSpec(
        "GATE-E", "Gate E - Operational",
        (
            _c("E1", "the security gate reports PASS in its own artifact",
               _WP23, "security_gate_status", equals("PASS"),
               "THS6_SECURITY_GATE_BLOCKED", "security owner"),
            _c("E2", "a governed database is reachable", _WP23,
               "database_available", is_true(), "THS6_DATABASE_UNAVAILABLE",
               "platform owner"),
            _c("E3", "the governed schema migration has been applied", _WP23,
               "migration_0011_executed", is_true(),
               "THS6_MIGRATION_NOT_EXECUTED", "platform owner"),
            _c("E4", "the audit chain has been verified against a real "
               "store", _WP23, "audit_chain_verified", is_true(),
               "THS6_AUDIT_CHAIN_UNVERIFIED", "platform owner"),
            _c("E5", "a restore has been executed and verified", _WP23,
               "restore_verified", is_true(),
               "THS6_BACKUP_RESTORE_NOT_VERIFIED", "platform owner"),
            _c("E6", "the deployment gate reports PASS in its own artifact",
               _WP24, "deployment_gate_status", equals("PASS"),
               "THS6_DEPLOYMENT_GATE_BLOCKED", "platform owner"),
            _c("E7", "a container runtime is available", _WP24,
               "container_runtime_available", is_true(),
               "THS6_CONTAINER_RUNTIME_UNAVAILABLE", "platform owner"),
            _c("E8", "a CI provider has executed the configured workflows",
               _WP24, "ci_executed", is_true(), "THS6_CI_NOT_EXECUTED",
               "platform owner"),
            _c("E9", "a staging environment has been deployed", _WP24E,
               "staging_deployed", is_true(), "THS6_STAGING_NOT_DEPLOYED",
               "platform owner"),
            _c("E10", "the combined Gate E artifact reports PASS", _WP24E,
               "gate_e_status", equals("PASS"),
               "THS6_DEPLOYMENT_GATE_BLOCKED", "platform owner"),
        )),
    GateSpec(
        "GATE-F", "Gate F - THS 6",
        (
            _c("F1", "the release validation aggregate permits a release",
               _WP24RV, "release_may_proceed", is_true(),
               "THS6_UPSTREAM_GATE_NOT_PASS", "release approver"),
            _c("F2", "every required release gate is satisfied", _WP24RV,
               "satisfied_required_count", at_least(19),
               "THS6_UPSTREAM_GATE_NOT_PASS", "release approver"),
            _c("F3", "the safety gate permits a release", _WP20,
               "release_may_proceed", is_true(),
               "THS6_UPSTREAM_GATE_NOT_PASS", "safety owner"),
            _c("F4", "the interface reports a populated validation "
               "dashboard", _WP17, "validation_dashboard_status",
               equals("POPULATED"), "THS6_DEMO_NOT_EXECUTED",
               "platform owner"),
            _c("F5", "the verification suite's recorded run is not stale",
               _WP19, "run_evidence_status", equals("FRESH"),
               "THS6_EVIDENCE_STALE", "verification owner"),
        ),
        depends_on=("GATE-A", "GATE-B", "GATE-C", "GATE-D", "GATE-E")),
)


def evaluate_gate(root: str, spec: GateSpec) -> GateRecord:
    """Evaluate one gate against the working tree.

    ``FAIL`` rather than ``NOT_EVALUATED`` when a source artifact is missing
    or a declared field is absent. Both mean the pack cannot answer the
    question it was built to answer, and that is an engineering defect worth
    an exit code of its own - a silently unevaluable condition is how a gate
    stops asking anything.
    """
    conditions: List[GateCondition] = []
    blockers: List[Blocker] = []
    findings: List[Finding] = []
    defective = False
    for item in spec.conditions:
        document = read_document(root, item.source_path)
        expectation = getattr(item.comparator, "expectation", "satisfied")
        if document is None:
            defective = True
            conditions.append(GateCondition(
                condition_id=item.condition_id, description=item.description,
                source_path=item.source_path, source_field=item.source_field,
                expected=expectation, observed="artifact unreadable",
                met=None))
            findings.append(Finding(
                code="THS6_EVIDENCE_UNAVAILABLE",
                detail="%s reads %s, which could not be read"
                       % (item.condition_id, item.source_path),
                owner="repository maintainer",
                resolution="the condition is recorded unevaluated and the "
                           "gate is reported FAIL rather than assumed",
                blocking=True, references=(item.source_path,)))
            continue
        value = field_at(document, item.source_field)
        if field_is_missing(value):
            defective = True
            conditions.append(GateCondition(
                condition_id=item.condition_id, description=item.description,
                source_path=item.source_path, source_field=item.source_field,
                expected=expectation, observed="field absent", met=None))
            findings.append(Finding(
                code="THS6_EVIDENCE_INVALID",
                detail="%s reads %s from %s, and the field is not there"
                       % (item.condition_id, item.source_field,
                          item.source_path),
                owner="repository maintainer",
                resolution="the condition is recorded unevaluated and the "
                           "gate is reported FAIL rather than assumed",
                blocking=True,
                references=(item.source_path,)))
            continue
        met, observed = item.comparator(value)
        blocker = None
        if not met:
            blocker = Blocker(code=item.blocker_code,
                              detail="%s: %s (observed %s, required %s)"
                                     % (item.condition_id, item.description,
                                        observed, expectation),
                              owner=item.owner, gate_id=spec.gate_id)
            blockers.append(blocker)
        conditions.append(GateCondition(
            condition_id=item.condition_id, description=item.description,
            source_path=item.source_path, source_field=item.source_field,
            expected=expectation, observed=observed, met=met,
            blocker=blocker))
    if defective:
        result = GateResult.FAIL
    elif blockers:
        result = GateResult.BLOCKED
    else:
        result = GateResult.PASS
    return GateRecord(
        gate_id=spec.gate_id, title=spec.title,
        conditions=tuple(conditions), result=result,
        blockers=tuple(blockers), depends_on=spec.depends_on,
        findings=tuple(findings),
        notes=("every condition names the artifact and field it was read "
               "from; the result is their conjunction and nothing else"))


# -- disagreement detection --------------------------------------------------

@dataclass(frozen=True)
class Disagreement:
    """Two authoritative artifacts stating different things about one fact.

    Recorded, never resolved. Preferring one value over the other is a
    decision with an owner, and WP-25 is not that owner.
    """

    fact: str
    left_path: str
    left_field: str
    right_path: str
    right_field: str
    explanation: str
    owner: str

    def observe(self, root: str) -> Optional[Mapping[str, object]]:
        left = read_document(root, self.left_path)
        right = read_document(root, self.right_path)
        if left is None or right is None:
            return None
        left_value = field_at(left, self.left_field)
        right_value = field_at(right, self.right_field)
        if field_is_missing(left_value) or field_is_missing(right_value):
            return None
        if _agree(left_value, right_value):
            return None
        return {"fact": self.fact, "left_path": self.left_path,
                "left_field": self.left_field, "left_value": left_value,
                "right_path": self.right_path, "right_field":
                self.right_field, "right_value": right_value,
                "explanation": self.explanation, "owner": self.owner,
                "resolution": "recorded; WP-25 does not choose between them"}


def _agree(left: object, right: object) -> bool:
    """Whether two observations of the same fact say the same thing.

    ``None`` and ``0`` deliberately *disagree*: one says no measurement was
    taken and the other says a measurement found none, and this project has
    spent five work packages keeping them apart.
    """
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    return left == right


#: The disagreements this pack knows how to look for. Each is a fact two
#: artifacts both describe; where they differ, the difference is reported.
DISAGREEMENTS: Tuple[Disagreement, ...] = (
    Disagreement(
        fact="whether the expert review workflow is implemented",
        left_path=_WP17, left_field="expert_review_workflow_status",
        right_path=_WP22, right_field="implementation_status",
        explanation="WP-17's interface gate status says the expert review "
                    "workflow is NOT_IMPLEMENTED; WP-22 reports its own "
                    "module IMPLEMENTED with a delivered review workflow. "
                    "One of the two artifacts is out of date.",
        owner="platform owner"),
    Disagreement(
        fact="the number of holdout validation cases",
        left_path=_WP17, left_field="holdout_case_count",
        right_path=_WP18, right_field="holdout_case_count",
        explanation="WP-17 records null, meaning no count was taken; WP-18 "
                    "records 0, meaning a count was taken and found none. "
                    "Both are honest and they are not the same statement.",
        owner="validation owner"),
    Disagreement(
        fact="whether WP-24 has started",
        left_path=_WP20, left_field="wp24_started",
        right_path=_WP19, right_field="wp24_started",
        explanation="WP-20's artifact reports that WP-24 had not started; "
                    "WP-19's reports that it had. WP-20's was generated "
                    "before the deployment package existed.",
        owner="safety owner"),
)


def _defined_test_function_count(root: str) -> Optional[int]:
    """Count test functions defined under ``tests/``, by parsing them.

    Not a discovered-test count and not a run count: it is the number of
    ``test*`` functions the source declares, which is cheap, deterministic and
    needs no test runner. It is used only to detect that a *recorded* count is
    materially out of date, which is a question this measurement can answer
    even though it is not the same measurement.
    """
    directory = os.path.join(root, "tests")
    if not os.path.isdir(directory):
        return None
    total = 0
    for base, directories, files in os.walk(directory):
        directories[:] = [name for name in directories
                          if name != "__pycache__"]
        for name in sorted(files):
            if not (name.startswith("test_") and name.endswith(".py")):
                continue
            path = os.path.join(base, name)
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    tree = ast.parse(handle.read())
            except Exception:  # pragma: no cover - unparseable test file
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name.startswith("test"):
                        total += 1
    return total


def detect_disagreements(root: str = ".") -> Tuple[Mapping[str, object], ...]:
    """Every disagreement observable in this tree, plus the stale test count.

    The test-count check is separate from the declarative table because its
    right-hand side is measured rather than read: WP-19's recorded
    ``discovered_test_count`` is compared against the number of test functions
    the tree currently defines. The two are different measurements, so only a
    material gap is reported - a recorded count *below* the number of defined
    functions cannot be explained by skips or parametrisation and means the
    artifact predates later work.
    """
    observed = [item.observe(root) for item in DISAGREEMENTS]
    results = [item for item in observed if item is not None]
    document = read_document(root, _WP19)
    recorded = field_at(document, "discovered_test_count")
    defined = _defined_test_function_count(root)
    if (not field_is_missing(recorded) and isinstance(recorded, int)
            and defined is not None and recorded < defined):
        results.append({
            "fact": "how many tests this repository has",
            "left_path": _WP19, "left_field": "discovered_test_count",
            "left_value": recorded,
            "right_path": "tests/", "right_field":
            "test functions defined (counted by parsing)",
            "right_value": defined,
            "explanation":
                "WP-19's recorded discovery count is lower than the number "
                "of test functions the tree now defines, so the recorded "
                "count predates later work packages. A recorded count can "
                "legitimately be lower than the defined count only through "
                "skips, which reduce execution rather than discovery.",
            "owner": "verification owner",
            "resolution": "recorded; WP-25 does not regenerate another work "
                          "package's artifact",
        })
    return tuple(results)


def build_gate_matrix(root: str = ".") -> Mapping[str, object]:
    """Every gate, evaluated, with Gate F's dependency enforced twice."""
    records = {spec.gate_id: evaluate_gate(root, spec) for spec in GATES}
    upstream = ("GATE-A", "GATE-B", "GATE-C", "GATE-D", "GATE-E")
    not_passing = [gate_id for gate_id in upstream
                   if not records[gate_id].result.is_pass]
    gate_f = records["GATE-F"]
    if not_passing and gate_f.result.is_pass:
        # Defence in depth. F's own conditions already read artifacts that
        # cannot be satisfied while A-E are blocked, but a future edit to
        # those conditions must not be able to make F pass alone.
        gate_f = GateRecord(
            gate_id=gate_f.gate_id, title=gate_f.title,
            conditions=gate_f.conditions, result=GateResult.BLOCKED,
            blockers=gate_f.blockers + (Blocker(
                code="THS6_UPSTREAM_GATE_NOT_PASS",
                detail="gates %s are not PASS, which forbids Gate F "
                       "regardless of its own conditions"
                       % ", ".join(not_passing),
                owner="programme owner", gate_id="GATE-F"),),
            depends_on=gate_f.depends_on, findings=gate_f.findings,
            notes=gate_f.notes)
        records["GATE-F"] = gate_f
    disagreements = detect_disagreements(root)
    results = {gate_id: record.result.value
               for gate_id, record in sorted(records.items())}
    passing = sorted(gate_id for gate_id, record in records.items()
                     if record.result.is_pass)
    return {
        "gate_matrix_version": GATE_MATRIX_VERSION,
        "gate_count": len(records),
        "results": results,
        "passing_gate_ids": passing,
        "passing_gate_count": len(passing),
        "blocking_gate_ids": sorted(
            gate_id for gate_id, record in records.items()
            if record.result is GateResult.BLOCKED),
        "failing_gate_ids": sorted(
            gate_id for gate_id, record in records.items()
            if record.result is GateResult.FAIL),
        "all_gates_pass": len(passing) == len(records),
        "gates": [records[spec.gate_id].to_json() for spec in GATES],
        "total_blocker_count": sum(len(record.blockers)
                                   for record in records.values()),
        "blocker_owners": sorted({
            blocker.owner for record in records.values()
            for blocker in record.blockers}),
        "source_artifact_disagreements": [dict(item)
                                          for item in disagreements],
        "disagreement_count": len(disagreements),
        "override_available": False,
        "note": (
            "A gate passes only when every mandatory condition is met. "
            "BLOCKED and NOT_EVALUATED never count towards a pass, Gate F "
            "cannot pass while any of A to E is not PASS, and there is no "
            "override."),
    }
