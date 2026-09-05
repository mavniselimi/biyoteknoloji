# -*- coding: utf-8 -*-
"""What this repository can honestly say about validation (WP-18).

Measured, not asserted. Every count is read off the repository, every absence
is classified, and the two questions "how many are there" and "how many should
there be" are answered in different fields.

**The important number is zero and it stays zero.** There are no holdout
cases. The P0 Definition of Done asks for at least 50 serious validation
cases, preferably 100 or more, and authoring even one is scientific work: it
needs a source, a derivation somebody can follow, and - for an expert holdout
- a named expert working it blind. None of that can be generated. A gate
status that reported the target where the count belongs, or that quietly
counted the seven development fixtures, would be the exact fabrication this
architecture was built to prevent.

**Null is not zero.** Where nothing could be measured - restricted storage
that was never configured, a holdout population nobody has looked at because
there is nowhere to look - the value is ``null`` and a companion field says
why. ``0`` means "counted, and there were none". They are different facts and
a reader acting on them would act differently.
"""

from __future__ import annotations

import datetime as _dt
import io
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from pgx.domain.claims import DEFAULT_CLAIM_BOUNDARY
from pgx.domain.hashing import sha256_digest
from pgx.validation.catalog import DEVELOPMENT_CATALOG_PATH, development_cases
from pgx.validation.manifests import P0_TARGET_CASE_COUNT
from pgx.validation.separation import audit_partition
from pgx.validation.vocabulary import (PayloadAvailability, VOCABULARY_VERSION,
                                       ValidationCaseRole)

__all__ = [
    "BLOCKER_CODES",
    "GATE_STATUS_VERSION",
    "RESTRICTED_STORAGE_ENV",
    "build_wp18_gate_status",
]

GATE_STATUS_VERSION = "pgx-wp18-gate-status/1"

#: Where a deployment would point at restricted holdout storage. Unset in this
#: repository, and reading it is how ``payload_availability`` is measured
#: rather than assumed.
RESTRICTED_STORAGE_ENV = "PGX_VALIDATION_RESTRICTED_ROOT"

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

BLOCKER_CODES: Mapping[str, Mapping[str, str]] = {
    "VALIDATION_NO_HOLDOUT_CASES": {
        "meaning": "no internal or expert holdout case has been authored, so "
                   "there is no independent evidence and no denominator",
        "owner": "scientific curators; a holdout case cannot be generated",
        "unblocks": "WP-21 can compute a rate over something real"},
    "VALIDATION_BELOW_P0_CASE_TARGET": {
        "meaning": "the P0 Definition of Done asks for at least 50 serious "
                   "validation cases and this repository has fewer",
        "owner": "scientific curators",
        "unblocks": "the P0 case-count item stops failing"},
    "VALIDATION_RESTRICTED_STORAGE_NOT_CONFIGURED": {
        "meaning": "no restricted storage root is configured, so an expert "
                   "payload has nowhere to live and nothing can be imported",
        "owner": "deployment",
        "unblocks": "the WP-18 import boundary becomes usable by WP-22"},
    "VALIDATION_NO_ACTIVE_RELEASE": {
        "meaning": "no release is registered or active, so a case's declared "
                   "compatibility cannot be resolved against anything",
        "owner": "WP-03 operation once artifacts exist",
        "unblocks": "compatibility declarations become checkable"},
    "VALIDATION_CLAIM_BOUNDARY_NOT_APPROVED": {
        "meaning": "the claim boundary is DRAFT and awaiting human and "
                   "scientific review",
        "owner": "the people named in docs/architecture/intended-purpose.md",
        "unblocks": "a validation result could be published at all"},
    "VALIDATION_BENCHMARK_NOT_PASSING": {
        "meaning": "WP-21's metric machinery is implemented and its benchmark "
                   "gate is not passing; no release has been benchmarked, so "
                   "no rate, ratio or percentage exists",
        "owner": "WP-21 operation once a release and holdout cases exist",
        "unblocks": "a validation result can be reported for a named release"},
    # Replaced at WP-22. The old code was VALIDATION_EXPERT_REVIEW_NOT_
    # IMPLEMENTED, and after WP-22 that sentence is false: the protocol,
    # the state machine and the review module exist. What is still true -
    # and is the fact Gate D actually needs - is that no expert has
    # completed a review under an approved protocol. Renaming rather than
    # deleting, because the blocker itself has not gone away.
    "VALIDATION_NO_COMPLETED_EXPERT_REVIEWS": {
        "meaning": "WP-22's blind review protocol and review module are "
                   "implemented, and no expert has completed a review under "
                   "them; there is no approved protocol, no expert-holdout "
                   "case and no named reviewer",
        "owner": "named experts under the approved protocol",
        "unblocks": "Gate D has its third input"},
}


