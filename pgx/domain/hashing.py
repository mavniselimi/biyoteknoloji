# -*- coding: utf-8 -*-
"""Canonical, deterministic hashing (WP-02).

Standard library only.

The determinism requirement in ``architecture.md`` section 9.6 means the same
semantic payload must hash identically on every machine and every run. This
module fixes the one canonical encoding used for input and output hashes:

* UTF-8, no ASCII escaping;
* object keys sorted;
* fixed separators, no incidental whitespace;
* ``NaN``/``Infinity`` rejected rather than silently encoded;
* UUIDs, enums, dates and aware datetimes given a stable spelling;
* naive datetimes rejected;
* sets and frozensets sorted by their canonical member form;
* array order preserved, because order carries meaning.

Nothing is added implicitly. In particular no wall-clock timestamp is folded
into a payload: a hash must depend only on what the caller passed in.

Digest format is ``sha256:<64 lowercase hex>``.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import uuid
from collections.abc import Mapping as _MappingABC
from decimal import Decimal
from enum import Enum
from typing import Any

from pgx.domain.errors import CanonicalizationError, InvalidTemporalValueError

__all__ = [
    "DIGEST_PREFIX",
    "SHA256_HEX_LENGTH",
    "canonical_json",
    "canonical_payload",
    "ensure_utc",
    "is_canonical_digest",
    "sha256_digest",
]

DIGEST_PREFIX = "sha256:"
SHA256_HEX_LENGTH = 64

_MAX_DEPTH = 64


def ensure_utc(value: _dt.datetime, field: str = "datetime") -> _dt.datetime:
    """Return ``value`` normalised to UTC, rejecting naive datetimes.

    A naive datetime has no defined instant, so it can neither be compared nor
    hashed reproducibly across environments.
    """
    if not isinstance(value, _dt.datetime):
        raise InvalidTemporalValueError(
            "%s must be a datetime, got %r" % (field, type(value).__name__))
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise InvalidTemporalValueError(
            "%s must be timezone-aware; naive datetimes are rejected because "
            "they do not identify an instant" % field)
    return value.astimezone(_dt.timezone.utc)


def _canonical(value: Any, path: str = "$", depth: int = 0) -> Any:
    """Recursively convert ``value`` into JSON-compatible canonical form."""
    if depth > _MAX_DEPTH:
        raise CanonicalizationError(
            "payload nests deeper than %d levels at %s" % (_MAX_DEPTH, path))

    if value is None or isinstance(value, str):
        return value

    # bool must be tested before int: it is a subclass of int.
    if isinstance(value, bool):
        return value

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise CanonicalizationError(
                "non-finite float at %s is not canonicalisable (%r)" % (path, value))
        return value

    if isinstance(value, Decimal):
        if not value.is_finite():
            raise CanonicalizationError(
                "non-finite Decimal at %s is not canonicalisable (%r)" % (path, value))
        # Decimals are rendered as strings so no binary float rounding occurs.
        return format(value.normalize(), "f")

    if isinstance(value, uuid.UUID):
        return str(value)

    if isinstance(value, Enum):
        return _canonical(value.value, path, depth + 1)

    if isinstance(value, _dt.datetime):
        return ensure_utc(value, path).isoformat().replace("+00:00", "Z")

    if isinstance(value, _dt.date):
        return value.isoformat()

    if isinstance(value, bytes):
        raise CanonicalizationError(
            "raw bytes at %s have no canonical text form; hash or decode them "
            "explicitly before hashing" % path)

    # Mapping, not dict: FrozenMapping is a Mapping and must hash identically
    # to the plain dict it was frozen from.
    if isinstance(value, _MappingABC):
        canonical: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError(
                    "object keys must be strings; got %r at %s"
                    % (type(key).__name__, path))
            canonical[key] = _canonical(item, "%s.%s" % (path, key), depth + 1)
        # Key order is normalised at serialisation time via sort_keys.
        return canonical

    if isinstance(value, (list, tuple)):
        # Order is preserved: sequence order is semantic.
        return [_canonical(item, "%s[%d]" % (path, index), depth + 1)
                for index, item in enumerate(value)]

    if isinstance(value, (set, frozenset)):
        # Sets have no inherent order, so members are sorted by their canonical
        # JSON spelling to make the result deterministic.
        members = [_canonical(item, "%s{}" % path, depth + 1) for item in value]
        try:
            return sorted(
                members,
                key=lambda member: json.dumps(
                    member, sort_keys=True, ensure_ascii=False, separators=(",", ":")),
            )
        except TypeError as exc:  # pragma: no cover - defensive
            raise CanonicalizationError(
                "set members at %s are not canonicalisable: %s" % (path, exc)) from exc

    # Anything with an explicit stable JSON form (domain identifiers).
    to_json = getattr(value, "to_json", None)
    if callable(to_json):
        return _canonical(to_json(), path, depth + 1)

    raise CanonicalizationError(
        "value of type %r at %s has no canonical form; add an explicit rule "
        "rather than relying on repr()" % (type(value).__name__, path))


def canonical_payload(payload: Any) -> Any:
    """Return the canonical, JSON-compatible form of ``payload``."""
    return _canonical(payload)


def canonical_json(payload: Any) -> str:
    """Return the canonical JSON text of ``payload``.

    Deterministic: sorted keys, fixed separators, UTF-8 characters preserved.
    """
    return json.dumps(
        canonical_payload(payload),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_digest(payload: Any) -> str:
    """Return ``sha256:<hex>`` for the canonical form of ``payload``.

    No timestamp, salt, or environment value is mixed in: the digest depends
    only on the payload the caller supplied.
    """
    encoded = canonical_json(payload).encode("utf-8")
    return DIGEST_PREFIX + hashlib.sha256(encoded).hexdigest()


def is_canonical_digest(value: object) -> bool:
    """True when ``value`` is a well-formed ``sha256:<hex>`` digest."""
    if not isinstance(value, str) or not value.startswith(DIGEST_PREFIX):
        return False
    hex_part = value[len(DIGEST_PREFIX):]
    return (
        len(hex_part) == SHA256_HEX_LENGTH
        and all(character in "0123456789abcdef" for character in hex_part)
    )
