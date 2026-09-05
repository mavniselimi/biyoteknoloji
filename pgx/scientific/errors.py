# -*- coding: utf-8 -*-
"""Typed source-governance failures (WP-05).

Standard library only.

The split is functional, not decorative. Each class marks a different *kind*
of wrongness, and the caller reacts differently to each:

* :class:`SourcePolicyConfigError` - the registry file could not be loaded or
  parsed at all. Nothing downstream may run, because there is no policy to
  apply and "no policy" must never read as "no restrictions".
* :class:`SourcePolicyValidationError` - the file loaded but a record is
  structurally wrong. Raised only where a caller asked for a strict load;
  validation normally *reports* rather than raises, so an operator sees the
  whole list.
* :class:`UnknownSourceError` - something referenced a source key the registry
  does not carry. This is fail-closed: an unregistered source is not an
  unrestricted one.
* :class:`ReviewIntegrityError` - a review record claims an approval it cannot
  support (no reviewer, no timestamp, no evidence). Forging approval is the
  one failure this package exists to prevent, so it raises rather than
  degrading to a warning.
* :class:`ConflictRegistryError` - a conflict record is malformed or
  contradicts itself.
* :class:`LegacyInventoryError` - the legacy scan could not read its inputs.

Nothing here inherits from the domain error tree: source governance is a
project-process concern, not a pharmacogenetic domain rule, and conflating the
two would let a policy failure be caught by a handler written for domain
invariants.
"""

from __future__ import annotations

from typing import Optional

__all__ = [
    "ConflictRegistryError",
    "LegacyInventoryError",
    "ReviewIntegrityError",
    "ScientificGovernanceError",
    "SourcePolicyConfigError",
    "SourcePolicyValidationError",
    "UnknownSourceError",
]


class ScientificGovernanceError(Exception):
    """Base class for every source-governance failure."""


class SourcePolicyConfigError(ScientificGovernanceError):
    """The source registry file is missing, unreadable or not valid JSON.

    Never downgraded to an empty registry. A caller that treated an unreadable
    policy file as "no sources are restricted" would invert the whole point of
    the file.
    """


class SourcePolicyValidationError(ScientificGovernanceError):
    """A source policy record is structurally invalid.

    Carries the stable issue codes so a caller can react to a class of problem
    rather than to prose.
    """

    def __init__(self, message: str, codes: tuple = ()) -> None:
        super().__init__(message)
        self.codes = tuple(codes)


class UnknownSourceError(ScientificGovernanceError):
    """A source key is not present in the registry.

    Fail-closed by construction: the answer to "may this source be used?" for
    an unknown source is no, and the caller must be told which key was missing
    rather than handed a default.
    """

    def __init__(self, source_key: str, detail: Optional[str] = None) -> None:
        text = "source %r is not registered" % source_key
        if detail:
            text = "%s: %s" % (text, detail)
        super().__init__(text)
        self.source_key = source_key


class ReviewIntegrityError(ScientificGovernanceError):
    """A review record does not support the decision it claims.

    An approval without a named reviewer, a decision timestamp and at least one
    official evidence reference is not an approval. This raises rather than
    reporting, because a half-formed approval that survives into a report has
    already done its damage.
    """


class ConflictRegistryError(ScientificGovernanceError):
    """A source-conflict record is malformed or self-contradictory."""


class LegacyInventoryError(ScientificGovernanceError):
    """The legacy source inventory could not read or interpret its inputs.

    Raised rather than skipping the unreadable file: an inventory that silently
    omits an input is worse than no inventory, because it looks complete.
    """
