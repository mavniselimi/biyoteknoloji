# -*- coding: utf-8 -*-
"""Failure types for the phenotype engine (WP-12).

Every type carries a stable machine-readable ``code`` alongside its message.
A caller branching on "which kind of bad input was this" must not have to
parse a sentence, and the difference between a missing phenotype and an
uninterpretable one is exactly the difference a downstream coverage engine
will need to report honestly.

There is deliberately no generic "phenotype error": the whole point of this
layer is that its failures stay distinguishable.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

__all__ = [
    "PhenotypeEngineError",
    "PhenotypeInputError",
    "PhenotypeProfileError",
    "PhenotypeMatchError",
]


class PhenotypeEngineError(Exception):
    """Base class for every phenotype-engine failure."""

    def __init__(self, message: str, *, code: str = "PHENOTYPE_ERROR",
                 location: str = "$",
                 detail: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.location = location
        self.detail = dict(detail or {})


class PhenotypeInputError(PhenotypeEngineError):
    """A value was offered where a phenotype token belongs and could not be
    interpreted as one.

    Raised only where a caller asked for a value or nothing - the normalizer
    itself does not raise, because "this input is unsupported" is a *result*
    that a caller must be able to record, not an exception it may swallow.
    """


class PhenotypeProfileError(PhenotypeEngineError):
    """A phenotype profile could not be constructed as stated.

    Duplicate genes, conflicting values for one canonical gene, a gene outside
    a pinned catalogue, or a catalogue that was requested and is empty. Each
    is a refusal rather than a repair: silently picking one of two conflicting
    values for a gene would be inventing an observation.
    """


class PhenotypeMatchError(PhenotypeEngineError):
    """The matcher was asked to compare something it does not compare.

    Not a mismatch - a mismatch is an ordinary ``NO_MATCH`` result. This is
    the caller passing a condition type the engine will not interpret, such as
    a raw dictionary that never went through WP-11's parser.
    """
