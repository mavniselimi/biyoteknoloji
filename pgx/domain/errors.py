# -*- coding: utf-8 -*-
"""Domain errors (WP-02).

Standard library only. These errors express *domain rule* violations and are
deliberately distinct from infrastructure failures: a repository must not raise
a domain error for a connection problem, and the domain must never raise a
SQLAlchemy error.
"""

from __future__ import annotations

__all__ = [
    "DomainError",
    "InvalidIdentifierError",
    "InvalidPublicIdentifierError",
    "IdentifierTypeMismatchError",
    "InvalidTemporalValueError",
    "DomainInvariantError",
    "TraceabilityError",
    "LifecycleError",
    "ModeNotPermittedError",
    "CanonicalizationError",
    "RepositoryTypeError",
]


class DomainError(Exception):
    """Base class for every domain rule violation."""


class InvalidIdentifierError(DomainError, ValueError):
    """A value cannot be interpreted as the requested identifier."""


class InvalidPublicIdentifierError(InvalidIdentifierError):
    """A human-readable public identifier does not match its required format."""


class IdentifierTypeMismatchError(DomainError, TypeError):
    """An identifier of the wrong entity type was supplied.

    Passing a ``DrugId`` where a ``GeneId`` is required is a programming error
    that must fail loudly rather than silently address the wrong row.
    """


class InvalidTemporalValueError(DomainError, ValueError):
    """A datetime is missing, naive, or otherwise unusable.

    Every stored instant must be timezone-aware and expressed in UTC, so that
    hashes and audit records are comparable across environments.
    """


class DomainInvariantError(DomainError, ValueError):
    """A domain object would violate one of its own invariants."""


class TraceabilityError(DomainInvariantError):
    """A calculated object lacks the evidence or rule references it requires.

    Backs ``SAFETY-INV-006``: a finding without traceable evidence must never
    exist, not even transiently.
    """


class LifecycleError(DomainInvariantError):
    """A lifecycle state is missing the metadata that state requires.

    Backs ``SAFETY-INV-003``: only fully approved rules may reach ``VALIDATED``.
    """


class ModeNotPermittedError(DomainInvariantError):
    """Raised when a domain object is created in a disabled operation mode.

    Backs the WP-00 claim boundary: ``PILOT`` is not enabled in P0, so an
    assessment in that mode must fail loudly rather than exist unremarked
    (``architecture.md`` section 2.3).
    """


class CanonicalizationError(DomainError, ValueError):
    """A value cannot be canonicalised deterministically for hashing."""


class RepositoryTypeError(DomainError, TypeError):
    """A repository was handed an object of a type it does not own.

    Backs the Evidence -> Interpretation -> Rule -> Assessment boundary: an
    evidence repository must refuse an assessment rather than storing it.
    """
