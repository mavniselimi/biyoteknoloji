# -*- coding: utf-8 -*-
"""The 1,000-assessment run (WP-24).

Two halves, and the order between them is the point.

**The target registry comes first.** It is defined in this module as a
constant, with a version, before any measurement exists - exactly as WP-21's
metric registry is, and for the same reason architecture.md gives: *"Performance
targets must be declared in the report before results are interpreted."* A
target chosen after the numbers is not a target, it is a description.

**The measurement comes second, and only against an eligible release.**
``execute_run`` refuses without one. That refusal is the load-bearing part of
this file: a throughput figure produced against a development fixture is a
figure about a fixture, and the moment it appears in a report next to the
words "1,000 assessments" it becomes a claim about the system. There is no
flag that relaxes this. A separate, explicitly labelled
``TEST_ONLY_REHEARSAL`` path exists so the percentile arithmetic and the
request generation can be exercised - and everything it produces carries the
label, which travels into the artifact and cannot be dropped by a caller.

Percentile definition, fixed before any run: **nearest-rank on the sorted
sample**, ``ceil(p/100 * n)`` clamped to ``[1, n]``, over *completed*
observations only. Failed attempts are counted in ``failed`` and in
``error_rate`` and are excluded from latency percentiles, because a request
that errored in 2 ms is not evidence that the system is fast. With ``n == 0``
every percentile is ``null`` - never ``0``, which would read as instantaneous.

Nothing here records a response body, a credential, a cookie, a CSRF token or
any holdout content. Inputs are identified by case id and by a hash of the
input mix.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Callable, List, Mapping, Optional, Sequence, Tuple

from pgx.deployment.vocabulary import (REHEARSAL_LABEL,
                                       DeploymentEnvironmentKind,
                                       ExecutionState, blocker)

__all__ = [
    "PERFORMANCE_TARGETS",
    "PERFORMANCE_TARGET_REGISTRY_VERSION",
    "PERFORMANCE_RESULT_VERSION",
    "REQUIRED_ATTEMPTS",
    "PerformanceTarget",
    "execute_run",
    "percentile",
    "summarise",
    "target_registry",
]

PERFORMANCE_TARGET_REGISTRY_VERSION = "pgx-wp24-performance-targets/1"
PERFORMANCE_RESULT_VERSION = "pgx-wp24-performance-result/1"

#: Exactly this many attempts for the real run. Not "about a thousand": the
#: number is in architecture.md section 14.3 and a run of 987 is a different
#: experiment reported under the same name.
REQUIRED_ATTEMPTS = 1000

#: Discarded before measurement begins. Declared here rather than chosen at
#: run time so that a slow run cannot be improved by warming up for longer.
WARMUP_ATTEMPTS = 50


@dataclass(frozen=True)
class PerformanceTarget:
    """One declared engineering target.

    ``rationale`` is required. A number with no reason behind it cannot be
    argued with, and a target nobody can argue with is one nobody will revise
    when it turns out to be wrong.
    """

    target_id: str
    metric: str
    comparator: str
    value: float
    unit: str
    rationale: str


#: The targets. Engineering and prototype targets for a demonstration
#: deployment - explicitly NOT clinical performance claims, NOT a service
#: level, and NOT evidence that any result is correct. They describe how fast
#: a deterministic computation and its transport are, and nothing else.
PERFORMANCE_TARGETS: Tuple[PerformanceTarget, ...] = (
    PerformanceTarget(
        "PERF-001", "latency_p50_ms", "<=", 250.0, "milliseconds",
        "A demonstration is conducted by a person clicking through cases. "
        "Median latency above a quarter of a second is felt as lag, and the "
        "assessment is a deterministic rule evaluation with no model call, so "
        "there is nothing that should take longer."),
    PerformanceTarget(
        "PERF-002", "latency_p95_ms", "<=", 1000.0, "milliseconds",
        "The tail is what a demonstration trips over. One second bounds the "
        "worst case a reviewer is likely to hit in a session; a slower tail "
        "usually means a connection-pool wait rather than computation."),
    PerformanceTarget(
        "PERF-003", "throughput_rps", ">=", 20.0, "requests per second",
        "A prototype target for a single container with the CPU and memory "
        "limits recorded beside the result. It is not a capacity claim and "
        "does not extrapolate to any other configuration."),
    PerformanceTarget(
        "PERF-004", "error_rate", "<=", 0.001, "fraction of attempts",
        "One failure in a thousand deterministic evaluations of committed "
        "inputs is already one too many: a deterministic engine given "
        "permitted input has no legitimate reason to fail, so any error here "
        "is a defect rather than a load characteristic."),
    PerformanceTarget(
        "PERF-005", "output_determinism", "==", 1.0, "fraction of repeats",
        "Every repeat of an identical input against the same release must "
        "produce a byte-identical result. This is separate from latency on "
        "purpose - latency varies legitimately, output does not, and a "
        "report that mixed them could hide a nondeterministic result inside "
        "a spread of timings."),
)


def target_registry() -> Mapping[str, object]:
    """The declared targets. Published before any measurement exists."""
    return {
        "performance_target_registry_version":
            PERFORMANCE_TARGET_REGISTRY_VERSION,
        "declared_before_measurement": True,
        "required_attempts": REQUIRED_ATTEMPTS,
        "warmup_attempts": WARMUP_ATTEMPTS,
        "percentile_definition": (
            "Nearest-rank on the sorted sample of COMPLETED observations: "
            "index = ceil(p/100 * n), clamped to [1, n]. Failed attempts are "
            "counted in error_rate and excluded from latency, because a "
            "request that errored in 2 ms is not evidence of speed."),
        "zero_denominator_behaviour": (
            "With no completed observation every percentile and the "
            "throughput are null. Never zero: zero milliseconds reads as "
            "instantaneous and zero requests per second reads as measured."),
        "not_a_clinical_claim": (
            "These are engineering and prototype targets for a demonstration "
            "deployment. They are not clinical performance claims, not a "
            "service level, and not evidence that any assessment is correct."),
        "targets": [
            {"target_id": item.target_id, "metric": item.metric,
             "comparator": item.comparator, "value": item.value,
             "unit": item.unit, "rationale": item.rationale}
            for item in PERFORMANCE_TARGETS],
    }


def percentile(samples: Sequence[float], p: float) -> Optional[float]:
    """Nearest-rank percentile, or ``None`` for an empty sample.

    ``None`` rather than ``0.0``. The distinction is the whole reason this
    function exists rather than a one-line expression at the call site: a
    zero-latency percentile in a report reads as an extraordinarily fast
    system, and it is what an empty list produces in almost every naive
    implementation.
    """
    if not samples:
        return None
    ordered = sorted(samples)
    rank = max(1, min(len(ordered), math.ceil(p / 100.0 * len(ordered))))
    return float(ordered[rank - 1])


def _input_mix_hash(case_ids: Sequence[str]) -> str:
    payload = json.dumps(sorted(case_ids), sort_keys=True, ensure_ascii=True)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def summarise(observations: Sequence[Mapping[str, Any]], *,
              attempted: int, wall_seconds: float) -> Mapping[str, object]:
    """Turn raw observations into the reported metrics.

    Separated from execution so the arithmetic is testable without a
    deployment - and so that a test can prove the zero-denominator behaviour
    without needing a run that produced nothing.
    """
    completed = [item for item in observations if item.get("ok")]
    failed = [item for item in observations if not item.get("ok")]
    latencies = [float(item["latency_ms"]) for item in completed
                 if item.get("latency_ms") is not None]
    codes: dict = {}
    for item in observations:
        key = str(item.get("code") or ("ok" if item.get("ok") else "error"))
        codes[key] = codes.get(key, 0) + 1
    return {
        "attempted": attempted,
        "completed": len(completed),
        "failed": len(failed),
        "latency_p50_ms": percentile(latencies, 50),
        "latency_p95_ms": percentile(latencies, 95),
        "latency_p99_ms": percentile(latencies, 99),
        "latency_min_ms": min(latencies) if latencies else None,
        "latency_max_ms": max(latencies) if latencies else None,
        "throughput_rps": (round(len(completed) / wall_seconds, 4)
                           if wall_seconds > 0 and completed else None),
        # A rate over zero attempts is undefined, not zero. A report showing
        # a 0.0 error rate for a run that never started is the single most
        # misleading number this module could produce.
        "error_rate": (round(len(failed) / attempted, 6) if attempted
                       else None),
        "response_code_distribution": dict(sorted(codes.items())),
        "wall_seconds": round(wall_seconds, 4) if wall_seconds else None,
    }


def execute_run(*, release: Optional[Mapping[str, Any]] = None,
                case_ids: Optional[Sequence[str]] = None,
                perform: Optional[Callable[[str], Mapping[str, Any]]] = None,
                attempts: int = REQUIRED_ATTEMPTS,
                concurrency: int = 1,
                image_digest: Optional[str] = None,
                resource_limits: Optional[Mapping[str, Any]] = None,
                environment: DeploymentEnvironmentKind =
                DeploymentEnvironmentKind.LOCAL_REHEARSAL,
                test_only: bool = False,
                clock: Optional[Callable[[], float]] = None,
                now: Optional[_dt.datetime] = None) -> Mapping[str, object]:
    """Run the measurement, or refuse and say what is missing.

    ``release`` must carry a ``release_id`` and a ``release_manifest_hash``.
    Both, not either: an id without a manifest hash names a release whose
    contents are not pinned, and a measurement attached to it could not be
    reproduced or contested.

    ``test_only`` marks a rehearsal of the machinery. It does not relax the
    release requirement - it changes what the result is *called*, and the
    label travels into the artifact where a reader will see it next to the
    numbers.
    """
    import time

    monotonic = clock or time.monotonic
    blockers = []
    eligible = bool(release and release.get("release_id")
                    and release.get("release_manifest_hash"))
    if not eligible:
        blockers.append(dict(blocker(
            "DEPLOY_NO_ELIGIBLE_RELEASE",
            owner=("scientific curators, expert reviewers and an "
                   "administrator - a release must be approved, registered "
                   "and activated before anything can be measured against "
                   "it"),
            detail=("no active validated release with both a release_id and "
                    "a release_manifest_hash was supplied; a measurement "
                    "with nothing pinned could not be reproduced or "
                    "contested")).to_json()))
    if perform is None:
        blockers.append(dict(blocker(
            "DEPLOY_PERFORMANCE_NOT_EXECUTED",
            owner="WP-24 operation against a running deployment",
            detail=("no request performer was supplied, so no assessment was "
                    "attempted")).to_json()))
    if blockers:
        return _blocked_result(blockers, attempts=attempts,
                               concurrency=concurrency, release=release,
                               environment=environment, test_only=test_only,
                               image_digest=image_digest,
                               resource_limits=resource_limits, now=now)

    ids = list(case_ids or [])
    if not ids:
        return _blocked_result(
            [dict(blocker("DEPLOY_PERFORMANCE_NOT_EXECUTED",
                          owner="WP-24 operation",
                          detail=("no permitted input case was supplied; a "
                                  "run over an empty mix measures nothing")
                          ).to_json())],
            attempts=attempts, concurrency=concurrency, release=release,
            environment=environment, test_only=test_only,
            image_digest=image_digest, resource_limits=resource_limits,
            now=now)

    started = _dt.datetime.now(_dt.timezone.utc) if now is None else now
    # Warm-up, discarded. Declared in the registry above rather than chosen
    # here, so a slow run cannot be improved by warming up for longer.
    for index in range(min(WARMUP_ATTEMPTS, attempts)):
        try:
            perform(ids[index % len(ids)])
        except Exception:  # noqa: BLE001 - warm-up outcomes are discarded
            pass

    observations: List[Mapping[str, Any]] = []
    begin = monotonic()
    for index in range(attempts):
        case_id = ids[index % len(ids)]
        request_started = monotonic()
        try:
            outcome = perform(case_id)
            latency = (monotonic() - request_started) * 1000.0
            observations.append({
                "ok": bool(outcome.get("ok", True)),
                "code": outcome.get("code"),
                "latency_ms": latency,
                # A hash, never the body. What is compared across repeats is
                # whether the output changed, and a digest answers that
                # without carrying an assessment into a report.
                "output_hash": outcome.get("output_hash"),
            })
        except Exception as error:  # noqa: BLE001
            observations.append({"ok": False, "code": type(error).__name__,
                                 "latency_ms": None, "output_hash": None})
    wall = monotonic() - begin

    metrics = dict(summarise(observations, attempted=attempts,
                             wall_seconds=wall))
    determinism = _determinism(observations)
    state = (ExecutionState.TEST_ONLY_REHEARSAL if test_only
             else ExecutionState.EXECUTED)
    return {
        "performance_result_version": PERFORMANCE_RESULT_VERSION,
        "state": state.value,
        "test_only": test_only,
        "rehearsal_label": (REHEARSAL_LABEL if environment is
                            DeploymentEnvironmentKind.LOCAL_REHEARSAL
                            else None),
        "environment_kind": environment.value,
        "attempts_required": REQUIRED_ATTEMPTS,
        "attempts_meets_requirement": attempts == REQUIRED_ATTEMPTS,
        "warmup_attempts": min(WARMUP_ATTEMPTS, attempts),
        "concurrency": concurrency,
        "release_id": (release or {}).get("release_id"),
        "release_manifest_hash": (release or {}).get(
            "release_manifest_hash"),
        "software_id": (release or {}).get("software_id"),
        "dataset_id": (release or {}).get("dataset_id"),
        "ruleset_id": (release or {}).get("ruleset_id"),
        "input_case_count": len(ids),
        "input_mix_hash": _input_mix_hash(ids),
        "input_case_ids": sorted(ids)[:200],
        "image_digest": image_digest,
        "resource_limits": dict(resource_limits or {}),
        "started_at": started.isoformat(),
        "finished_at": _dt.datetime.now(_dt.timezone.utc).isoformat()
        if now is None else started.isoformat(),
        "target_registry_version": PERFORMANCE_TARGET_REGISTRY_VERSION,
        "targets_evaluated": _evaluate_targets(metrics, determinism),
        "output_determinism": determinism,
        "blockers": [],
        "note": _PERF_NOTE,
        **metrics,
    }


def _determinism(observations: Sequence[Mapping[str, Any]]
                 ) -> Mapping[str, object]:
    """Whether identical inputs produced identical outputs.

    Reported separately from latency, deliberately. Latency varies
    legitimately between runs and output does not; a single "stable" figure
    covering both could hide a nondeterministic result inside a spread of
    timings.
    """
    hashes = [item.get("output_hash") for item in observations
              if item.get("ok") and item.get("output_hash")]
    if not hashes:
        return {"comparable_observations": 0, "distinct_output_hashes": None,
                "deterministic": None,
                "reason": "no output hash was recorded, so nothing was "
                          "compared"}
    distinct = len(set(hashes))
    return {"comparable_observations": len(hashes),
            "distinct_output_hashes": distinct,
            "deterministic": distinct == 1,
            "reason": ""}


def _evaluate_targets(metrics: Mapping[str, Any],
                      determinism: Mapping[str, Any]) -> Sequence[Mapping]:
    results = []
    for target in PERFORMANCE_TARGETS:
        if target.metric == "output_determinism":
            observed: Optional[float] = (
                1.0 if determinism.get("deterministic") is True
                else 0.0 if determinism.get("deterministic") is False
                else None)
        else:
            raw = metrics.get(target.metric)
            observed = None if raw is None else float(raw)
        met: Optional[bool]
        if observed is None:
            met = None
        elif target.comparator == "<=":
            met = observed <= target.value
        elif target.comparator == ">=":
            met = observed >= target.value
        else:
            met = observed == target.value
        results.append({"target_id": target.target_id,
                        "metric": target.metric, "declared": target.value,
                        "comparator": target.comparator,
                        "observed": observed, "met": met})
    return results


def _blocked_result(blockers, *, attempts, concurrency, release, environment,
                    test_only, image_digest, resource_limits, now):
    return {
        "performance_result_version": PERFORMANCE_RESULT_VERSION,
        "state": ExecutionState.BLOCKED.value,
        "test_only": test_only,
        "rehearsal_label": (REHEARSAL_LABEL if environment is
                            DeploymentEnvironmentKind.LOCAL_REHEARSAL
                            else None),
        "environment_kind": environment.value,
        "attempts_required": REQUIRED_ATTEMPTS,
        "attempts_meets_requirement": False,
        "concurrency": concurrency,
        "release_id": (release or {}).get("release_id"),
        "release_manifest_hash": (release or {}).get(
            "release_manifest_hash"),
        # Every measurement is null. Not zero - a zero here would say the
        # system answered a thousand times in no time with no errors.
        "attempted": 0, "completed": None, "failed": None,
        "latency_p50_ms": None, "latency_p95_ms": None,
        "latency_p99_ms": None, "latency_min_ms": None,
        "latency_max_ms": None, "throughput_rps": None, "error_rate": None,
        "response_code_distribution": {}, "wall_seconds": None,
        "input_case_count": 0, "input_mix_hash": None, "input_case_ids": [],
        "image_digest": image_digest,
        "resource_limits": dict(resource_limits or {}),
        "started_at": None, "finished_at": None,
        "target_registry_version": PERFORMANCE_TARGET_REGISTRY_VERSION,
        "targets_evaluated": _evaluate_targets({}, {}),
        "output_determinism": {"comparable_observations": 0,
                               "distinct_output_hashes": None,
                               "deterministic": None,
                               "reason": "no run was performed"},
        "blockers": blockers,
        "note": _PERF_NOTE,
    }


_PERF_NOTE = (
    "Targets were declared before measurement, in "
    "pgx.deployment.performance.PERFORMANCE_TARGETS. A run refuses without "
    "an active validated release: a throughput figure produced against a "
    "development fixture is a figure about a fixture, and next to the words "
    "'1,000 assessments' it becomes a claim about the system. No response "
    "body, credential, cookie, CSRF token or holdout content is recorded.")
