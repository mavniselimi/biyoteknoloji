# -*- coding: utf-8 -*-
"""What makes two validation cases the same case (WP-18).

Duplicate detection across the development/holdout line is the load-bearing
check of this work package, and it is worth being precise about what it may
and may not use.

**It may not use display text.** A title, a label or a filename is a thing a
curator typed. Two people writing up the same source vignette will not type
the same title, and one person can retitle a case in the morning and create a
"new" one in the afternoon. A partition guarded by titles is guarded by
nothing.

**It may not use the case identifier.** That is the whole point: a holdout
case copied from a development case gets a fresh identifier precisely because
somebody meant it to look new.

**So it uses content**, canonicalised: the observations, the medications, the
scientific context. Canonicalisation here means four specific things, each of
which was chosen because ignoring it produces a false *distinction* - two
records of the same case that hash differently and therefore both enter a
denominator:

1. *Key order is irrelevant.* JSON objects are unordered, and
   :func:`pgx.domain.hashing.canonical_json` already sorts them.
2. *Observation order is irrelevant.* A profile is a set of gene-phenotype
   statements, not a sequence; "CYP2C19 poor, CYP2D6 normal" and the reverse
   are the same profile. Sequences whose order *is* meaningful are not sorted
   - see :data:`ORDER_INSENSITIVE_FIELDS`, which names them one at a time
   rather than sorting everything.
3. *Unicode form is irrelevant.* ``NFC`` throughout. A Turkish label typed on
   two keyboards can be two byte sequences and one string.
4. *Surrounding whitespace is irrelevant, and case is irrelevant only where a
   vocabulary says so.* Governed tokens - gene keys, phenotype values - are
   already upper-case by their own validation; free-form text is stripped and
   folded, because "  CYP2C19 " and "CYP2C19" are one token.

**What it must not do is collapse genuinely different cases.** Every rule
above removes a difference that carries no scientific meaning. None of them
removes a difference that does: a changed phenotype, a changed medication, an
added gene and a changed source all change the fingerprint, and tests assert
each of those separately.
"""

from __future__ import annotations

import unicodedata
from typing import Any, Mapping, Sequence, Tuple

from pgx.domain.hashing import canonical_json, sha256_digest
from pgx.validation.errors import FingerprintError

__all__ = [
    "CONTENT_FINGERPRINT_VERSION",
    "ORDER_INSENSITIVE_FIELDS",
    "canonical_content",
    "content_fingerprint",
    "derivation_family_fingerprint",
    "normalise_text",
]

#: Bumping this changes every fingerprint, so it is part of what a manifest
#: records. A silent change to the rules below would make an old audit's
#: "no duplicates" conclusion meaningless while looking identical.
CONTENT_FINGERPRINT_VERSION = "pgx-wp18-content-fingerprint/1"

#: Fields whose sequence order carries no meaning and is therefore normalised
#: away. Named individually and deliberately short: sorting every list would
#: silently erase order from a field where order matters, and the failure
#: would be two distinct cases hashing alike - a false duplicate that hides a
#: real case rather than a false distinction that merely counts one twice.
ORDER_INSENSITIVE_FIELDS: Tuple[str, ...] = (
    "observations",
    "medications",
    "source_citations",
)

_MAX_TEXT = 4096


def normalise_text(value: str, *, fold_case: bool = False) -> str:
    """NFC, stripped, optionally case-folded. The text half of the rules.

    ``fold_case`` is off by default. Governed tokens validate their own case
    and folding them would let a malformed value pass; free-form text is
    folded by its caller, where the decision is visible.
    """
    if not isinstance(value, str):
        raise FingerprintError("expected a string, got %r"
                               % type(value).__name__)
    if len(value) > _MAX_TEXT:
        raise FingerprintError("a text value exceeds %d characters and is "
                               "refused rather than truncated" % _MAX_TEXT)
    text = unicodedata.normalize("NFC", value).strip()
    return text.casefold() if fold_case else text


def _canonicalise(value: Any, path: str, depth: int) -> Any:
    if depth > 24:
        raise FingerprintError("content nests deeper than 24 levels at %s"
                               % path)
    if isinstance(value, str):
        return normalise_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Mapping):
        out = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise FingerprintError("content keys must be strings at %s"
                                       % path)
            name = normalise_text(key)
            child = _canonicalise(item, "%s.%s" % (path, name), depth + 1)
            if name in ORDER_INSENSITIVE_FIELDS and isinstance(child, list):
                # Sorted by canonical rendering rather than by a chosen key:
                # the members may be scalars or objects, and a key-based sort
                # would need to know their shape.
                child = sorted(child, key=canonical_json)
            out[name] = child
        return out
    if isinstance(value, (list, tuple)):
        return [_canonicalise(item, "%s[%d]" % (path, index), depth + 1)
                for index, item in enumerate(value)]
    raise FingerprintError("content carries an unhashable %r at %s"
                           % (type(value).__name__, path))


def canonical_content(content: Mapping[str, Any]) -> Mapping[str, Any]:
    """The canonical form a fingerprint is taken over. Returned for review.

    Exposed rather than kept private so that a curator investigating why two
    cases collided can look at exactly what was compared, instead of being
    told a digest and left to guess.
    """
    if not isinstance(content, Mapping):
        raise FingerprintError("content must be a mapping, got %r"
                               % type(content).__name__)
    if not content:
        raise FingerprintError("content is empty; an empty case has no "
                               "identity and would collide with every other "
                               "empty case")
    return _canonicalise(content, "$", 0)


def content_fingerprint(content: Mapping[str, Any]) -> str:
    """The ``sha256:`` fingerprint of a case's scientific content.

    Deterministic across processes and runs: no clock, no ``id()``, no set
    iteration order, no PYTHONHASHSEED dependence.
    """
    return sha256_digest({"fingerprint_version": CONTENT_FINGERPRINT_VERSION,
                          "content": canonical_content(content)})


def derivation_family_fingerprint(source_identity: str,
                                  derivation_method: str) -> str:
    """Identity of the *lineage* a case came from, not of the case.

    Two cases built from one source vignette by one method belong to one
    family even when their content differs - one may add a medication, one may
    drop a gene. That is exactly the pair a content fingerprint cannot catch
    and a partition must still refuse to split, because the second case leaks
    the first.

    Folded and NFC-normalised, because a family identity is written by hand
    and "Smith 2019, Table 3" and "smith 2019, table 3" are one lineage.
    """
    source = normalise_text(source_identity, fold_case=True)
    method = normalise_text(derivation_method, fold_case=True)
    if not source:
        raise FingerprintError("a derivation family needs a source identity")
    if not method:
        raise FingerprintError("a derivation family needs a derivation method")
    return sha256_digest({"fingerprint_version": CONTENT_FINGERPRINT_VERSION,
                          "family": {"source": source, "method": method}})
