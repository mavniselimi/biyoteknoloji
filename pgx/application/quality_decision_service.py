# -*- coding: utf-8 -*-
"""WP-C06: recording a dataset quality decision, and what follows from it.

Two things happen when a data owner decides, and they are different acts. The
decision is recorded - who, when, on what, and why - and that record is kept
whichever way they decided. Only then, and only for an approval, is the WP-07
transition attempted.

This module joins those two acts without merging them. It owns no state guard,
no audit format and no transition: the ledger in
:mod:`pgx.normalization.quality_decision` owns the record, and
:class:`pgx.application.canonical_service.CanonicalDatasetService` owns the
transition, with the verification and the guard it always had. What was
missing was the decision itself and the fact that nothing connected one to
the other.

**A rejection is a first-class outcome.** It is recorded, it is auditable, and
it moves nothing. The failure this guards against is a system in which saying
no leaves no trace, so that the only visible decisions are the approvals.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from pgx.normalization.quality_decision import (DatasetQualityDecision,
                                                DecisionOutcome,
                                                DecisionResult,
                                                QualityDecision,
                                                append_decision)

__all__ = ["QualityDecisionServiceResult", "record_dataset_quality_decision"]


@dataclass(frozen=True)
class QualityDecisionServiceResult:
    """What was recorded, and what - if anything - it caused."""

    decision_result: DecisionResult
    transition_outcome: Optional[str] = None
    transition_detail: str = ""

    @property
    def recorded(self) -> bool:
        return self.decision_result.outcome.is_recorded

    @property
    def transitioned(self) -> bool:
        return self.transition_outcome == "QUALITY_CHECKED"

    def to_json(self) -> Dict[str, Any]:
        return {
            "decision": self.decision_result.to_json(),
            "transition_attempted": self.transition_outcome is not None,
            "transition_outcome": self.transition_outcome,
            "transition_detail": self.transition_detail,
            "note": ("Recording a decision and moving a dataset are two acts. "
                     "A rejection is recorded and moves nothing; an approval "
                     "is a precondition for the WP-07 transition, which "
                     "applies its own guard and may still refuse."),
        }


def record_dataset_quality_decision(
        decision: DatasetQualityDecision,
        build_path: str,
        source_registry_path: str,
        ledger_path: str,
        canonical_service: Any = None,
        quality_check_request: Any = None) -> QualityDecisionServiceResult:
    """Record the decision; attempt the transition only if it was an approval.

    The order is deliberate. The ledger refuses a replay, a stale binding and
    an absent build before anything else happens, so a refused decision never
    reaches the transition and never leaves a half-recorded state behind.

    ``canonical_service`` is optional because the record is worth keeping even
    where no database is reachable. When it is absent, an approval is recorded
    and the transition is reported as not attempted - which is the truth, and
    is not the same as a transition that was attempted and refused.
    """
    result = append_decision(decision, build_path, source_registry_path,
                             ledger_path)
    if not result.outcome.is_recorded:
        return QualityDecisionServiceResult(decision_result=result)

    if decision.decision is QualityDecision.REJECTED:
        return QualityDecisionServiceResult(
            decision_result=result,
            transition_detail=("rejected; no transition is attempted and the "
                               "dataset is not release-eligible"))

    if canonical_service is None or quality_check_request is None:
        return QualityDecisionServiceResult(
            decision_result=result,
            transition_detail=("approval recorded; no canonical service was "
                               "supplied, so the WP-07 transition was not "
                               "attempted here"))

    transition = canonical_service.record_quality_check(quality_check_request)
    return QualityDecisionServiceResult(
        decision_result=result,
        transition_outcome=getattr(transition.outcome, "value",
                                   str(transition.outcome)),
        transition_detail=transition.detail)
