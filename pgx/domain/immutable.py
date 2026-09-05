# -*- coding: utf-8 -*-
"""Recursive immutability for JSON-shaped domain values (WP-02 corrective).

Standard library only.

``@dataclass(frozen=True)`` only stops rebinding an attribute. It does nothing
about the object the attribute points at, so ``model.metadata["k"] = "v"``
succeeds on a plain dict and the "immutable" claim is false. This module makes
it true.

:func:`freeze_json` converts a JSON-shaped value into a deeply immutable one:

* mappings become :class:`FrozenMapping` (no ``__setitem__``, no ``update``);
* sequences become ``tuple``;
* conversion is recursive, so nested structures are frozen all the way down;
* the caller's original object is copied, so mutating it afterwards cannot
  reach inside the model.

Anything outside the JSON data model is **rejected**, not silently coerced:
callables, sets, bytes, ``NaN``, ``Infinity``, non-string mapping keys, and
arbitrary objects. A value that cannot round-trip through JSON has no place in
a record whose hash must be reproducible.

:func:`thaw_json` is the inverse, used at the ORM/JSONB boundary where the
driver needs real ``dict`` and ``list`` objects.
"""

from __future__ import annotations

import math
from collections.abc import Mapping as _MappingABC
from collections.abc import Sequence as _SequenceABC
from types import MappingProxyType
from typing import Any, Dict, Iterator, Mapping

from pgx.domain.errors import DomainInvariantError

__all__ = [
    "EMPTY_MAPPING",
    "FrozenMapping",
    "MAX_JSON_DEPTH",
    "freeze_json",
    "freeze_metadata",
    "is_frozen_json",
    "thaw_json",
]

#: Depth guard: a payload nested deeper than this is refused rather than
#: risking a recursion error during hashing or serialisation.
MAX_JSON_DEPTH = 64


class FrozenMapping(_MappingABC):
    """An immutable, ordered, string-keyed mapping of frozen JSON values.

    Implements ``Mapping`` but not ``MutableMapping``: there is no
    ``__setitem__``, ``__delitem__``, ``update``, ``pop``, ``popitem``,
    ``clear`` or ``setdefault``.

    The backing store is a :class:`types.MappingProxyType`, so the read-only
    view is what the ``_data`` slot holds. A previous revision stored a plain
    ``dict`` there, which made ``mapping._data["k"] = v`` and
    ``mapping._data.update(...)`` succeed — the object advertised immutability
    while handing out a mutable dictionary through ordinary attribute access.
    A proxy has no mutating methods at all, so there is nothing to reach.

    The public constructor **freezes what it is given**, recursively. The same
    revision copied only the top level, so ``FrozenMapping({"items": []})``
    kept the caller's list and every later ``append`` was visible inside the
    "immutable" mapping. Values now go through :func:`freeze_json`, which
    returns frozen containers and rejects anything outside the JSON data model.

    :meth:`_from_frozen` is the internal fast path used by :func:`freeze_json`,
    which has already frozen every value; it skips the second walk so nesting
    stays linear rather than quadratic.

    Iteration order is the insertion order of the source mapping, which keeps
    ``repr`` stable; hashing sorts keys separately, so order never affects a
    digest.

    This does not defend against Python's deliberate low-level escapes
    (``object.__setattr__``, ``gc.get_referents``). Those are not accidents;
    ``mapping._data[...] = ...`` is, and it no longer works.
    """

    __slots__ = ("_data", "_hash")

    def __init__(self, data: Mapping[str, Any]) -> None:
        if not isinstance(data, _MappingABC):
            raise DomainInvariantError(
                "FrozenMapping requires a mapping, got %r"
                % (type(data).__name__,))
        frozen: Dict[str, Any] = {}
        for key, value in data.items():
            if not isinstance(key, str):
                raise DomainInvariantError(
                    "mapping key %r is a %s; JSON object keys must be strings"
                    % (key, type(key).__name__))
            frozen[key] = freeze_json(value, "$.%s" % key, 1)
        self._install(frozen)

    @classmethod
    def _from_frozen(cls, frozen: Dict[str, Any]) -> "FrozenMapping":
        """Wrap a dict whose values are **already** frozen, without re-walking.

        Private on purpose: the caller carries the obligation that every value
        is frozen. :func:`freeze_json` is the only caller, and it has just
        produced those values itself.
        """
        instance = object.__new__(cls)
        instance._install(frozen)
        return instance

    def _install(self, frozen: Dict[str, Any]) -> None:
        # The dict is created here and never handed out; only the read-only
        # proxy over it is reachable, so the mapping cannot be mutated and the
        # hash below cannot go stale.
        object.__setattr__(self, "_data", MappingProxyType(frozen))
        object.__setattr__(self, "_hash", None)

    # -- Mapping protocol ------------------------------------------------

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __contains__(self, key: object) -> bool:
        return key in self._data

    # -- immutability ----------------------------------------------------

    def __setattr__(self, name: str, value: Any) -> None:
        raise DomainInvariantError(
            "FrozenMapping is immutable; attribute %r cannot be set" % name)

    def __delattr__(self, name: str) -> None:
        raise DomainInvariantError(
            "FrozenMapping is immutable; attribute %r cannot be deleted" % name)

    def __setitem__(self, key: str, value: Any) -> None:
        raise DomainInvariantError(
            "FrozenMapping is immutable; use a new model instead of assigning "
            "%r" % (key,))

    def __delitem__(self, key: str) -> None:
        raise DomainInvariantError(
            "FrozenMapping is immutable; %r cannot be deleted" % (key,))

    # -- value semantics -------------------------------------------------

    def __hash__(self) -> int:
        """Order-independent hash.

        Cached after the first call. The cache cannot go stale: the only
        reference to the backing dict lives inside a read-only proxy, so the
        content it summarises cannot change.
        """
        cached = self._hash
        if cached is None:
            cached = hash(tuple(sorted(self._data.items(), key=lambda item: item[0])))
            object.__setattr__(self, "_hash", cached)
        return cached

    def __eq__(self, other: object) -> bool:
        if isinstance(other, FrozenMapping):
            return dict(self._data) == dict(other._data)
        if isinstance(other, _MappingABC):
            return dict(self._data) == dict(other)
        return NotImplemented

    def __ne__(self, other: object) -> bool:
        result = self.__eq__(other)
        return result if result is NotImplemented else not result

    def __repr__(self) -> str:
        return "FrozenMapping(%r)" % (dict(self._data),)


