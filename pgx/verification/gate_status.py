# -*- coding: utf-8 -*-
"""What WP-19 may say, field by field, with nothing collapsed.

The temptation in a gate status is one boolean. It is always wrong here,
because the things being reported have genuinely different states: the suite
can be entirely green while PostgreSQL was never reached, coverage was never
measured, and the claim boundary is unapproved. A single ``verified: true``
would be false; a single ``verified: false`` would suggest the software is
broken. Neither is what happened.

So every component is its own field, and the fields that mean "nobody looked"
are ``null`` rather than ``0`` - the distinction WP-18 drew and this document
keeps. ``release_may_proceed`` exists, but it is the *conjunction* of the
fields above it, computed rather than asserted, and it is false whenever
anything is blocked.

Three claims this document explicitly does not make:

* **No scientific validation.** Software tests passing is not a validated
  ruleset, a reviewed case, or an expert opinion. WP-21 and WP-22 own those.
* **No safety gate.** The safety-invariant map says which tests relate to which
  invariant. WP-20 owns the registry and the blocking job.
* **No claim-boundary approval.** That is a signature from named humans, and no
  code path here can produce one.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.verification.coverage_report import CoverageSummary
from pgx.verification.flaky import FlakyReport
from pgx.verification.matrix import Matrix
from pgx.verification.model import Category, Criticality, Outcome, ProfileResult
from pgx.verification.reproducibility import ReproducibilityReport
from pgx.verification.run_evidence import (
    NO_EVIDENCE,
    VERIFIED,
    load_run_evidence,
    run_evidence_freshness,
)

__all__ = [
    "GATE_STATUS_SCHEMA_VERSION",
    "GATE_STATUS_PATH",
    "BLOCKER_CODES",
    "build_wp19_gate_status",
]

GATE_STATUS_SCHEMA_VERSION = "pgx-wp19-gate-status/1"
GATE_STATUS_PATH = "data/verification/wp19-real-gate-status.json"

#: Stable, controlled codes. A later CI keys on these; the wording of a detail
#: may change, the code may not.
BLOCKER_CODES: Tuple[str, ...] = (
    "VERIFICATION_NO_RECORDED_RUN",
    "VERIFICATION_RUN_STALE",
    "VERIFICATION_RUN_FAILED",
    "VERIFICATION_COVERAGE_NOT_MEASURED",
    "VERIFICATION_POSTGRESQL_NOT_EXERCISED",
    "VERIFICATION_CATEGORY_NOT_EXERCISED",
    "VERIFICATION_REQUIREMENT_NOT_COVERED",
    "VERIFICATION_CRITICAL_TESTS_UNMAPPED",
    "VERIFICATION_FLAKY_TESTS_DETECTED",
    "VERIFICATION_ARTIFACTS_NOT_REPRODUCIBLE",
    "VERIFICATION_UNEXPLAINED_SKIPS",
    "VERIFICATION_CLAIM_BOUNDARY_NOT_APPROVED",
    "VERIFICATION_SAFETY_GATE_NOT_PASSING",
)

#: Owners, so a blocker names who can close it. "code" appears nowhere: every
#: blocker below is closed by a person, a machine or a later work package.
_OWNERS: Mapping[str, str] = {
    "VERIFICATION_NO_RECORDED_RUN": "whoever runs the suite",
    "VERIFICATION_RUN_STALE": "whoever runs the suite",
    "VERIFICATION_RUN_FAILED": "whoever fixes the failing tests",
    "VERIFICATION_COVERAGE_NOT_MEASURED": "deployment (install coverage.py)",
    "VERIFICATION_POSTGRESQL_NOT_EXERCISED":
        "deployment (start the disposable test database)",
    "VERIFICATION_CATEGORY_NOT_EXERCISED": "whoever runs the suite",
    "VERIFICATION_REQUIREMENT_NOT_COVERED": "WP-19 maintainer",
    "VERIFICATION_CRITICAL_TESTS_UNMAPPED": "WP-19 maintainer",
    "VERIFICATION_FLAKY_TESTS_DETECTED": "whoever owns the flaky test",
    "VERIFICATION_ARTIFACTS_NOT_REPRODUCIBLE":
        "whoever owns the generator that disagreed",
    "VERIFICATION_UNEXPLAINED_SKIPS": "whoever owns the skipping test",
    "VERIFICATION_CLAIM_BOUNDARY_NOT_APPROVED":
        "named human and scientific reviewers",
    "VERIFICATION_SAFETY_GATE_NOT_PASSING": "WP-20 safety gate",
}

#: Repeated verbatim into the artifact.
_NOT_SCIENTIFIC_VALIDATION = (
    "Everything in this document is software verification. A green suite means "
    "the software behaved as its tests describe. It is not a validated "
    "ruleset, a reviewed validation case, an expert opinion, a clinical "
    "result, or an approval. Those are produced by people under WP-21 and "
    "WP-22 and cannot be produced by running tests. WP-22's review module is "
    "implemented and its test suite is green; that means the software records "
    "a review correctly, and says nothing about whether an expert conducted "
    "one.")

_SAFETY_GATE_NOTE = (
    "WP-19 maps existing tests to the safety invariants so that thin coverage "
    "is visible. WP-20 owns the registry, the negative controls and the "
    "blocking gate, and this document reports WP-20's *measured* state rather "
    "than asserting or inferring one. Where WP-20 has not been run here, the "
    "state is reported as absent - never as satisfied.")


def _benchmark_gate_state(root: str) -> Dict[str, Any]:
    """Read WP-21's committed benchmark gate status. Never infer one.

    Same contract as :func:`_safety_gate_state`, and for the same reason: the
    package that measures a thing and the package that reports it must be
    able to disagree, or a disagreement is undetectable. A missing WP-21
    status is ``ABSENT``; it is never optimistically read as ``PASS``, and
    WP-19 does not run the benchmark on WP-21's behalf.

    WP-19 does *not* block on this. A verification suite is not a validation
    result, and making a green test run wait on a scientific gate would
    conflate them - which is the confusion both packages exist to prevent.
    It is reported so a reader of one document sees both states.
    """
    import io as _io
    import json as _json

    absent = {"benchmark_gate_status": "ABSENT",
              "validation_metrics_implemented": False,
              "validation_metric_definition_count": None,
              "numeric_validation_metric_count": None,
              "validation_evidence_case_count": None}
    path = os.path.join(root, "data", "validation",
                        "wp21-real-gate-status.json")
    if not os.path.exists(path):
        return absent
    try:
        with _io.open(path, "r", encoding="utf-8") as handle:
            document = _json.load(handle)
    except (ValueError, OSError):
        return absent
    return {
        "benchmark_gate_status": document.get("benchmark_gate_status",
                                              "ABSENT"),
        "validation_metrics_implemented": bool(
            document.get("metric_framework_implemented")),
        "validation_metric_definition_count":
            document.get("metric_definition_count"),
        "numeric_validation_metric_count":
            document.get("numeric_validation_metric_count"),
        "validation_evidence_case_count":
            document.get("validation_evidence_case_count"),
    }


def _safety_gate_state(root: str) -> Dict[str, Any]:
    """Read WP-20's committed gate status. Never infer one.

    Until WP-20 existed this was a standing blocker saying the gate was
    somebody else's. Now there is a gate, so the honest thing is to read what
    it measured - and to keep reporting a blocker whenever it is not PASS,
    which is a different and much more useful statement than "not implemented".

    A missing or unreadable WP-20 status is ``ABSENT``, not ``PASS``. WP-19
    does not run the safety gate on WP-20's behalf: doing so would put the
    measurement and the reporting in one place, and the first time they
    disagreed there would be nothing to compare.
    """
    import io as _io
    import json as _json

    path = os.path.join(root, "data", "safety", "wp20-real-gate-status.json")
    if not os.path.exists(path):
        return {"safety_gate_status": "ABSENT",
                "safety_gate_reason": "no WP-20 safety gate status is "
                                      "committed; run `pgx-safety check "
                                      "--write`",
                "safety_invariant_count": None,
                "safety_negative_controls_detected": None,
                "safety_negative_control_count": None}
    try:
        with _io.open(path, "r", encoding="utf-8") as handle:
            document = _json.load(handle)
    except (ValueError, OSError):
        return {"safety_gate_status": "ABSENT",
                "safety_gate_reason": "the WP-20 gate status could not be read",
                "safety_invariant_count": None,
                "safety_negative_controls_detected": None,
                "safety_negative_control_count": None}
    return {
        "safety_gate_status": document.get("safety_gate_status", "ABSENT"),
        "safety_gate_reason": "" if document.get("release_may_proceed")
                              else "the WP-20 safety gate reports %s with %d "
                                   "blocker(s)"
                                   % (document.get("safety_gate_status"),
                                      document.get("blocker_count", 0)),
        "safety_invariant_count": document.get("registered_invariant_count"),
        "safety_negative_controls_detected":
            document.get("detected_negative_control_count"),
        "safety_negative_control_count":
            document.get("negative_control_count"),
    }


def _later_packages_started(root: str) -> Dict[str, Any]:
    """Whether WP-20 or later has begun. Measured from the tree, not asserted.

    The same mechanism WP-16 used for ``wp17_started`` and WP-18 for
    ``wp19_started``, for the same reason: a pinned ``false`` has to be deleted
    on the day the next package starts, and until somebody notices it is a lie.
    """
    markers = {
        "wp20": ("pgx/safety", "docs/architecture/wp20-safety-invariants.md"),
        # Corrected at WP-22, the same correction WP-18's and WP-20's lists
        # needed: WP-19 guessed ``pgx/benchmark`` and ``pgx/metrics``, and
        # neither was built - the metric engine lives inside
        # ``pgx/validation`` because it depends on the partition it must not
        # violate. Left as it was, this reported a finished work package as
        # unstarted forever, which is exactly the lie the docstring above
        # warns about, arriving by a different route.
        "wp21": ("pgx/validation/benchmark.py", "pgx/validation/metrics.py",
                 "docs/architecture/wp21-validation-metrics.md"),
        "wp22": ("pgx/expert_review/service.py",
                 "pgx/expert_review/protocol.py",
                 "docs/validation/expert-protocol.md",
                 "docs/architecture/wp22-expert-review.md"),
        "wp24": (".github/workflows", "docs/architecture/wp24-ci.md"),
    }
    found: Dict[str, Any] = {}
    for name, paths in markers.items():
        present = [path for path in paths
                   if os.path.exists(os.path.join(root, *path.split("/")))]
        found["%s_markers_found" % name] = sorted(present)
        found["%s_started" % name] = bool(present)
    return found


def _claim_boundary(root: str) -> Tuple[bool, str]:
    """Read the claim boundary's status line rather than asserting it."""
    path = os.path.join(root, "docs", "architecture", "intended-purpose.md")
    if not os.path.exists(path):
        return (False, "docs/architecture/intended-purpose.md is missing")
    import io
    with io.open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("| Status |"):
                status = line.split("|")[2].strip().strip("*")
                return (status.upper().startswith("APPROVED"), status)
    return (False, "no status line found in the intended-purpose document")


