# -*- coding: utf-8 -*-
"""Failure types for the rule and ruleset layer (WP-11).

Every type carries the structured detail a caller needs to act, rather than
only prose. A CLI branching on "which gate is shut" or "which member is
missing" must not have to parse a sentence.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence, Tuple

__all__ = [
    "ArtifactIntegrityError",
    "ConditionGrammarError",
    "ConflictDetectedError",
    "FrozenArtifactExistsError",
    "RuleError",
    "RuleImmutabilityError",
    "RuleLifecycleError",
    "RuleProvenanceError",
    "RuleValidationError",
    "RulesetLifecycleError",
    "RulesetMembershipError",
    "RegistryLoadError",
]


class RuleError(Exception):
    """Base class for every rule-layer failure."""


class ConditionGrammarError(RuleError):
    """A condition is not expressible in the WP-11 grammar.

    Raised for a wildcard, a regex, a negation, an expression, an unknown key,
    an unknown entity, or anything else the small declarative language does not
    have. The grammar is small on purpose: it is the set of conditions a
    reviewer can check by reading.
    """

    def __init__(self, message: str, *, code: str = "RULE_COND_INVALID",
                 location: str = "$") -> None:
        super().__init__(message)
        self.code = code
        self.location = location


class RuleValidationError(RuleError):
    """One or more validation issues prevented an operation.

    Carries the whole issue list rather than the first failure: an author
    fixing a rule one round-trip per problem is an author who gives up.
    """

    def __init__(self, message: str,
                 issues: Sequence[Any] = ()) -> None:
        super().__init__(message)
        self.issues = tuple(issues)

    @property
    def codes(self) -> Tuple[str, ...]:
        return tuple(sorted({getattr(issue, "code", "") for issue in self.issues}
                            - {""}))


class RuleLifecycleError(RuleError):
    """A rule transition the lifecycle does not have."""

    def __init__(self, message: str, *, current: Optional[str] = None,
                 requested: Optional[str] = None) -> None:
        super().__init__(message)
        self.current = current
        self.requested = requested


class RuleImmutabilityError(RuleError):
    """An attempt to change content that is fixed after validation."""


class RuleProvenanceError(RuleError):
    """A rule's provenance does not resolve, or does not match what it pins."""

    def __init__(self, message: str, *, code: str = "RULE_PROV_UNRESOLVED",
                 expected: Optional[str] = None,
                 actual: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code
        self.expected = expected
        self.actual = actual


class ConflictDetectedError(RuleError):
    """Rules disagree in a way nothing here is allowed to resolve.

    There is no priority, no ordering and no "most severe wins". Two validated
    rules producing different attention levels for one canonical axis is a
    scientific disagreement, and the only correct behaviour is to refuse the
    ruleset and hand it back to people.
    """

    def __init__(self, message: str, findings: Sequence[Any] = ()) -> None:
        super().__init__(message)
        self.findings = tuple(findings)

    @property
    def codes(self) -> Tuple[str, ...]:
        return tuple(sorted({getattr(item, "kind", "") for item in self.findings}
                            - {""}))


class RulesetLifecycleError(RuleError):
    """A ruleset transition the lifecycle does not have."""

    def __init__(self, message: str, *, current: Optional[str] = None,
                 requested: Optional[str] = None) -> None:
        super().__init__(message)
        self.current = current
        self.requested = requested


class RulesetMembershipError(RuleError):
    """A membership change that is refused."""


class ArtifactIntegrityError(RuleError):
    """A built artifact does not verify.

    Raised for a checksum mismatch, a missing member, an altered rule, an
    altered approval list, or a manifest that does not describe what is on
    disk. Loading fails closed: a partially verified ruleset is not a ruleset.
    """

    def __init__(self, message: str, *, code: str = "ARTIFACT_CHECKSUM_MISMATCH",
                 detail: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.detail = dict(detail or {})


class FrozenArtifactExistsError(RuleError):
    """A build would overwrite an artifact that is already frozen.

    A frozen ruleset is never rewritten. A correction is a new build under a
    new identity, so anything that cited the old hash still resolves to what it
    cited.
    """


class RegistryLoadError(RuleError):
    """The engine-facing registry refused to expose something."""

    def __init__(self, message: str, *, code: str = "REGISTRY_NOT_FROZEN") -> None:
        super().__init__(message)
        self.code = code
