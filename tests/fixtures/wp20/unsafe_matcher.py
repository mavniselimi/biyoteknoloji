# -*- coding: utf-8 -*-
"""SAFETY-INV-004 negative controls: phenotype matchers that over-match.

``LEGACY-BUG-001``: the legacy matcher let RAPID and ULTRARAPID match each
other, silently applying a rule outside the evidence that supports it. Implicit
equivalence between two phenotypes is an unreviewed scientific claim, and it is
the kind that reaches a person.
"""

from __future__ import annotations

from typing import Any, Sequence

from pgx.domain.enums import Phenotype


def safe_matcher(observed: Any, declared: Sequence[Any]) -> bool:
    """The safe control: exact membership, nothing else."""
    return observed in tuple(declared)


def prefix_matcher(observed: Any, declared: Sequence[Any]) -> bool:
    """NC-INV-004-PREFIX-MATCHER - the actual legacy shape.

    ``"RAPID"`` is a suffix of ``"ULTRARAPID"``, so a substring test written to
    be "tolerant of formatting" makes the two interchangeable in one
    direction - and asymmetry is why a one-way test would miss it.
    """
    name = getattr(observed, "value", str(observed))
    for candidate in declared:
        other = getattr(candidate, "value", str(candidate))
        if name in other or other in name:
            return True
    return False


def synonym_matcher(observed: Any, declared: Sequence[Any]) -> bool:
    """NC-INV-004-SYNONYM-TABLE - an explicit equivalence nobody approved.

    A table like this usually appears to "handle vendor naming". It encodes a
    pharmacological claim that RAPID and ULTRARAPID metabolisers may be treated
    alike, which no curator reviewed.
    """
    synonyms = {"RAPID": {"RAPID", "ULTRARAPID"},
                "ULTRARAPID": {"ULTRARAPID", "RAPID"}}
    name = getattr(observed, "value", str(observed))
    group = synonyms.get(name, {name})
    return any(getattr(c, "value", str(c)) in group for c in declared)


def ordinal_matcher(observed: Any, declared: Sequence[Any]) -> bool:
    """NC-INV-004-ORDINAL-PROXIMITY - "close enough on the scale".

    Treats the phenotype model as an ordered axis and accepts a neighbour. The
    model is a vocabulary, not a magnitude; adjacency in a list is not
    biological similarity.
    """
    order = [p.value for p in Phenotype]
    name = getattr(observed, "value", str(observed))
    if name not in order:
        return False
    index = order.index(name)
    for candidate in declared:
        other = getattr(candidate, "value", str(candidate))
        if other in order and abs(order.index(other) - index) <= 1:
            return True
    return False


UNSAFE_SUBJECTS = {
    "NC-INV-004-PREFIX-MATCHER": prefix_matcher,
    "NC-INV-004-SYNONYM-TABLE": synonym_matcher,
    "NC-INV-004-ORDINAL-PROXIMITY": ordinal_matcher,
}

SAFE_SUBJECT = safe_matcher
