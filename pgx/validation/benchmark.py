# -*- coding: utf-8 -*-
"""The benchmark engine (WP-21): run the plan, compute the metrics, refuse.

The order of operations here is the safety property, so it is worth stating
plainly before the code:

1. Audit the separation of the case set. **If it is not clean, compute
   nothing.** Not "compute the clean partitions"; nothing. A dirty audit means
   the roles may not mean what they say, and every metric downstream is a
   statement about roles.
2. Resolve exactly one release, once, and pin it.
3. Collect observations per role through the injected port.
4. Verify every observation against the pinned identities. One disagreement
   refuses the whole run.
5. Compute each declared metric, per role, never across roles.

Step 5 has no combining step and no ``overall`` figure. That absence is
deliberate and is asserted by test: an aggregate over development and holdout
would let seven fixtures that shaped the software carry a partition that was
supposed to be independent of it, and an aggregate across the two holdout
roles would let the easier one carry the harder.

Development observations are computed too - determinism and conflict counts
are software properties worth regressing - and every value they produce is
marked ``is_validation_evidence: false`` by the metric layer, in a section the
report names ``DEVELOPMENT_REGRESSION``.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.validation.benchmark_models import (BenchmarkError,
                                             BenchmarkObservation,
                                             BenchmarkPlan, BenchmarkRun,
                                             PinMismatchError,
                                             ReferenceJudgment,
                                             ReferenceJudgmentPort,
                                             RestrictedObservationPort)
from pgx.validation.metric_definitions import (FAILURE_PATH_CATALOGUE,
                                               MetricDefinition,
                                               UnavailableReason,
                                               definitions_by_id)
from pgx.validation.metrics import (MetricValue, blocked, distribution,
                                    measured_count, measured_rate,
                                    not_executed, unavailable)
from pgx.validation.separation import SeparationAudit, audit_partition
from pgx.validation.vocabulary import ValidationCaseRole

__all__ = [
    "DEVELOPMENT_SECTION",
    "BenchmarkEngine",
    "SeparationNotCleanError",
    "reassuring_levels",
    "verify_observation",
]

#: The one section name a development result may appear under. Named as a
#: constant so the report, the schema, the dashboard and the tests all use the
#: same string and none of them can quietly rename it to something milder.
DEVELOPMENT_SECTION = "DEVELOPMENT_REGRESSION"

#: Attention levels that tell a reader there is nothing to worry about. Used
#: only together with a coverage status that is not FULL - the pair is what
#: makes it false reassurance rather than a legitimate low-risk finding.
_REASSURING = ("LOW", "NO_ACTIVE_ATTENTION")


def reassuring_levels() -> Tuple[str, ...]:
    return _REASSURING


class SeparationNotCleanError(BenchmarkError):
    """The case set failed its separation audit, so no metric was computed."""

    def __init__(self, audit: SeparationAudit) -> None:
        self.audit = audit
        super().__init__(
            "the development/holdout separation audit reported %d issue(s): "
            "%s. No metric was computed. A metric over a case set whose roles "
            "may have leaked measures memory rather than generalisation, and "
            "no later analysis undoes that."
            % (len(audit.issues), ", ".join(audit.issue_codes)))


def verify_observation(observation: BenchmarkObservation,
                       plan: BenchmarkPlan) -> None:
    """Raise unless this observation was produced under the pinned release."""
    expected = plan.pinned_release.identity()
    observed = observation.identity()
    for field_name in sorted(expected):
        if expected[field_name] != observed[field_name]:
            raise PinMismatchError(field_name, expected[field_name],
                                   observed[field_name],
                                   case_id=observation.case_id)
    pinned_manifest = plan.case_manifest_hashes.get(observation.role.value)
    if pinned_manifest is None:
        raise PinMismatchError("case_manifest_hashes[%s]"
                               % observation.role.value,
                               "<not pinned>", observation.case_manifest_hash,
                               case_id=observation.case_id)
    if pinned_manifest != observation.case_manifest_hash:
        raise PinMismatchError("case_manifest_hash", pinned_manifest,
                               observation.case_manifest_hash,
                               case_id=observation.case_id)


class _NoJudgments(ReferenceJudgmentPort):
    """The truthful default: nobody has supplied an answer key.

    Returning an empty mapping rather than raising, because "no judgments
    exist" is a real state the metrics know how to report. Raising would turn
    an expected condition into an error and tempt a caller to catch it.
    """

    def judgments(self, *, role: ValidationCaseRole
                  ) -> Mapping[str, ReferenceJudgment]:
        return {}


class BenchmarkEngine:
    """Compute metrics for one run. Holds no state between runs."""

    def __init__(self, *,
                 observation_port: Optional[RestrictedObservationPort] = None,
                 judgment_port: Optional[ReferenceJudgmentPort] = None,
                 decision_port: Optional[Any] = None,
                 clock: Optional[Any] = None) -> None:
        self._observations = observation_port
        self._judgments = judgment_port or _NoJudgments()
        # WP-22's expert-decision source. Absent by default and absent in this
        # repository, which is why PGX-VAL-011 and PGX-VAL-012 report
        # NO_COMPLETED_EXPERT_REVIEWS rather than a distribution.
        self._decisions = decision_port
        self._clock = clock or (lambda: _dt.datetime.now(_dt.timezone.utc))

    # -- execution -------------------------------------------------------

    def execute(self, plan: BenchmarkPlan, *, cases: Sequence[Any] = (),
                previous_roles: Optional[Mapping[str, str]] = None
                ) -> BenchmarkRun:
        """Run the plan. Refuses before observing anything if the audit is bad.

        ``cases`` are ``ValidationCaseMetadata`` values. They are audited, not
        executed: execution happens through the observation port, because the
        payloads live in restricted storage this process may not read.
        """
        audit = audit_partition(list(cases), previous_roles=previous_roles)
        if not audit.is_clean:
            raise SeparationNotCleanError(audit)
        if self._observations is None:
            raise BenchmarkError(
                "no observation port is wired, so no case can be executed. "
                "This is the repository's real state and the caller should "
                "report NOT_EXECUTED rather than construct an empty run and "
                "call it a result.")

        started = self._clock()
        collected: List[BenchmarkObservation] = []
        for role in plan.roles:
            for observation in self._observations.observe(role=role,
                                                          plan=plan):
                if observation.role is not role:
                    raise PinMismatchError(
                        "role", role.value, observation.role.value,
                        case_id=observation.case_id)
                verify_observation(observation, plan)
                collected.append(observation)
        finished = self._clock()
        return BenchmarkRun(plan=plan, observations=tuple(collected),
                            started_at=started, finished_at=finished,
                            separation_audit=audit.to_json())

    # -- metric computation ----------------------------------------------

    def compute(self, run: BenchmarkRun) -> Dict[str, List[MetricValue]]:
        """Every declared metric, per role. Never across roles.

        Returns ``{role_value: [MetricValue, ...]}``. A role the plan named but
        that produced no observation still appears, holding unavailable
        values - an absent row on a dashboard reads as "not applicable", and
        what is true is "we planned to measure this and found nothing".
        """
        registry = definitions_by_id()
        results: Dict[str, List[MetricValue]] = {}
        for role in run.plan.roles:
            observations = run.for_role(role)
            judgments = dict(self._judgments.judgments(role=role))
            values: List[MetricValue] = []
            for metric_id in run.plan.declared_metric_ids:
                definition = registry.get(metric_id)
                if definition is None:
                    raise BenchmarkError(
                        "plan declares unknown metric %r" % metric_id)
                values.append(self._one(definition, role, observations,
                                        judgments, run.plan))
            results[role.value] = values
        return results

    def _one(self, definition: MetricDefinition, role: ValidationCaseRole,
             observations: Sequence[BenchmarkObservation],
             judgments: Mapping[str, ReferenceJudgment],
             plan: BenchmarkPlan) -> MetricValue:
        role_name = role.value
        if not definition.accepts(role):
            # Not an error and not a zero: this metric was never defined over
            # this role. Reported so the table shows why the cell is empty.
            return unavailable(definition, role_name,
                               UnavailableReason.INPUT_INCOMPATIBLE
                               if UnavailableReason.INPUT_INCOMPATIBLE
                               in definition.unavailable_when
                               else UnavailableReason.NO_ELIGIBLE_OBSERVATIONS,
                               detail="%s is not an eligible role for this "
                                      "metric" % role_name)
        if not observations:
            return unavailable(definition, role_name,
                               UnavailableReason.NO_ELIGIBLE_OBSERVATIONS,
                               denominator=0,
                               detail="the run produced no observation for "
                                      "this role")
        if definition.requires_expert_review and self._decisions is None:
            # WP-22 built the protocol; this repository has completed no
            # review under it. Those are different statements and the reason
            # code says which one applies.
            return unavailable(
                definition, role_name,
                UnavailableReason.NO_COMPLETED_EXPERT_REVIEWS,
                detail="the blind expert review module is implemented and no "
                       "completed review has been supplied for this role")

        handler = getattr(self, "_m_%s" % definition.metric_id.replace("-", "_")
                          .lower(), None)
        if handler is None:  # pragma: no cover - registry/engine drift
            raise BenchmarkError("no handler for %s" % definition.metric_id)
        return handler(definition, role_name, observations, judgments, plan)

    # -- individual metrics ----------------------------------------------
    #
    # Each takes the same arguments so the dispatch above stays a lookup
    # rather than a chain of conditionals that could grow a special case.

    @staticmethod
    def _judged(observations: Sequence[BenchmarkObservation],
                judgments: Mapping[str, ReferenceJudgment]
                ) -> List[Tuple[BenchmarkObservation, ReferenceJudgment]]:
        return [(item, judgments[item.case_id]) for item in observations
                if item.case_id in judgments]

    def _m_pgx_val_001(self, definition, role, observations, judgments, plan):
        pairs = self._judged(observations, judgments)
        if not judgments:
            return unavailable(definition, role,
                               UnavailableReason.NO_REFERENCE_JUDGMENT,
                               detail="no reference judgment has been "
                                      "supplied for this role")
        matched = sum(
            1 for observation, judgment in pairs
            if observation.attention_level == judgment.expected_attention_level
            and observation.coverage_status == judgment.expected_coverage_status
            and (judgment.expected_rule_id is None
                 or observation.firing_rule_id == judgment.expected_rule_id))
        return measured_rate(definition, role, numerator=matched,
                             denominator=len(pairs),
                             detail="judged observations only")

    def _m_pgx_val_002(self, definition, role, observations, judgments, plan):
        pairs = self._judged(observations, judgments)
        if not judgments:
            return unavailable(definition, role,
                               UnavailableReason.NO_REFERENCE_JUDGMENT,
                               detail="no reference judgment has been "
                                      "supplied for this role")
        matched = sum(
            1 for observation, judgment in pairs
            if observation.coverage_status == judgment.expected_coverage_status
            and (judgment.expected_coverage_reason is None
                 or observation.coverage_reason
                 == judgment.expected_coverage_reason))
        return measured_rate(definition, role, numerator=matched,
                             denominator=len(pairs))

    @staticmethod
    def _false_reassurance(observations: Sequence[BenchmarkObservation]) -> int:
        return sum(1 for item in observations
                   if item.attention_level in _REASSURING
                   and item.coverage_status not in (None, "FULL"))

    def _m_pgx_val_003(self, definition, role, observations, judgments, plan):
        return measured_count(
            definition, role,
            numerator=self._false_reassurance(observations),
            denominator=len(observations),
            detail="counted from this run's observations; unrelated to WP-20 "
                   "detector controls")

    def _m_pgx_val_004(self, definition, role, observations, judgments, plan):
        return measured_rate(definition, role,
                             numerator=self._false_reassurance(observations),
                             denominator=len(observations))

    @staticmethod
    def _findings(observations: Sequence[BenchmarkObservation]
                  ) -> Tuple[int, int]:
        total = sum(item.finding_count for item in observations)
        traceable = sum(item.traceable_finding_count for item in observations)
        return traceable, total

    def _m_pgx_val_005(self, definition, role, observations, judgments, plan):
        traceable, total = self._findings(observations)
        if total == 0:
            # A count whose denominator is zero is still not a count of zero
            # traceable findings - there were no findings to trace.
            return unavailable(definition, role,
                               UnavailableReason.NO_ELIGIBLE_OBSERVATIONS,
                               numerator=0, denominator=0,
                               detail="no finding was emitted in this run")
        return measured_count(definition, role, numerator=traceable,
                              denominator=total,
                              detail="denominator is emitted findings, not "
                                     "cases")

    def _m_pgx_val_006(self, definition, role, observations, judgments, plan):
        traceable, total = self._findings(observations)
        return measured_rate(definition, role, numerator=traceable,
                             denominator=total)

    @staticmethod
    def _repeated(observations: Sequence[BenchmarkObservation]
                  ) -> Tuple[int, int]:
        eligible = [item for item in observations
                    if item.repeats_agree is not None]
        return sum(1 for item in eligible if item.repeats_agree), len(eligible)

    def _m_pgx_val_007(self, definition, role, observations, judgments, plan):
        agreed, eligible = self._repeated(observations)
        if eligible == 0:
            return unavailable(definition, role,
                               UnavailableReason.INPUT_INCOMPATIBLE,
                               numerator=0, denominator=0,
                               detail="the plan declared %d repeat(s); "
                                      "repeatability needs at least two"
                                      % plan.repeat_count)
        return measured_count(definition, role, numerator=agreed,
                              denominator=eligible)

    def _m_pgx_val_008(self, definition, role, observations, judgments, plan):
        agreed, eligible = self._repeated(observations)
        if eligible == 0:
            return unavailable(definition, role,
                               UnavailableReason.INPUT_INCOMPATIBLE,
                               numerator=0, denominator=0,
                               detail="fewer than two repeats were executed")
        return measured_rate(definition, role, numerator=agreed,
                             denominator=eligible)

    def _holdout_pass(self, observations, judgments) -> Tuple[int, int]:
        pairs = self._judged(observations, judgments)
        passed = 0
        for observation, judgment in pairs:
            if observation.attention_level != judgment.expected_attention_level:
                continue
            if observation.coverage_status != judgment.expected_coverage_status:
                continue
            if judgment.requires_evidence and (
                    observation.finding_count == 0
                    or observation.traceable_finding_count
                    != observation.finding_count):
                continue
            passed += 1
        return passed, len(pairs)

    def _m_pgx_val_009(self, definition, role, observations, judgments, plan):
        if not judgments:
            return unavailable(definition, role,
                               UnavailableReason.NO_REFERENCE_JUDGMENT,
                               detail="no reference judgment for this role")
        passed, judged = self._holdout_pass(observations, judgments)
        return measured_count(definition, role, numerator=passed,
                              denominator=judged)

    def _m_pgx_val_010(self, definition, role, observations, judgments, plan):
        if not judgments:
            return unavailable(definition, role,
                               UnavailableReason.NO_REFERENCE_JUDGMENT,
                               detail="no reference judgment for this role")
        passed, judged = self._holdout_pass(observations, judgments)
        return measured_rate(definition, role, numerator=passed,
                             denominator=judged)

    def _m_pgx_val_011(self, definition, role, observations, judgments, plan):
        """Agreement distribution, from completed WP-22 reviews only.

        The denominator is completed decisions, not observations. A case that
        ran but that nobody reviewed is not a case an expert declined to
        agree with - it is a case with no expert opinion, and counting it
        would put silence in the DISAGREE column by arithmetic.
        """
        decisions = dict(self._decisions.decisions(role=role))
        eligible = {case_id: value for case_id, value in decisions.items()
                    if case_id in {item.case_id for item in observations}}
        if not eligible:
            return unavailable(definition, role,
                               UnavailableReason.NO_COMPLETED_EXPERT_REVIEWS,
                               denominator=0,
                               detail="no completed expert review matches an "
                                      "observation in this run")
        counts = {name: 0 for name in definition.categories}
        for value in eligible.values():
            if value not in counts:
                raise BenchmarkError(
                    "an expert decision outside the governed vocabulary "
                    "reached a metric: %r" % value)
            counts[value] += 1
        return distribution(definition, role, counts=counts,
                            denominator=len(eligible),
                            detail="one decision per completed review")

    def _m_pgx_val_012(self, definition, role, observations, judgments, plan):
        """Likert distribution, per rating rather than per review.

        Ratings are optional, so the denominator counts *completed ratings*.
        Using completed reviews instead would silently treat every unrated
        review as a missing low score.
        """
        ratings = self._decisions.ratings(role=role)
        observed = {item.case_id for item in observations}
        values = [value for case_id, dimensions in ratings.items()
                  if case_id in observed
                  for value in dimensions.values()]
        if not values:
            return unavailable(definition, role,
                               UnavailableReason.NO_COMPLETED_EXPERT_REVIEWS,
                               denominator=0,
                               detail="no completed Likert rating matches an "
                                      "observation in this run")
        counts = {name: 0 for name in definition.categories}
        for value in values:
            key = str(int(value))
            if key not in counts:
                raise BenchmarkError(
                    "a Likert value outside the declared points reached a "
                    "metric: %r" % value)
            counts[key] += 1
        return distribution(definition, role, counts=counts,
                            denominator=len(values),
                            detail="denominator is completed ratings, not "
                                   "completed reviews")

    def _m_pgx_val_013(self, definition, role, observations, judgments, plan):
        return measured_count(
            definition, role,
            numerator=sum(1 for item in observations
                          if item.unresolved_conflict),
            denominator=len(observations))

    @staticmethod
    def _paths_covered(observations: Sequence[BenchmarkObservation]) -> int:
        seen = set()
        for item in observations:
            seen.update(item.failure_paths)
        return len(seen)

    def _m_pgx_val_014(self, definition, role, observations, judgments, plan):
        return measured_count(definition, role,
                              numerator=self._paths_covered(observations),
                              denominator=len(FAILURE_PATH_CATALOGUE),
                              detail="denominator is the predeclared "
                                     "catalogue, not the paths that ran")

    def _m_pgx_val_015(self, definition, role, observations, judgments, plan):
        return measured_rate(definition, role,
                             numerator=self._paths_covered(observations),
                             denominator=len(FAILURE_PATH_CATALOGUE))

    # -- the honest empty result ------------------------------------------

    @staticmethod
    def not_executed_values(roles: Sequence[ValidationCaseRole],
                            metric_ids: Sequence[str], *, detail: str = ""
                            ) -> Dict[str, List[MetricValue]]:
        """Every declared metric as ``NOT_EXECUTED``, per role.

        What this repository actually produces. Separate from :meth:`compute`
        so there is no code path that turns an empty observation list into a
        table of zeros - the two states are built by different functions and
        neither can be mistaken for the other.
        """
        registry = definitions_by_id()
        out: Dict[str, List[MetricValue]] = {}
        for role in roles:
            out[role.value] = [
                not_executed(registry[metric_id], role.value, detail=detail)
                for metric_id in metric_ids]
        return out

    @staticmethod
    def blocked_values(roles: Sequence[ValidationCaseRole],
                       metric_ids: Sequence[str],
                       reason: UnavailableReason, *, detail: str = ""
                       ) -> Dict[str, List[MetricValue]]:
        """Every declared metric as ``BLOCKED`` for one named precondition."""
        registry = definitions_by_id()
        out: Dict[str, List[MetricValue]] = {}
        for role in roles:
            values = []
            for metric_id in metric_ids:
                definition = registry[metric_id]
                if reason in definition.unavailable_when:
                    values.append(blocked(definition, role.value, reason,
                                          detail=detail))
                else:
                    values.append(not_executed(definition, role.value,
                                               detail=detail))
            out[role.value] = values
        return out
