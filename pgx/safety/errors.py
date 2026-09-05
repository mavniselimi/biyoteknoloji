# -*- coding: utf-8 -*-
"""Failures raised by the WP-20 safety gate.

These describe faults in the *gate*, not unsafe behaviour in the software. An
invariant that is violated is a **result** - it travels as a `ComplianceState`
and blocks the release. An exception here means the gate itself could not
produce a trustworthy answer: the registry disagreed with itself, a selector
matched nothing, a negative control was missing.

The distinction is the whole point. A gate that crashed and a gate that found
nothing wrong must never look the same to a caller, because one of them has
verified nothing.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

__all__ = [
    "SafetyError",
    "RegistryError",
    "InvariantNotRegistered",
    "DuplicateInvariant",
    "UnknownInvariant",
    "SelectorError",
    "NegativeControlMissing",
    "NegativeControlNotDetected",
    "EvidenceError",
    "StaleEvidence",
    "GateRefusal",
]


class SafetyError(Exception):
    """Base class for every fault in the WP-20 safety gate."""


class RegistryError(SafetyError):
    """The invariant registry is internally inconsistent.

    Carries every problem at once. A registry with three faults should be read
    once by a person, not three times by a build.
    """

    def __init__(self, message: str,
                 issues: Optional[Iterable[str]] = None) -> None:
        self.issues: Sequence[str] = tuple(issues or ())
        if self.issues:
            message = "%s: %s" % (message, "; ".join(self.issues))
        super().__init__(message)


class InvariantNotRegistered(RegistryError):
    """A required SAFETY-INV identifier is absent from the registry.

    Fails closed. The alternative - carrying on with eleven invariants because
    the twelfth was deleted - is how a safety requirement quietly stops being
    one.
    """


class DuplicateInvariant(RegistryError):
    """One identifier appears twice, so a result cannot be attributed."""


class UnknownInvariant(RegistryError):
    """An identifier outside SAFETY-INV-001..012 appeared.

    Refused rather than accepted: a thirteenth invariant is a change to the
    safety contract, and the contract is a reviewed document.
    """


class SelectorError(RegistryError):
    """An invariant's test selector matches no test that exists.

    The registry would otherwise keep a row that reads convincingly while the
    tests behind it were renamed or deleted.
    """


class NegativeControlMissing(RegistryError):
    """An invariant has no unsafe fixture, so its detector is unproven.

    A detector nobody has shown to reject anything is a detector nobody has
    shown to work.
    """


class NegativeControlNotDetected(SafetyError):
    """A detector accepted the unsafe case it exists to reject.

    The most serious fault this package can report. The invariant looks
    enforced, the suite is green, and the check is inert.
    """

    def __init__(self, invariant_id: str, control_id: str,
                 detail: str = "") -> None:
        self.invariant_id = invariant_id
        self.control_id = control_id
        super().__init__(
            "%s: negative control %s was NOT detected%s"
            % (invariant_id, control_id, (": " + detail) if detail else ""))


class EvidenceError(SafetyError):
    """Safety execution evidence could not be read or written."""


class StaleEvidence(EvidenceError):
    """Evidence exists but is no longer about this code.

    Never silently refreshed. Stale evidence is reported as ``STALE`` and
    blocks the release until somebody runs the gate again.
    """


class GateRefusal(SafetyError):
    """The gate refused to write or report something it cannot stand behind.

    Raised when a caller asks for a PASS that the observations do not support -
    zero tests executed, a missing control, an incomplete run.
    """