def _restricted_storage_status(environ: Optional[Mapping[str, str]] = None
                               ) -> Tuple[PayloadAvailability, Optional[int]]:
    """Whether restricted storage is configured, and what is in it.

    Returns ``(availability, count_or_none)``. The count is ``None`` when
    nothing was configured, because nobody looked - as opposed to ``0``, which
    would mean somebody looked and the shelf was empty.
    """
    source = os.environ if environ is None else environ
    root = source.get(RESTRICTED_STORAGE_ENV)
    if not root:
        return PayloadAvailability.NOT_CONFIGURED, None
    if not os.path.isdir(root):
        return PayloadAvailability.NOT_CONFIGURED, None
    payloads = [name for name in os.listdir(root) if name.endswith(".json")]
    if not payloads:
        return PayloadAvailability.CONFIGURED_EMPTY, 0
    return PayloadAvailability.CONFIGURED_PRESENT, len(payloads)


def _expert_review_implemented(root: str) -> bool:
    """Whether WP-22's review module exists, measured from the tree.

    Delegated to WP-22's own marker list rather than duplicated, so the two
    documents cannot disagree about whether the module is there. Imported
    inside the function and guarded, for the reason WP-21 gives: an
    ImportError in an unrelated module must not turn a truthful answer into a
    crash inside a gate builder.
    """
    try:
        from pgx.expert_review.gate_status import (MODULE_MARKERS,
                                                   expert_review_module_markers)
    except Exception:  # pragma: no cover - a module that cannot be imported
        return False
    return len(expert_review_module_markers(root)) == len(MODULE_MARKERS)


def _later_packages_started(root: str) -> Dict[str, Any]:
    """Whether WP-19, WP-21 or WP-22 has begun. Measured from the tree."""
    markers = {
        "wp19": ("pgx/verification", "docs/architecture/wp19-verification.md"),
        # Corrected at WP-21. WP-18 guessed ``pgx/benchmark`` and
        # ``pgx/metrics``; neither was built, because the metric code depends
        # on the partition it must not violate and therefore lives inside
        # ``pgx/validation``. Left uncorrected, this would have reported
        # wp21_started=False forever while WP-21 was finished.
        "wp21": ("pgx/validation/benchmark.py", "pgx/validation/metrics.py",
                 "docs/architecture/wp21-validation-metrics.md"),
        # Corrected at WP-22, for the same reason WP-21's list was: WP-18
        # guessed a bare package directory, which an empty ``__init__.py``
        # would have satisfied. These are the files that actually constitute
        # the review module, and the protocol document is one of them -
        # a review module without its protocol is not a review module.
        "wp22": ("pgx/expert_review/service.py",
                 "pgx/expert_review/protocol.py",
                 "docs/validation/expert-protocol.md",
                 "docs/architecture/wp22-expert-review.md"),
    }
    found: Dict[str, Any] = {}
    for name, paths in markers.items():
        present = [path for path in paths
                   if os.path.exists(os.path.join(root, path))]
        found["%s_started" % name] = bool(present)
        found["%s_markers_found" % name] = present
    return found