def build_wp19_gate_status(root: str,
                           matrix: Matrix,
                           discovered: int,
                           results: Mapping[str, ProfileResult],
                           coverage: CoverageSummary,
                           flaky: Optional[FlakyReport],
                           reproducibility: Optional[ReproducibilityReport],
                           ) -> Dict[str, Any]:
    """The WP-19 gate status. Every component reported separately."""
    blockers: List[Dict[str, Any]] = []

    def block(code: str, detail: str) -> None:
        blockers.append({"blocking": True, "code": code, "detail": detail,
                         "owner": _OWNERS.get(code, "unassigned")})

    # -- the recorded run -------------------------------------------------
    evidence = load_run_evidence(root)
    run_status, run_reason = run_evidence_freshness(evidence, root)
    if run_status == NO_EVIDENCE:
        block("VERIFICATION_NO_RECORDED_RUN", run_reason)
    elif run_status == "STALE_EVIDENCE_REJECTED":
        block("VERIFICATION_RUN_STALE", run_reason)
    elif run_status == "RUN_FAILED":
        block("VERIFICATION_RUN_FAILED", run_reason)

    # -- execution counts, never derived from one another -----------------
    full = results.get("full")
    if full is None:
        counts: Dict[str, Any] = {
            "discovered": discovered, "executed": None, "passed": None,
            "failed": None, "errored": None, "skipped": None,
            "unexplained_skips": None, "not_executed": None}
        execution_status = "BLOCKED"
    else:
        counts = dict(full.summary.as_document())
        counts["discovered"] = discovered
        execution_status = full.outcome.value
        if full.summary.unexplained_skips:
            block("VERIFICATION_UNEXPLAINED_SKIPS",
                  "%d skip(s) did not match the reason their inventory entry "
                  "permits" % full.summary.unexplained_skips)

    # -- categories --------------------------------------------------------
    category_status: Dict[str, Any] = {}
    for category in Category:
        observed: Optional[Mapping[str, Any]] = None
        for result in results.values():
            candidate = result.categories.get(category.value)
            if candidate and candidate.get("executed"):
                if observed is None or candidate["executed"] > observed["executed"]:
                    observed = candidate
        if observed is None:
            static = next((item for item in matrix.categories
                           if item.category is category), None)
            category_status[category.value] = {
                "outcome": (Outcome.MISSING.value if static is None
                            or not static.test_ids else Outcome.BLOCKED.value),
                "executed": 0,
                "inventoried": 0 if static is None else len(static.test_ids),
                "reason": "no executed result for this category in any profile "
                          "run here",
            }
            block("VERIFICATION_CATEGORY_NOT_EXERCISED",
                  "category %s has no executed result" % category.value)
            continue
        static = next((item for item in matrix.categories
                       if item.category is category), None)
        entry = dict(observed)
        entry["inventoried"] = 0 if static is None else len(static.test_ids)
        category_status[category.value] = entry
        if entry["outcome"] == Outcome.BLOCKED.value:
            code = ("VERIFICATION_POSTGRESQL_NOT_EXERCISED"
                    if category is Category.POSTGRESQL_INTEGRATION
                    else "VERIFICATION_CATEGORY_NOT_EXERCISED")
            block(code, "category %s executed only skips: %s"
                  % (category.value, str(entry.get("reason", ""))[:160]))

    # -- requirements ------------------------------------------------------
    requirement_status: Dict[str, Any] = {}
    for coverage_item in matrix.requirements:
        requirement = coverage_item.requirement
        requirement_status[requirement.requirement_id] = {
            "criticality": requirement.criticality.value,
            "is_covered": coverage_item.is_covered,
            "test_count": len(coverage_item.test_ids),
            "title": requirement.title,
        }
    for identifier in matrix.uncovered_requirements:
        block("VERIFICATION_REQUIREMENT_NOT_COVERED",
              "%s has no test matching its selectors" % identifier)
    if matrix.unmapped_critical_modules:
        block("VERIFICATION_CRITICAL_TESTS_UNMAPPED",
              "%d critical test module(s) serve no requirement: %s"
              % (len(matrix.unmapped_critical_modules),
                 ", ".join(matrix.unmapped_critical_modules[:5])))

    # -- coverage ----------------------------------------------------------
    if coverage.status != "MEASURED":
        block("VERIFICATION_COVERAGE_NOT_MEASURED", coverage.reason)

    # -- flakiness and reproducibility -------------------------------------
    if flaky is not None and flaky.status == "FLAKY":
        block("VERIFICATION_FLAKY_TESTS_DETECTED",
              "%d test(s) did not agree with themselves across %d repetitions"
              % (len(flaky.flaky), flaky.repetitions))
    if reproducibility is not None and reproducibility.status not in (
            "REPRODUCIBLE",):
        block("VERIFICATION_ARTIFACTS_NOT_REPRODUCIBLE",
              "artifact reproducibility reported %s" % reproducibility.status)

    # -- governance --------------------------------------------------------
    approved, claim_status = _claim_boundary(root)
    if not approved:
        block("VERIFICATION_CLAIM_BOUNDARY_NOT_APPROVED",
              "claim boundary status is %s" % claim_status)
    safety = _safety_gate_state(root)
    benchmark = _benchmark_gate_state(root)
    if safety["safety_gate_status"] != Outcome.PASS.value:
        block("VERIFICATION_SAFETY_GATE_NOT_PASSING",
              safety["safety_gate_reason"] or
              "the WP-20 safety gate is not passing")

    later = _later_packages_started(root)

    document: Dict[str, Any] = {
        "asgi_runtime_status":
            category_status[Category.ASGI_RUNTIME.value]["outcome"],
        "blocker_count": len(blockers),
        "blockers": sorted(blockers, key=lambda item: item["code"]),
        "browser_e2e_status":
            category_status[Category.BROWSER_E2E.value]["outcome"],
        "category_status": category_status,
        "claim_boundary_approved": approved,
        "claim_boundary_status": claim_status,
        "counts": counts,
        "coverage": coverage.as_document(),
        "coverage_tool_available": coverage.status == "MEASURED",
        "critical_requirement_count": sum(
            1 for item in matrix.requirements
            if item.requirement.criticality is Criticality.P0_CRITICAL),
        "discovered_test_count": discovered,
        "execution_status": execution_status,
        "flaky": (None if flaky is None else flaky.as_document()),
        "flaky_repeat_status": (None if flaky is None else flaky.status),
        "gate_status_schema_version": GATE_STATUS_SCHEMA_VERSION,
        "implementation_status": "IMPLEMENTED",
        "matrix_is_complete": matrix.is_complete,
        "not_scientific_validation": _NOT_SCIENTIFIC_VALIDATION,
        "postgresql_test_status":
            category_status[Category.POSTGRESQL_INTEGRATION.value]["outcome"],
        "profiles_executed": sorted(results),
        "profile_results": {name: result.as_document(include_outcomes=False)
                            for name, result in sorted(results.items())},
        "reproducibility": (None if reproducibility is None
                            else reproducibility.as_document()),
        "reproducibility_status": (None if reproducibility is None
                                   else reproducibility.status),
        "requirement_status": requirement_status,
        "run_evidence_path": "data/verification/wp19-verification-run.json",
        "run_evidence_reason": run_reason,
        "run_evidence_status": run_status,
        "safety_gate_note": _SAFETY_GATE_NOTE,
        # Changed by WP-20, together with its schema and its tests. WP-19's
        # map is still a map - but a gate now exists, so this document reports
        # its measured state instead of declaring the question out of scope.
        "safety_invariant_map_only": False,
        "scientific_validation_performed": False,
        "unmapped_critical_modules": list(matrix.unmapped_critical_modules),
        "uncovered_requirements": list(matrix.uncovered_requirements),
        "work_package": "WP-19",
    }
    document.update(later)
    document.update(safety)
    # Reported, not blocked on. See _benchmark_gate_state.
    document.update(benchmark)

    # Computed last, from the fields above, and never asserted. A single
    # boolean is safe only when it is the conjunction of things a reader can
    # check for themselves.
    document["release_may_proceed"] = bool(
        run_status == VERIFIED
        and execution_status == Outcome.PASS.value
        and not blockers)
    return document
