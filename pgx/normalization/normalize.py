# -*- coding: utf-8 -*-
"""Exact, deterministic normalisation (WP-07).

Standard library only.

**Exact, and nothing more.** There is no fuzzy matching here, no substring
containment, no edit distance, no phonetic key, no embedding and no model. Each
function applies a fixed sequence of Unicode operations and returns the result.
That is a deliberate ceiling, not an unfinished implementation: a resolver that
could guess would eventually guess wrong about a gene, and the failure would be
invisible because the guess looks exactly like a match.

**The original spelling always survives.** Every normalisation returns a value
to compare with; the caller keeps the source's own text beside it. A canonical
record that had thrown away what the source actually wrote could not be checked
against the source again.

**NFKC, deliberately.** Compatibility composition folds the full-width and
ligature forms that appear when data passes through a spreadsheet, so ``ＣＹＰ２Ｃ１９``
and ``CYP2C19`` compare equal. It does not fold anything meaning-bearing here:
digits, Latin letters and the punctuation drug names use are untouched.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional, Tuple

from pgx.normalization.errors import NormalizationError

__all__ = [
    "NORMALIZATION_RULE_VERSION",
    "ExternalIdentifier",
    "normalize_drug_name",
    "normalize_endpoint_container",
    "normalize_external_id",
    "normalize_gene_symbol",
    "normalize_whitespace",
]

#: Bumped whenever any rule below changes. Recorded in the canonical manifest,
#: because a canonical build is only comparable with another built under the
#: same rules.
NORMALIZATION_RULE_VERSION = "pgx-normalization/1"

#: Characters that must never appear in a normalised value: control codes and
#: the Unicode separators that are invisible in a diff.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏  ﻿]")

_WHITESPACE = re.compile(r"\s+")

#: A gene symbol as HGNC writes them: letters, digits, and the hyphen and
#: dot that appear in real symbols (``HLA-B``, ``MT-CO1``). Anything else is
#: refused rather than stripped, because stripping punctuation out of a symbol
#: is how ``HLA-B`` quietly becomes ``HLAB``.
_GENE_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9\-.@_]*$")

_MAX_LENGTH = 300


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise NormalizationError(
            "%s must be a string, got %s" % (field, type(value).__name__))
    if _CONTROL.search(value):
        raise NormalizationError(
            "%s contains a control or invisible separator character" % field)
    if len(value) > _MAX_LENGTH:
        raise NormalizationError(
            "%s is %d characters; the limit is %d"
            % (field, len(value), _MAX_LENGTH))
    return value


def normalize_whitespace(value: str) -> str:
    """Trim, then collapse every internal run of whitespace to one space."""
    return _WHITESPACE.sub(" ", value).strip()


def normalize_gene_symbol(value: object) -> str:
    """Return the canonical form of a gene symbol.

    NFKC, trim, collapse internal whitespace, upper-case. Case-folding is done
    with ``str.upper`` on an NFKC-composed string, which is locale-independent:
    the Turkish dotless-i rule that would turn ``i`` into ``I`` incorrectly is a
    property of locale-aware case mapping, and Python's is not locale-aware.

    A symbol is validated against the shape HGNC actually uses. Punctuation is
    never removed - ``HLA-B`` and ``HLAB`` are different genes, and a rule that
    stripped the hyphen would merge them silently.

    Raises:
        NormalizationError: the value is not a string, is blank, or is not a
            plausible symbol. Never returns a guess.
    """
    text = _require_text(value, "gene symbol")
    folded = normalize_whitespace(unicodedata.normalize("NFKC", text)).upper()
    if not folded:
        raise NormalizationError("a gene symbol must not be blank")
    if not _GENE_SYMBOL.match(folded):
        raise NormalizationError(
            "%r is not a usable gene symbol after normalisation (%r). "
            "Punctuation is never stripped and no fuzzy repair is attempted."
            % (text, folded))
    return folded


def normalize_drug_name(value: object) -> str:
    """Return the canonical form of a drug name.

    NFKC, trim, collapse internal whitespace, then ``str.casefold`` - which is
    the locale-independent full case fold, stronger than ``lower`` and correct
    for the Greek final sigma and the German sharp s.

    Meaningful punctuation is preserved. Salts, formulations, combinations and
    active-ingredient qualifiers are **not** removed: ``metoprolol tartrate``
    and ``metoprolol succinate`` are different products, and silently reducing
    both to ``metoprolol`` would be a scientific claim disguised as string
    cleaning.

    Recognising a chemical name says nothing about pharmacogenetic coverage.
    That distinction belongs to WP-09 and later, and nothing here implies it.
    """
    text = _require_text(value, "drug name")
    folded = normalize_whitespace(unicodedata.normalize("NFKC", text)).casefold()
    if not folded:
        raise NormalizationError("a drug name must not be blank")
    return folded


def normalize_endpoint_container(value: object) -> str:
    """Return the canonical identity of a source container or endpoint name.

    ``variantAnnotation`` and ``VariantAnnotation`` are the same container
    spelled two ways in the same response; folding them is what makes
    ``LEGACY-BUG-004`` detectable rather than a source of phantom records. The
    original spelling is always kept in provenance alongside this value.

    This normalises the *container's* identity, never a record's content.
    """
    text = _require_text(value, "container name")
    return normalize_whitespace(unicodedata.normalize("NFKC", text)).casefold()


class ExternalIdentifier(tuple):
    """A namespaced external identifier: ``(namespace, value)``.

    A bare identifier is never compared across namespaces. ``PA124`` in the
    ClinPGx namespace and ``PA124`` in some other registry are different facts,
    and treating them as one would join two unrelated records.
    """

    __slots__ = ()

    def __new__(cls, namespace: str, value: str) -> "ExternalIdentifier":
        return super().__new__(cls, (namespace, value))

    @property
    def namespace(self) -> str:
        return self[0]

    @property
    def value(self) -> str:
        return self[1]

    def to_json(self) -> str:
        """``namespace:value`` - the one spelling used in artifacts."""
        return "%s:%s" % (self.namespace, self.value)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "ExternalIdentifier(%r, %r)" % (self.namespace, self.value)


#: Namespaces this project knows how to validate, and the shape each requires.
#: A namespace absent from this table is accepted with its value normalised but
#: unvalidated, and that fact is reported: silently accepting an unknown
#: namespace as if it had been checked would be the worse failure.
_NAMESPACE_PATTERNS = {
    "clinpgx": re.compile(r"^PA[0-9]+$"),
    "pharmgkb": re.compile(r"^PA[0-9]+$"),
    "hgnc": re.compile(r"^HGNC:[0-9]+$"),
    "rxnorm": re.compile(r"^[0-9]+$"),
    "atc": re.compile(r"^[A-Z][0-9]{2}[A-Z]{2}[0-9]{2}$"),
    "drugbank": re.compile(r"^DB[0-9]{5}$"),
    "ncbigene": re.compile(r"^[0-9]+$"),
}

_NAMESPACE_NAME = re.compile(r"^[a-z][a-z0-9_.-]*$")


def normalize_external_id(
    namespace: object, value: object
) -> Tuple[ExternalIdentifier, Optional[str]]:
    """Return a namespaced identifier and, if it is malformed, why.

    The second element is ``None`` for a well-formed identifier and a short
    explanation otherwise. An invalid identifier is **returned**, not discarded:
    it has to stay visible as a data-quality finding, and dropping it would make
    a broken external reference look like an absent one.

    Raises:
        NormalizationError: only when the namespace itself is unusable. A bad
            *value* is a finding; a bad *namespace* means the caller cannot say
            what kind of identifier this is at all.
    """
    namespace_text = _require_text(namespace, "external id namespace")
    folded_namespace = normalize_whitespace(
        unicodedata.normalize("NFKC", namespace_text)).casefold()
    if not _NAMESPACE_NAME.match(folded_namespace):
        raise NormalizationError(
            "%r is not a usable external identifier namespace" % namespace_text)

    value_text = _require_text(value, "external id value")
    normalized_value = normalize_whitespace(
        unicodedata.normalize("NFKC", value_text))
    identifier = ExternalIdentifier(folded_namespace, normalized_value)

    if not normalized_value:
        return identifier, "the identifier value is blank"
    pattern = _NAMESPACE_PATTERNS.get(folded_namespace)
    if pattern is None:
        return identifier, ("namespace %r has no validation rule in this build; "
                            "the value is recorded unchecked"
                            % folded_namespace)
    if not pattern.match(normalized_value):
        return identifier, ("%r does not match the %s identifier shape %s"
                            % (normalized_value, folded_namespace,
                               pattern.pattern))
    return identifier, None
