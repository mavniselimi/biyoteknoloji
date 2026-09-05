# -*- coding: utf-8 -*-
"""Telling a narrower view of a record from a contradictory one (WP-08).

Standard library only.

ClinPGx serves the same record at several ``view`` depths. The pair endpoint
returned ``{"id": 376523711}`` where the data endpoint returned
``{"id": 376523711, "phenotype": "cardiovascular events", ...}``. Those two
payloads are not equal, and treating that inequality as a conflict would block
1,644 perfectly consistent records; treating it as "close enough" would hide a
real disagreement the day one appears.

So the distinction is made structurally and is checkable:

* **projection** - every key present in the narrower payload is present in the
  wider one, and each corresponding value is itself a projection. Lists must
  have the same length and correspond element-wise. Nothing the narrower
  payload says is contradicted; it simply says less.
* **conflict** - any shared path where two scalars differ, or two lists differ
  in length. One of the two is wrong, and this module never decides which.

When several payloads are observed for one source identity, a **unique
maximal** payload - one that every other is a projection of - is the record's
payload, because keeping it discards nothing. If two payloads are incomparable,
or if any pair contradicts, the group is a conflict: both are kept, neither is
chosen, and the caller raises a blocking issue.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "PayloadRelation",
    "choose_maximal_payload",
    "describe_payload_difference",
    "is_projection_of",
]


class PayloadRelation(str, Enum):
    """How a set of payloads for one source identity relate."""

    #: One payload, seen once or many times.
    IDENTICAL = "IDENTICAL"
    #: Several payloads, one of which every other projects into.
    PROJECTION = "PROJECTION"
    #: Several payloads with no unique maximal element.
    INCOMPARABLE = "INCOMPARABLE"
    #: A shared path carries different values.
    CONFLICT = "CONFLICT"

    def __str__(self) -> str:
        return self.value

    @property
    def is_blocking(self) -> bool:
        """Whether this relation must stop the record reaching production.

        A projection is not blocking: the wider payload contains everything the
        narrower one said. Anything else means two payloads claim one identity
        and disagree, which no storage rule can reconcile.
        """
        return self in (PayloadRelation.INCOMPARABLE, PayloadRelation.CONFLICT)


def is_projection_of(narrow: Any, wide: Any) -> bool:
    """True when ``narrow`` says a subset of what ``wide`` says.

    Recursive by necessity. The difference between a view depth and a
    disagreement lives inside nested objects: ``{"id": 1}`` against
    ``{"id": 1, "term": "increased"}`` is a view, while ``{"term": "increased"}``
    against ``{"term": "decreased"}`` is a disagreement, and a shallow
    comparison cannot tell them apart.
    """
    if isinstance(narrow, Mapping) and isinstance(wide, Mapping):
        return all(key in wide and is_projection_of(value, wide[key])
                   for key, value in narrow.items())
    if isinstance(narrow, (list, tuple)) and isinstance(wide, (list, tuple)):
        # Same length, element-wise. A shorter list is not a narrower view of a
        # longer one: a missing element is missing content, not missing detail.
        return (len(narrow) == len(wide)
                and all(is_projection_of(left, right)
                        for left, right in zip(narrow, wide)))
    if isinstance(narrow, bool) != isinstance(wide, bool):
        return False
    return narrow == wide


def choose_maximal_payload(payloads: Sequence[Any]
                           ) -> Tuple[PayloadRelation, Optional[Any]]:
    """Return the relation among ``payloads`` and the payload to keep.

    The payload is ``None`` for anything but ``IDENTICAL`` and ``PROJECTION``:
    when two payloads disagree there is nothing to keep that would not be a
    choice between them.
    """
    if not payloads:
        return PayloadRelation.IDENTICAL, None
    distinct: List[Any] = []
    for payload in payloads:
        if not any(_deep_equal(payload, seen) for seen in distinct):
            distinct.append(payload)
    if len(distinct) == 1:
        return PayloadRelation.IDENTICAL, distinct[0]

    maximal = [candidate for candidate in distinct
               if all(is_projection_of(other, candidate) for other in distinct)]
    if len(maximal) == 1:
        return PayloadRelation.PROJECTION, maximal[0]
    if len(maximal) > 1:
        # Several payloads each contain all the others: they are equal in
        # content and differed only in a way _deep_equal caught, which should
        # not happen. Reported rather than silently resolved.
        return PayloadRelation.INCOMPARABLE, None
    if any(_contradicts(left, right)
           for index, left in enumerate(distinct)
           for right in distinct[index + 1:]):
        return PayloadRelation.CONFLICT, None
    return PayloadRelation.INCOMPARABLE, None


def describe_payload_difference(left: Any, right: Any,
                                path: str = "$", limit: int = 6
                                ) -> Tuple[str, ...]:
    """Name the paths at which two payloads disagree.

    Bounded, because a difference report longer than the payload helps nobody.
    Only genuine disagreements are listed: a key present in one payload and
    absent from the other is a view difference and is reported as such.
    """
    differences: List[str] = []
    _collect_differences(left, right, path, differences, limit)
    return tuple(differences[:limit])


# -- internals ----------------------------------------------------------


def _deep_equal(left: Any, right: Any) -> bool:
    return is_projection_of(left, right) and is_projection_of(right, left)


def _contradicts(left: Any, right: Any) -> bool:
    """True when the two payloads disagree somewhere they both speak."""
    return bool(describe_payload_difference(left, right, limit=1))


def _collect_differences(left: Any, right: Any, path: str,
                         out: List[str], limit: int) -> None:
    if len(out) >= limit:
        return
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        for key in sorted(set(left) & set(right)):
            _collect_differences(left[key], right[key],
                                 "%s.%s" % (path, key), out, limit)
        return
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        if len(left) != len(right):
            out.append("%s: %d entries versus %d"
                       % (path, len(left), len(right)))
            return
        for index, (one, other) in enumerate(zip(left, right)):
            _collect_differences(one, other, "%s[%d]" % (path, index), out,
                                 limit)
        return
    if isinstance(left, Mapping) != isinstance(right, Mapping) or \
            isinstance(left, (list, tuple)) != isinstance(right, (list, tuple)):
        out.append("%s: %s versus %s"
                   % (path, type(left).__name__, type(right).__name__))
        return
    if isinstance(left, bool) != isinstance(right, bool) or left != right:
        out.append("%s: %r versus %r" % (path, left, right))
