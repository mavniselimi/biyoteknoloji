# -*- coding: utf-8 -*-
"""The WP-21 gate (WP-21): what is implemented, and what is still true.

Two questions that must not be collapsed into one:

- **Is the metric machinery implemented?** Yes, after this work package. That
  is a software fact, measured by importing the modules and counting the
  registry.
- **Has a release been validated?** No. There is no active release, no holdout
  case, no reference judgment and no expert review, so there is nothing to
  validate against and nothing was validated.

Every previous work package that reported one boolean for "is it done" had to
be unpicked later. So this document reports both answers separately and lets
them disagree, which they currently do: implementation ``IMPLEMENTED``, gate
``BLOCKED``.

Nothing here is asserted. Counts come from the sealed case catalogue and the
separation audit; the release state comes from the resolver port being absent;
the marker checks walk the tree.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Mapping, Optional, Tuple

from pgx.domain.claims import DEFAULT_CLAIM_BOUNDARY
from pgx.validation.catalog import development_cases
from pgx.validation.metric_definitions import (FAILURE_PATH_CATALOGUE,
                                               FAILURE_PATH_CATALOGUE_VERSION,
                                               METRIC_DEFINITIONS,
                                               METRIC_REGISTRY_VERSION,
                                               registry_digest,
                                               validation_evidence_metric_ids)
from pgx.validation.separation import audit_partition
from pgx.validation.vocabulary import ValidationCaseRole

__all__ = [
    "BENCHMARK_BLOCKER_CODES",
    "GATE_STATUS_VERSION",
    "RESTRICTED_STORAGE_ENV",
    "benchmark_gate_state",
    "build_wp21_gate_status",
]

GATE_STATUS_VERSION = "pgx-wp21-gate-status/1"

#: Same environment variable WP-18 reads. Named here rather than imported so
#: this module does not depend on WP-18's gate builder, which depends on this
#: one after the integration below.
RESTRICTED_STORAGE_ENV = "PGX_VALIDATION_RESTRICTED_ROOT"

BENCHMARK_BLOCKER_CODES: Mapping[str, Mapping[str, str]] = {
    "BENCHMARK_NO_ACTIVE_RELEASE": {
        "meaning": "no release is registered or active, so no benchmark can "
                   "pin one and no result can name what it measured",
        "owner": "WP-03 operation"},
    "BENCHMARK_NO_HOLDOUT_CASES": {
        "meaning": "zero internal-holdout and zero expert-holdout cases "
                   "exist; the seven development cases shaped the software "
                   "and are not validation evidence",
        "owner": "scientific curators; a holdout case cannot be generated"},
    "BENCHMARK_NO_REFERENCE_JUDGMENT": {
        "meaning": "no immutable reference judgment has been supplied, so "
                   "concordance, coverage correctness and holdout pass rate "
                   "have no answer to compare against",
        "owner": "scientific curators under the WP-22 protocol"},
    "BENCHMARK_RESTRICTED_STORAGE_NOT_CONFIGURED": {
        "meaning": "holdout payloads live in restricted storage and none is "
                   "configured, so no holdout case could be executed",
        "owner": "deployment"},
    "BENCHMARK_NO_COMPLETED_EXPERT_REVIEWS": {
        "meaning": "the blind review protocol and the review module are "
                   "implemented and no expert has completed a review under "
                   "them, so expert agreement and Likert metrics have no "
                   "decisions to summarise",
        "owner": "named experts under the approved protocol"},
    "BENCHMARK_NOT_EXECUTED": {
        "meaning": "no benchmark run exists for any release; nobody looked",
        "owner": "whoever runs a benchmark once a release exists"},
    "BENCHMARK_CLAIM_BOUNDARY_NOT_APPROVED": {
        "meaning": "the claim boundary awaits human and scientific review, "
                   "so no validation result may be presented as a claim",
        "owner": "named human and scientific reviewers"},
    "BENCHMARK_NO_VALIDATION_EVIDENCE_CASES": {
        "meaning": "no case in the repository may enter a validation "
                   "denominator",
        "owner": "scientific curators"},
}


def _restricted_storage_configured(environ: Optional[Mapping[str, str]]
                                   ) -> bool:
    values = os.environ if environ is None else environ
    root = values.get(RESTRICTED_STORAGE_ENV)
    return bool(root) and os.path.isdir(str(root))


def _active_release_available(resolver: Optional[Any]) -> bool:
    """Whether one release could be pinned right now.

    ``None`` means no resolver was injected, which is this repository's state:
    there is no release registry to read and nothing to activate. Returning
    ``False`` rather than raising, because "no release" is a condition the
    gate reports, not an error it hits.
    """
    if resolver is None:
        return False
    try:
        return resolver.resolve() is not None
    except Exception:  # pragma: no cover - a resolver that cannot resolve
        return False


def benchmark_gate_state(*, active_release: bool, holdout_cases: int,
                         reference_judgments: int,
                         restricted_storage: bool,
                         benchmark_executed: bool,
                         numeric_evidence_metrics: int) -> str:
    """``PASS`` only when a real benchmark produced real evidence values."""
    if not (active_release and holdout_cases > 0 and reference_judgments > 0
            and restricted_storage and benchmark_executed):
        return "BLOCKED"
    if numeric_evidence_metrics <= 0:
        return "BLOCKED"
    return "PASS"


def _expert_review_module_present(root: str) -> bool:
    """Whether WP-22's review module exists, measured from the tree.

    Read from disk rather than imported, for the same reason WP-20 reads
    WP-21's marker from disk: an ImportError in an unrelated module must not
    turn a truthful "not implemented" into a crash in a gate builder.
    """
    return all(os.path.exists(os.path.join(root, *path.split("/")))
               for path in ("pgx/expert_review/service.py",
                            "pgx/expert_review/protocol.py",
                            "docs/validation/expert-protocol.md"))


def _wp21_markers(root: str) -> Tuple[str, ...]:
    """The files that actually constitute WP-21, checked on disk.

    WP-18 originally guessed ``pgx/benchmark`` and ``pgx/metrics``. Neither
    was ever built - the metric code lives inside ``pgx/validation`` because
    it depends on the partition it must not violate - so the marker list is
    corrected here and WP-18 reads this function rather than its own guess.
    """
    candidates = ("pgx/validation/benchmark.py",
                  "pgx/validation/metrics.py",
                  "docs/architecture/wp21-validation-metrics.md")
    return tuple(path for path in candidates
                 if os.path.exists(os.path.join(root, path)))


def build_wp21_gate_status(root: str = None,
                           environ: Optional[Mapping[str, str]] = None,
                           release_resolver: Optional[Any] = None,
                           judgment_port: Optional[Any] = None,
                           decision_port: Optional[Any] = None
                           ) -> Dict[str, Any]:
    """The committed WP-21 gate status, measured from this repository."""
    if root is None:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                            "..", ".."))
    cases = development_cases(root)
    audit = audit_partition(cases)
    holdout_total = audit.internal_holdout_count + audit.expert_holdout_count
    restricted = _restricted_storage_configured(environ)
    active_release = _active_release_available(release_resolver)
    boundary = DEFAULT_CLAIM_BOUNDARY

    judgments = 0
    if judgment_port is not None:
        for role in (ValidationCaseRole.INTERNAL_HOLDOUT,
                     ValidationCaseRole.EXPERT_HOLDOUT):
            judgments += len(judgment_port.judgments(role=role))

    benchmark_executed = False
    numeric_evidence = 0

    # ``None`` rather than ``0`` when no decision source was supplied: nobody
    # inspected a store, so nothing was counted. An inspected store holding
    # zero rows would report 0, and the two must stay distinguishable.
    completed_reviews: Optional[int] = None
    if decision_port is not None:
        completed_reviews = 0
        for role in (ValidationCaseRole.INTERNAL_HOLDOUT,
                     ValidationCaseRole.EXPERT_HOLDOUT):
            completed_reviews += len(decision_port.decisions(role=role))

    blockers: List[Dict[str, Any]] = []

    def _block(code: str, detail: str) -> None:
        blockers.append({"code": code, "blocking": True, "detail": detail,
                         "owner": BENCHMARK_BLOCKER_CODES[code]["owner"]})

    if not active_release:
        _block("BENCHMARK_NO_ACTIVE_RELEASE",
               "no release resolver is wired and no release is active")
    if holdout_total == 0:
        _block("BENCHMARK_NO_HOLDOUT_CASES",
               "internal holdout: %d, expert holdout: %d"
               % (audit.internal_holdout_count, audit.expert_holdout_count))
        _block("BENCHMARK_NO_VALIDATION_EVIDENCE_CASES",
               "%d development case(s) exist and none of them may enter a "
               "validation denominator" % audit.development_count)
    if judgments == 0:
        _block("BENCHMARK_NO_REFERENCE_JUDGMENT",
               "WP-18 stores no expected answer by design and no separate "
               "reference-judgment input has been supplied")
    if not restricted:
        _block("BENCHMARK_RESTRICTED_STORAGE_NOT_CONFIGURED",
               "%s is unset or does not name a directory"
               % RESTRICTED_STORAGE_ENV)
    _block("BENCHMARK_NO_COMPLETED_EXPERT_REVIEWS",
           "the WP-22 review module is implemented; %s"
           % ("no review store was inspected, so no completed review count "
              "was taken" if completed_reviews is None
              else "%d completed review(s) were supplied" % completed_reviews))
    if not benchmark_executed:
        _block("BENCHMARK_NOT_EXECUTED",
               "no benchmark run exists for any release")
    if not boundary.is_approved:
        _block("BENCHMARK_CLAIM_BOUNDARY_NOT_APPROVED",
               "claim boundary status is %s" % boundary.status)
    blockers.sort(key=lambda item: (item["code"], item["detail"]))

    state = benchmark_gate_state(
        active_release=active_release, holdout_cases=holdout_total,
        reference_judgments=judgments, restricted_storage=restricted,
        benchmark_executed=benchmark_executed,
        numeric_evidence_metrics=numeric_evidence)

    return {
        "gate_status_schema_version": GATE_STATUS_VERSION,
        "work_package": "WP-21",
        "implementation_status": "IMPLEMENTED",
        "implementation_note": (
            "The metric registry, the benchmark contract, the engine, the "
            "public report and the dashboard feed are implemented. That is a "
            "statement about software. Whether any release has been "
            "validated is the separate question below, and the answer is no."),
        "benchmark_gate_status": state,
        "release_may_proceed": state == "PASS",
        "benchmark_executed_against_active_release": benchmark_executed,
        "active_release_available": active_release,
        "metric_framework_implemented": True,
        "metric_definition_count": len(METRIC_DEFINITIONS),
        "validation_evidence_metric_count":
            len(validation_evidence_metric_ids()),
        "computed_metric_value_count": 0,
        "computed_metric_value_note": (
            "zero rather than null: the metric layer ran and produced no "
            "value because no benchmark was executed. Every metric is "
            "NOT_EXECUTED or BLOCKED, never a numeric zero."),
        "numeric_validation_metric_count": numeric_evidence,
        "metric_registry_version": METRIC_REGISTRY_VERSION,
        "metric_registry_digest": registry_digest(),
        "failure_path_catalogue_version": FAILURE_PATH_CATALOGUE_VERSION,
        "failure_path_count": len(FAILURE_PATH_CATALOGUE),
        "threshold_count": 0,
        "threshold_note": (
            "No metric carries a threshold. One would require a predeclared, "
            "reviewable policy with provenance, and none exists."),
        "development_case_count": audit.development_count,
        "internal_holdout_case_count": audit.internal_holdout_count,
        "expert_holdout_case_count": audit.expert_holdout_count,
        "validation_evidence_case_count": holdout_total,
        "reference_judgment_count": judgments,
        "expert_review_module_implemented": _expert_review_module_present(root),
        "completed_expert_review_count": completed_reviews,
        "completed_expert_review_count_source": (
            "null rather than zero: no review store was inspected, so no "
            "count was taken" if completed_reviews is None
            else "counted from the supplied decision source"),
        "reference_judgment_note": (
            "WP-18 stores no expected answer. A reference judgment is a "
            "separate immutable input with its own provenance; none has been "
            "supplied, so concordance-style metrics are "
            "NO_REFERENCE_JUDGMENT rather than zero."),
        "restricted_storage_configured": restricted,
        "separation_audit_clean": audit.is_clean,
        "separation_audit_checked_case_count": audit.checked_case_count,
        "separation_audit_issue_codes": list(audit.issue_codes),
        "release_validation_result_available": False,
        "clinical_validation_performed": False,
        "expert_review_performed": False,
        "claim_boundary_status": boundary.status,
        "claim_boundary_approved": boundary.is_approved,
        "development_is_not_validation": (
            "The %d development cases are a regression signal. They shaped "
            "the software and are structurally excluded from every validation "
            "denominator; results derived from them appear only under "
            "DEVELOPMENT_REGRESSION." % audit.development_count),
        "not_clinical_validation": (
            "This document describes metric machinery and its current empty "
            "state. It is not clinical validation, scientific validation or "
            "expert review, and no number in it establishes that the system "
            "is safe for any patient."),
        "wp21_markers_found": list(_wp21_markers(root)),
        # Measured from WP-22's own marker list rather than from a bare
        # directory, so this document and WP-22's cannot disagree about
        # whether the module is there. An empty ``__init__.py`` used to be
        # enough to report started.
        "wp22_started": _expert_review_module_present(root),
        "blocker_count": len(blockers),
        "blockers": blockers,
    }