def build_wp18_gate_status(root: str = _REPO_ROOT,
                           environ: Optional[Mapping[str, str]] = None
                           ) -> Dict[str, Any]:
    """The committed WP-18 gate status, measured from this repository."""
    cases = development_cases(root)
    audit = audit_partition(cases)
    availability, payload_count = _restricted_storage_status(environ)
    boundary = DEFAULT_CLAIM_BOUNDARY
    # WP-21's own measured state, read rather than restated. Imported here
    # rather than at module scope: WP-21's gate builder imports this module's
    # catalogue helper, and a top-level import would close the cycle.
    from pgx.validation.benchmark_gate_status import build_wp21_gate_status
    benchmark = build_wp21_gate_status(root, environ)

    holdout_total = (audit.internal_holdout_count
                     + audit.expert_holdout_count)

    blockers: List[Dict[str, Any]] = []

    def _block(code: str, detail: str) -> None:
        blockers.append({"code": code, "blocking": True, "detail": detail,
                         "owner": BLOCKER_CODES[code]["owner"]})

    if holdout_total == 0:
        _block("VALIDATION_NO_HOLDOUT_CASES",
               "internal holdout: 0, expert holdout: 0. The seven development "
               "cases are fixtures that shaped the software and are not "
               "validation evidence.")
    if holdout_total < P0_TARGET_CASE_COUNT:
        _block("VALIDATION_BELOW_P0_CASE_TARGET",
               "%d of at least %d serious validation cases exist; the gap is "
               "%d and is scientific work, not code."
               % (holdout_total, P0_TARGET_CASE_COUNT,
                  P0_TARGET_CASE_COUNT - holdout_total))
    if availability is PayloadAvailability.NOT_CONFIGURED:
        _block("VALIDATION_RESTRICTED_STORAGE_NOT_CONFIGURED",
               "%s is unset or does not name a directory" %
               RESTRICTED_STORAGE_ENV)
    _block("VALIDATION_NO_ACTIVE_RELEASE",
           "no release is registered or active in this repository")
    if not boundary.is_approved:
        _block("VALIDATION_CLAIM_BOUNDARY_NOT_APPROVED",
               "claim boundary status is %s" % boundary.status)
    if benchmark["benchmark_gate_status"] != "PASS":
        _block("VALIDATION_BENCHMARK_NOT_PASSING",
               "WP-21 benchmark gate is %s: %d validation-evidence case(s), "
               "%d numeric validation metric(s)"
               % (benchmark["benchmark_gate_status"],
                  benchmark["validation_evidence_case_count"],
                  benchmark["numeric_validation_metric_count"]))
    _block("VALIDATION_NO_COMPLETED_EXPERT_REVIEWS",
           "the WP-22 review module is implemented; the protocol is a draft, "
           "no expert-holdout case exists and no review has been completed")
    blockers.sort(key=lambda item: item["code"])

    document: Dict[str, Any] = {
        "gate_status_schema_version": GATE_STATUS_VERSION,
        "work_package": "WP-18",
        "vocabulary_version": VOCABULARY_VERSION,
        "implementation_status": "IMPLEMENTED",

        # 1. What exists, counted.
        "development_case_count": audit.development_count,
        "development_case_source": DEVELOPMENT_CATALOG_PATH,
        "internal_holdout_case_count": 0,
        "expert_holdout_case_count": 0,
        "holdout_case_count": holdout_total,
        "holdout_case_count_source": (
            "counted from the committed case set; zero because no holdout "
            "case has been authored, not because a lookup failed"),
        "real_patient_case_count": 0,
        "real_patient_case_count_source": (
            "structurally zero: the case model refuses every real-patient, "
            "genotype and raw-sequencing field at any depth, so there is no "
            "path by which one could exist. Real-patient ingestion is "
            "P2-03/P2-04 and is not implemented."),

        # 2. The target, kept apart from the count.
        "p0_target_case_count": P0_TARGET_CASE_COUNT,
        "p0_target_met": holdout_total >= P0_TARGET_CASE_COUNT,
        "p0_target_shortfall": max(0, P0_TARGET_CASE_COUNT - holdout_total),

        # 3. Restricted storage: null where nobody looked.
        "restricted_payload_availability": availability.value,
        "restricted_payload_count": payload_count,
        "restricted_payload_count_source": (
            "no restricted storage root is configured, so no count was taken; "
            "null rather than zero"
            if payload_count is None else
            "counted from the configured restricted storage root"),

        # 4. Separation.
        "separation_audit_clean": audit.is_clean,
        "separation_audit_issue_codes": list(audit.issue_codes),
        "separation_audit_checked_case_count": audit.checked_case_count,
        "separation_rules_checked": len(audit.to_json()["checked_rules"]),

        # 5. Governance, none of which WP-18 may close.
        "claim_boundary_phase": boundary.phase.value,
        "claim_boundary_status": boundary.status,
        "claim_boundary_approved": bool(boundary.is_approved),
        "active_release_available": False,
        "active_release_note": (
            "No release is registered in this repository. A case may declare "
            "which release it is compatible with; nothing here activates or "
            "invents one."),

        # 6. What has not been computed, stated rather than implied.
        #
        # ``validation_metrics_implemented`` became true at WP-21 and says
        # only that the machinery exists. ``validation_metric_count`` stays
        # null, because it counts metrics *computed for a release* and no
        # benchmark has been run - the definition count is a separate field
        # so the two can never be read as one number.
        "validation_metrics_implemented":
            bool(benchmark["metric_framework_implemented"]),
        "validation_metric_definition_count":
            benchmark["metric_definition_count"],
        "validation_metric_count": None,
        "validation_metric_count_source": (
            "null rather than zero: metrics are implemented and no benchmark "
            "has been executed against a release, so none was computed. A "
            "zero here would say a run produced no metrics; nothing ran."),
        "benchmark_gate_status": benchmark["benchmark_gate_status"],
        "benchmark_executed": bool(
            benchmark["benchmark_executed_against_active_release"]),
        "numeric_validation_metric_count":
            benchmark["numeric_validation_metric_count"],
        # True after WP-22: the module exists, measured from the tree by
        # WP-22's own gate builder rather than asserted here.
        "expert_review_implemented": _expert_review_implemented(root),
        "expert_review_protocol_approved": False,
        "expert_review_performed": False,
        # Still null, and for the unchanged reason: no review store was
        # inspected, so no count was taken. Implementing the module did not
        # turn "we did not look" into "we looked and found none".
        "expert_reviewed_case_count": None,
        "expert_reviewed_case_count_source": (
            "null rather than zero: WP-22's review module is implemented but "
            "no review store was inspected, so no review was counted"),

        # 7. Later packages, measured.
        **_later_packages_started(root),

        "blocker_count": len(blockers),
        "blockers": blockers,
        "may_report_validation_result": False,
        "note": (
            "WP-18 builds the partition, not the dataset. Development, "
            "internal holdout and expert holdout are structurally distinct "
            "and cannot be mixed silently; that is what is implemented. What "
            "is absent is every holdout case, because authoring one is "
            "scientific work and generating one would be the fabrication this "
            "architecture exists to prevent. No metric, rate or percentage "
            "appears in this document, no case carries an expected answer, "
            "and no count above was asserted rather than measured."),
    }
    return document


def gate_status_digest(document: Mapping[str, Any]) -> str:
    return sha256_digest(document)
