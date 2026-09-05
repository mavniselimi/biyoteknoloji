# -*- coding: utf-8 -*-
"""Metric values (WP-21): how a number is carried, and how nothing is.

One class, :class:`MetricValue`, and it exists because the interesting cases
are the ones with no number in them.

A rate that came back with a zero denominator, a rate whose benchmark never
ran, and a rate that ran and measured exactly zero are three different facts.
Every serialisation format that represents all three as ``0`` - or worse, as
``0%`` on a dashboard - has destroyed the difference at the point where it
matters most, because a reader who sees ``0% unsafe reassurance`` will believe
the system was tested and found safe.

So the rules here are:

- ``value`` is ``None`` unless a real measurement produced it. Never ``0`` and
  never ``100`` as a stand-in.
- ``numerator`` and ``denominator`` are stored separately and always, so a
  reader can check the ratio rather than trust it.
- ``NOT_EXECUTED`` reports a null denominator, because nobody counted.
  ``UNAVAILABLE`` may report a real ``0`` denominator, because somebody
  counted and the answer was zero cases.
- Rates serialise as decimal *strings* through :mod:`decimal`, so the artifact
  bytes do not depend on a platform's float repr. Counts serialise as ints.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any, Dict, Mapping, Optional, Tuple

from pgx.validation.errors import ValidationDatasetError
from pgx.validation.metric_definitions import (MetricDefinition, MetricKind,
                                               MetricStatus,
                                               UnavailableReason)

__all__ = [
    "MetricError",
    "MetricValue",
    "blocked",
    "distribution",
    "format_rate",
    "measured_count",
    "measured_rate",
    "not_executed",
    "unavailable",
]


class MetricError(ValidationDatasetError):
    """A metric was constructed in a way that would misreport its own state."""


def format_rate(numerator: int, denominator: int, places: int = 4) -> str:
    """A rate as a fixed-point decimal string, or raise on a zero denominator.

    Decimal rather than float so the same inputs give the same bytes on every
    platform, and banker's rounding so a long run of exact halves does not
    drift upward. The caller must have checked the denominator; a zero here is
    a programming error rather than a value to represent, and returning
    ``"0.0000"`` for it is precisely the bug this module exists to prevent.
    """
    if denominator <= 0:
        raise MetricError(
            "format_rate was asked to divide by %d. A zero denominator has no "
            "rate; the caller must report UNAVAILABLE with ZERO_DENOMINATOR "
            "instead of formatting one." % denominator)
    if numerator < 0:
        raise MetricError("a metric numerator may not be negative")
    if numerator > denominator:
        raise MetricError(
            "numerator %d exceeds denominator %d; a rate above 1 means the "
            "two are counting different things" % (numerator, denominator))
    quantum = Decimal(1).scaleb(-places)
    ratio = (Decimal(numerator) / Decimal(denominator)).quantize(
        quantum, rounding=ROUND_HALF_EVEN)
    return str(ratio)


@dataclass(frozen=True, slots=True)
class MetricValue:
    """One metric's outcome for one partition of one benchmark run.

    ``role`` is part of the identity, not a label on it. The same metric
    computed over INTERNAL_HOLDOUT and over EXPERT_HOLDOUT produces two
    values, and there is deliberately no operation that merges them.
    """

    metric_id: str
    role: str
    status: MetricStatus
    kind: MetricKind
    numerator: Optional[int] = None
    denominator: Optional[int] = None
    #: Decimal string for a RATE, integer for a COUNT, ``None`` otherwise.
    value: Optional[str] = None
    reason: Optional[UnavailableReason] = None
    detail: str = ""
    categories: Mapping[str, int] = None  # type: ignore[assignment]
    is_validation_evidence: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "categories",
                           dict(self.categories or {}))
        if self.status is MetricStatus.AVAILABLE:
            if self.reason is not None:
                raise MetricError(
                    "%s is AVAILABLE and names an unavailable reason"
                    % self.metric_id)
            if self.kind is MetricKind.DISTRIBUTION:
                if not self.categories:
                    raise MetricError("%s is an available distribution with "
                                      "no categories" % self.metric_id)
            elif self.value is None:
                raise MetricError(
                    "%s is AVAILABLE with no value. An available metric is a "
                    "measurement; if there is nothing to report the status is "
                    "UNAVAILABLE." % self.metric_id)
            if self.denominator is None:
                raise MetricError(
                    "%s is AVAILABLE with no denominator. Every number here "
                    "is checkable against what it was counted over."
                    % self.metric_id)
            if self.kind is MetricKind.RATE and self.denominator == 0:
                raise MetricError(
                    "%s is an AVAILABLE rate over a zero denominator. That "
                    "combination is the false zero this class exists to make "
                    "unrepresentable." % self.metric_id)
        else:
            if self.value is not None:
                raise MetricError(
                    "%s is %s and carries a value" % (self.metric_id,
                                                      self.status.value))
            if self.reason is None:
                raise MetricError(
                    "%s is %s with no reason code. 'No value, no reason' is "
                    "indistinguishable from a bug." % (self.metric_id,
                                                       self.status.value))
        if self.status is MetricStatus.NOT_EXECUTED and \
                self.denominator is not None:
            raise MetricError(
                "%s is NOT_EXECUTED and reports a denominator. Nobody ran it, "
                "so nothing was counted - a denominator here would say we "
                "looked." % self.metric_id)
        if self.numerator is not None and self.numerator < 0:
            raise MetricError("%s has a negative numerator" % self.metric_id)
        if self.denominator is not None and self.denominator < 0:
            raise MetricError("%s has a negative denominator" % self.metric_id)

    @property
    def has_number(self) -> bool:
        return self.status is MetricStatus.AVAILABLE

    def to_json(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "metric_id": self.metric_id,
            "role": self.role,
            "status": self.status.value,
            "kind": self.kind.value,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "value": self.value,
            "unavailable_reason": (None if self.reason is None
                                   else self.reason.value),
            "detail": self.detail,
            "is_validation_evidence": self.is_validation_evidence,
        }
        if self.kind is MetricKind.DISTRIBUTION:
            payload["categories"] = {name: int(count) for name, count
                                     in sorted(self.categories.items())}
        return payload


def _evidence(definition: MetricDefinition, role: str) -> bool:
    """Whether this particular value counts as validation evidence.

    Both halves must hold: the metric must be an evidence metric *and* the
    role must be a holdout role. A determinism metric computed over
    DEVELOPMENT is a regression signal; the same metric over a holdout is
    still not evidence, because the definition says so.
    """
    return bool(definition.is_validation_evidence) and role != "DEVELOPMENT"


def measured_count(definition: MetricDefinition, role: str, *,
                   numerator: int, denominator: int,
                   detail: str = "") -> MetricValue:
    """A real count. Zero is a legitimate value here and is reported as one."""
    if definition.kind is not MetricKind.COUNT:
        raise MetricError("%s is not a count" % definition.metric_id)
    return MetricValue(
        metric_id=definition.metric_id, role=role,
        status=MetricStatus.AVAILABLE, kind=definition.kind,
        numerator=int(numerator), denominator=int(denominator),
        value=str(int(numerator)), detail=detail,
        is_validation_evidence=_evidence(definition, role))


def measured_rate(definition: MetricDefinition, role: str, *,
                  numerator: int, denominator: int,
                  detail: str = "") -> MetricValue:
    """A real rate, or ``UNAVAILABLE`` when the denominator is zero.

    The zero-denominator branch lives here rather than at each call site, so
    there is exactly one place in the system where "no cases" could have been
    turned into "0%", and it does not.
    """
    if definition.kind is not MetricKind.RATE:
        raise MetricError("%s is not a rate" % definition.metric_id)
    if denominator <= 0:
        return unavailable(definition, role,
                           UnavailableReason.ZERO_DENOMINATOR,
                           denominator=int(denominator),
                           numerator=int(numerator),
                           detail=detail or "denominator is zero")
    return MetricValue(
        metric_id=definition.metric_id, role=role,
        status=MetricStatus.AVAILABLE, kind=definition.kind,
        numerator=int(numerator), denominator=int(denominator),
        value=format_rate(int(numerator), int(denominator),
                          definition.decimal_places),
        detail=detail, is_validation_evidence=_evidence(definition, role))


def distribution(definition: MetricDefinition, role: str, *,
                 counts: Mapping[str, int], denominator: int,
                 detail: str = "") -> MetricValue:
    """A category distribution. Every declared category appears, even at zero.

    A missing category and a zero category read the same on a dashboard and
    mean different things, so the declared set is filled in rather than left
    to whatever the data happened to contain.
    """
    if definition.kind is not MetricKind.DISTRIBUTION:
        raise MetricError("%s is not a distribution" % definition.metric_id)
    unknown = sorted(set(counts) - set(definition.categories))
    if unknown:
        raise MetricError("%s received undeclared categories: %s"
                          % (definition.metric_id, ", ".join(unknown)))
    if denominator <= 0:
        return unavailable(definition, role,
                           UnavailableReason.ZERO_DENOMINATOR,
                           denominator=int(denominator), detail=detail)
    filled = {name: int(counts.get(name, 0))
              for name in definition.categories}
    total = sum(filled.values())
    if total != denominator:
        raise MetricError(
            "%s distribution sums to %d over a denominator of %d; a category "
            "is missing or double counted" % (definition.metric_id, total,
                                              denominator))
    return MetricValue(
        metric_id=definition.metric_id, role=role,
        status=MetricStatus.AVAILABLE, kind=definition.kind,
        numerator=total, denominator=int(denominator), value=None,
        categories=filled, detail=detail,
        is_validation_evidence=_evidence(definition, role))


def unavailable(definition: MetricDefinition, role: str,
                reason: UnavailableReason, *,
                numerator: Optional[int] = None,
                denominator: Optional[int] = None,
                detail: str = "") -> MetricValue:
    """No value, and the reason why - which the definition must have listed."""
    if reason not in definition.unavailable_when:
        raise MetricError(
            "%s reported %s, which its definition does not list as a way to "
            "be unavailable. Either the runner is wrong or the definition is "
            "incomplete; both need a person."
            % (definition.metric_id, reason.value))
    return MetricValue(
        metric_id=definition.metric_id, role=role,
        status=MetricStatus.UNAVAILABLE, kind=definition.kind,
        numerator=numerator, denominator=denominator, value=None,
        reason=reason, detail=detail,
        is_validation_evidence=_evidence(definition, role))


def not_executed(definition: MetricDefinition, role: str, *,
                 detail: str = "") -> MetricValue:
    """Nobody ran the benchmark. Distinct from running it and finding zero."""
    return MetricValue(
        metric_id=definition.metric_id, role=role,
        status=MetricStatus.NOT_EXECUTED, kind=definition.kind,
        numerator=None, denominator=None, value=None,
        reason=UnavailableReason.BENCHMARK_NOT_EXECUTED,
        detail=detail or "no benchmark run exists for this release",
        is_validation_evidence=_evidence(definition, role))


def blocked(definition: MetricDefinition, role: str,
            reason: UnavailableReason, *, detail: str = "") -> MetricValue:
    """A precondition failed, so the computation was refused, not attempted."""
    if reason not in definition.unavailable_when:
        raise MetricError(
            "%s was blocked for %s, which its definition does not list"
            % (definition.metric_id, reason.value))
    return MetricValue(
        metric_id=definition.metric_id, role=role,
        status=MetricStatus.BLOCKED, kind=definition.kind,
        numerator=None, denominator=None, value=None, reason=reason,
        detail=detail, is_validation_evidence=_evidence(definition, role))
