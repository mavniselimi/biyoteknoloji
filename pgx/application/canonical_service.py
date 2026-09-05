# -*- coding: utf-8 -*-
"""The audited dataset quality transition (WP-07).

Standard library plus :mod:`pgx.domain`, :mod:`pgx.normalization` and
:mod:`pgx.application.canonical_schema`. No infrastructure type appears in any
signature; the unit of work is injected.

**One transition, and only one.** ``BUILDING -> QUALITY_CHECKED``. There is no
``publish``, no ``activate``, no ``retire`` and no ``rollback`` in this module.
Publication and release activation belong to WP-03's release registry and to a
human, and putting either here would give canonicalization a route to a state
it has no business setting.

**Nothing about this transition is automatic.** Every one of ``reviewed_by``,
``reviewed_at`` and ``rationale`` is a required argument with no default, so a
transition with no author cannot be expressed. The quality gate must pass first,
and if it does not, the service returns the blocking codes and changes nothing.
The CLI exposes no path to this function at all: `pgx-normalize quality-check`
computes and prints the gate, and stops.

**Why it exists when nothing in this repository can use it.** The real dataset
is a quarantined legacy import over an unapproved source, so its gate is
blocked and will stay blocked until a human approves the source and a fresh
acquisition-backed snapshot exists. The mechanism is written and tested now,
against synthetic datasets, so that when those preconditions are met the
transition is an audited service call rather than an `UPDATE` somebody types.

**What it records.** The dataset's status, the reviewer, the instant, the DQ
report's path and content hash, and one append-only audit event carrying the
canonical build key and the gate's own summary. A dataset marked quality checked
against a report nobody can identify is not evidence of a quality check.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from pgx.application.canonical_schema import (validate_canonical_manifest,
                                              validate_dq_report)
from pgx.domain.enums import AuditAction, DatasetStatus
from pgx.domain.hashing import ensure_utc
from pgx.domain.identifiers import AuditEventId
from pgx.domain.models import AuditEvent
from pgx.normalization.build import read_build_manifest, verify_build
from pgx.normalization.errors import QualityGateError
from pgx.normalization.quality import (DQ_REPORT_VERSION, compare_with_artifacts,
                                       recount_from_build_path)

__all__ = [
    "CanonicalDatasetService",
    "QualityCheckRequest",
    "QualityCheckResult",
    "TransitionOutcome",
]


class TransitionOutcome(str, Enum):
    """What a transition attempt actually did.

    A refusal is an ordinary outcome here, not an exception, because most
    attempts in this project are expected to be refused and a caller should be
    able to report *why* without catching anything.
    """

    QUALITY_CHECKED = "QUALITY_CHECKED"
    REFUSED_GATE_BLOCKED = "REFUSED_GATE_BLOCKED"
    REFUSED_WRONG_STATE = "REFUSED_WRONG_STATE"
    REFUSED_BUILD_UNVERIFIED = "REFUSED_BUILD_UNVERIFIED"
    REFUSED_REPORT_MISSING = "REFUSED_REPORT_MISSING"
    REFUSED_SCHEMA_INVALID = "REFUSED_SCHEMA_INVALID"
    DATASET_NOT_FOUND = "DATASET_NOT_FOUND"

    def __str__(self) -> str:
        return self.value

    @property
    def succeeded(self) -> bool:
        return self is TransitionOutcome.QUALITY_CHECKED


@dataclass(frozen=True)
class QualityCheckRequest:
    """One human's decision to mark one dataset quality checked.

    ``reviewed_by``, ``reviewed_at`` and ``rationale`` have no defaults. That is
    the point: a decision with no author, no instant or no reason cannot be
    constructed, so it cannot reach the repository or the database.

    ``expected_current_state`` defaults to ``BUILDING`` and is applied as a
    guard, so a repeated attempt on an already-checked dataset is refused rather
    than silently re-run.
    """

    dataset_public_id: str
    build_path: str
    reviewed_by: str
    reviewed_at: _dt.datetime
    rationale: str
    expected_current_state: DatasetStatus = DatasetStatus.BUILDING

    def __post_init__(self) -> None:
        for name in ("dataset_public_id", "build_path", "reviewed_by",
                     "rationale"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise QualityGateError(
                    "QualityCheckRequest.%s must be a non-empty string; a "
                    "quality decision names a human, an instant and a reason"
                    % name)
        if not isinstance(self.expected_current_state, DatasetStatus):
            raise QualityGateError(
                "expected_current_state must be a DatasetStatus")
        if self.expected_current_state is not DatasetStatus.BUILDING:
            raise QualityGateError(
                "the only transition this service performs is BUILDING -> "
                "QUALITY_CHECKED; %s is not a state it moves from"
                % self.expected_current_state.value)
        object.__setattr__(self, "reviewed_at",
                           ensure_utc(self.reviewed_at, "reviewed_at"))


@dataclass(frozen=True)
class QualityCheckResult:
    """What happened, and everything needed to explain it."""

    outcome: TransitionOutcome
    dataset_public_id: str
    canonical_build_key: Optional[str] = None
    blocking_codes: Tuple[str, ...] = ()
    problems: Tuple[str, ...] = ()
    dq_report_hash: Optional[str] = None
    detail: str = ""

    @property
    def succeeded(self) -> bool:
        return self.outcome.succeeded

    def to_json(self) -> Dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "succeeded": self.succeeded,
            "dataset_public_id": self.dataset_public_id,
            "canonical_build_key": self.canonical_build_key,
            "blocking_codes": list(self.blocking_codes),
            "problems": list(self.problems),
            "dq_report_hash": self.dq_report_hash,
            "detail": self.detail,
        }


class CanonicalDatasetService:
    """Reads a sealed build and, if everything passes, records one decision."""

    def __init__(self, uow_factory) -> None:
        """Args: ``uow_factory`` returns a fresh unit of work per call."""
        self._uow_factory = uow_factory

    # -- read-only -------------------------------------------------------

    def inspect(self, build_path: str) -> Dict[str, Any]:
        """Everything the service would check, without changing anything."""
        checksums_ok, checksum_problems = verify_build(build_path)
        summary_ok, summary_problems = (True, ())
        if checksums_ok:
            summary_ok, summary_problems = compare_with_artifacts(build_path)
        report, report_problems = _read_report(build_path)
        decision = (report or {}).get("decision") or {}
        return {
            "build_path": build_path,
            "checksums_ok": checksums_ok,
            "checksum_problems": list(checksum_problems),
            "summary_agrees_with_artifacts": summary_ok,
            "summary_problems": list(summary_problems),
            "report_problems": list(report_problems),
            "gate_passed": bool(decision.get("passed")),
            "blocking_codes": list(decision.get("blocking_codes") or ()),
            "recount": recount_from_build_path(build_path),
        }

    # -- the one transition ----------------------------------------------

    def record_quality_check(self,
                             request: QualityCheckRequest) -> QualityCheckResult:
        """Record a human's quality decision, or refuse and say why.

        Order matters. Every check that can refuse runs *before* the unit of
        work is opened, so a refusal never leaves a half-written transaction;
        the state guard runs inside it, where it is atomic.
        """
        checks = self._preconditions(request)
        if checks is not None:
            return checks

        manifest = read_build_manifest(request.build_path)
        report, _ = _read_report(request.build_path)
        build_key = manifest.get("canonical_build_key")
        report_hash = report.get("content_hash")
        report_path = os.path.join(request.build_path, "dq-report.json")

        with self._uow_factory() as uow:
            current = uow.datasets.get_status(request.dataset_public_id)
            if current is None:
                return QualityCheckResult(
                    outcome=TransitionOutcome.DATASET_NOT_FOUND,
                    dataset_public_id=request.dataset_public_id,
                    detail="no dataset version is registered under this id")
            if current != request.expected_current_state.value:
                return QualityCheckResult(
                    outcome=TransitionOutcome.REFUSED_WRONG_STATE,
                    dataset_public_id=request.dataset_public_id,
                    canonical_build_key=build_key,
                    detail=("the dataset is %s, not %s. A repeated or "
                            "out-of-order transition is refused rather than "
                            "silently re-applied."
                            % (current, request.expected_current_state.value)))

            uow.datasets.record_quality_check(
                dataset_public_id=request.dataset_public_id,
                expected_current_state=request.expected_current_state.value,
                dq_report_path=report_path,
                dq_report_hash=report_hash,
                canonical_build_key=build_key,
                reviewed_by=request.reviewed_by,
                reviewed_at=request.reviewed_at,
                rationale=request.rationale)

            uow.audit.append(AuditEvent(
                id=AuditEventId.new(),
                action=AuditAction.DATASET_QUALITY_CHECKED,
                actor=request.reviewed_by,
                object_type="dataset_version",
                object_id=request.dataset_public_id,
                occurred_at=request.reviewed_at,
                reason=request.rationale,
                metadata={
                    "canonical_build_key": build_key,
                    "build_content_hash": manifest.get("content_hash"),
                    "dq_report_hash": report_hash,
                    "dq_report_version": report.get("dq_report_version"),
                    "advisory_codes": list(
                        (report.get("decision") or {}).get("advisory_codes")
                        or ()),
                    "previous_state": request.expected_current_state.value,
                    "new_state": DatasetStatus.QUALITY_CHECKED.value,
                }))
            uow.commit()

        return QualityCheckResult(
            outcome=TransitionOutcome.QUALITY_CHECKED,
            dataset_public_id=request.dataset_public_id,
            canonical_build_key=build_key,
            dq_report_hash=report_hash,
            detail=("recorded by %s. This is one human's decision about one "
                    "build; it is not a publication and activates no release."
                    % request.reviewed_by))

    # -- internals -------------------------------------------------------

    def _preconditions(self, request: QualityCheckRequest
                       ) -> Optional[QualityCheckResult]:
        """Every refusal that can be decided without opening a transaction."""
        checksums_ok, checksum_problems = verify_build(request.build_path)
        if not checksums_ok:
            return QualityCheckResult(
                outcome=TransitionOutcome.REFUSED_BUILD_UNVERIFIED,
                dataset_public_id=request.dataset_public_id,
                problems=tuple(checksum_problems),
                detail=("the build does not match its own recorded digests; "
                        "its bytes have changed since it was sealed"))

        summary_ok, summary_problems = compare_with_artifacts(request.build_path)
        if not summary_ok:
            return QualityCheckResult(
                outcome=TransitionOutcome.REFUSED_BUILD_UNVERIFIED,
                dataset_public_id=request.dataset_public_id,
                problems=tuple(summary_problems),
                detail=("the recorded summary disagrees with the artifacts it "
                        "describes"))

        report, report_problems = _read_report(request.build_path)
        if report is None:
            return QualityCheckResult(
                outcome=TransitionOutcome.REFUSED_REPORT_MISSING,
                dataset_public_id=request.dataset_public_id,
                problems=tuple(report_problems),
                detail="the build carries no readable data quality report")

        manifest = read_build_manifest(request.build_path)
        schema_problems = tuple(
            ["manifest.json: %s" % problem
             for problem in validate_canonical_manifest(manifest)]
            + ["dq-report.json: %s" % problem
               for problem in validate_dq_report(report)])
        if schema_problems:
            return QualityCheckResult(
                outcome=TransitionOutcome.REFUSED_SCHEMA_INVALID,
                dataset_public_id=request.dataset_public_id,
                problems=schema_problems,
                detail="the build's documents no longer match the published "
                       "schemas")

        if manifest.get("dataset_public_id") != request.dataset_public_id:
            return QualityCheckResult(
                outcome=TransitionOutcome.REFUSED_WRONG_STATE,
                dataset_public_id=request.dataset_public_id,
                detail=("the build at %s describes dataset %r, not %r"
                        % (request.build_path,
                           manifest.get("dataset_public_id"),
                           request.dataset_public_id)))

        decision = report.get("decision") or {}
        if not decision.get("passed"):
            return QualityCheckResult(
                outcome=TransitionOutcome.REFUSED_GATE_BLOCKED,
                dataset_public_id=request.dataset_public_id,
                canonical_build_key=manifest.get("canonical_build_key"),
                blocking_codes=tuple(decision.get("blocking_codes") or ()),
                dq_report_hash=report.get("content_hash"),
                detail=("the quality gate is blocked. The gate fails closed, "
                        "and there is no argument to this service that "
                        "overrides it."))
        return None


def _read_report(build_path: str) -> Tuple[Optional[Mapping[str, Any]],
                                           Tuple[str, ...]]:
    path = os.path.join(build_path, "dq-report.json")
    if not os.path.isfile(path):
        return None, ("no dq-report.json in %s" % build_path,)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        return None, ("dq-report.json is unreadable: %s" % exc,)
    if payload.get("dq_report_version") != DQ_REPORT_VERSION:
        return payload, (
            "dq-report.json declares version %r; this build reads %r"
            % (payload.get("dq_report_version"), DQ_REPORT_VERSION),)
    return payload, ()