#: Shared immutable empty mapping. A module-level ``{}`` would be mutable
#: shared state: one caller mutating it would change every default.
EMPTY_MAPPING = FrozenMapping({})


def _reject(value: Any, path: str) -> None:
    """Raise a precise error for a value outside the JSON data model."""
    kind = type(value).__name__
    if callable(value):
        raise DomainInvariantError(
            "callable at %s is not a JSON value; a rule condition is declarative "
            "data, never code" % path)
    if isinstance(value, (set, frozenset)):
        raise DomainInvariantError(
            "set at %s has no JSON representation and no defined order; use a "
            "list if order matters, or sort it explicitly first" % path)
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise DomainInvariantError(
            "binary data at %s has no canonical JSON text form; encode it "
            "explicitly (for example base64) before storing" % path)
    raise DomainInvariantError(
        "value of type %r at %s is not JSON-compatible; permitted values are "
        "null, bool, int, finite float, str, string-keyed mapping, and sequence"
        % (kind, path))


def freeze_json(value: Any, path: str = "$", depth: int = 0) -> Any:
    """Return a deeply immutable copy of a JSON-shaped ``value``.

    Args:
        value: The value to freeze.
        path: JSON path used in error messages.
        depth: Current recursion depth.

    Raises:
        DomainInvariantError: if the value is not JSON-compatible, contains a
            non-string mapping key, or is nested too deeply.
    """
    if depth > MAX_JSON_DEPTH:
        raise DomainInvariantError(
            "value nests deeper than %d levels at %s" % (MAX_JSON_DEPTH, path))

    if value is None:
        return None

    # bool before int: bool is a subclass of int.
    if isinstance(value, bool):
        return value

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise DomainInvariantError(
                "non-finite float at %s (%r) cannot be represented in JSON and "
                "would break deterministic hashing" % (path, value))
        return value

    if isinstance(value, str):
        return value

    if isinstance(value, FrozenMapping):
        # Every value inside a FrozenMapping is frozen by construction - the
        # public constructor freezes and the private fast path is only reached
        # with frozen values - so re-walking it would be wasted work.
        return value

    if isinstance(value, _MappingABC):
        frozen: Dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise DomainInvariantError(
                    "mapping key %r at %s is a %s; JSON object keys must be "
                    "strings" % (key, path, type(key).__name__))
            frozen[key] = freeze_json(item, "%s.%s" % (path, key), depth + 1)
        # Values are already frozen; the fast path avoids a second recursion.
        return FrozenMapping._from_frozen(frozen)

    if isinstance(value, (list, tuple)):
        return tuple(
            freeze_json(item, "%s[%d]" % (path, index), depth + 1)
            for index, item in enumerate(value))

    # A str is a Sequence, but it was handled above; anything else claiming to
    # be a Sequence (and not bytes) is treated as a list.
    if isinstance(value, _SequenceABC) and not isinstance(
            value, (str, bytes, bytearray)):
        return tuple(
            freeze_json(item, "%s[%d]" % (path, index), depth + 1)
            for index, item in enumerate(value))

    _reject(value, path)
    raise AssertionError("unreachable")  # pragma: no cover


def thaw_json(value: Any) -> Any:
    """Return a plain ``dict``/``list`` copy of a frozen value.

    Used at the ORM/JSONB boundary, where psycopg needs real mutable
    containers. The copy is fresh, so the driver cannot reach back into a
    domain object.
    """
    if isinstance(value, _MappingABC):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [thaw_json(item) for item in value]
    return value


def is_frozen_json(value: Any) -> bool:
    """True when ``value`` is already deeply frozen JSON.

    A non-finite float is **not** frozen JSON. ``NaN`` and ``+-Infinity`` have
    no JSON representation and would break deterministic hashing, so
    :func:`freeze_json` rejects them; reporting them as frozen would have let a
    caller trust a value the freezer would refuse.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, FrozenMapping):
        return all(is_frozen_json(item) for item in value.values())
    if isinstance(value, tuple):
        return all(is_frozen_json(item) for item in value)
    return False


def freeze_metadata(value: Any, field: str) -> Mapping[str, Any]:
    """Freeze a metadata mapping field, defaulting to the shared empty mapping."""
    if value is None:
        return EMPTY_MAPPING
    if not isinstance(value, _MappingABC):
        raise DomainInvariantError(
            "%s must be a mapping, got %r" % (field, type(value).__name__))
    return freeze_json(value, "$." + field)
