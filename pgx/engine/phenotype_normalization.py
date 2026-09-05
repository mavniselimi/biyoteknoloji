# -*- coding: utf-8 -*-
"""The phenotype input boundary (WP-12), contract ``pgx-phenotype-input/1``.

This module is the only place a supplied value becomes a
:class:`~pgx.domain.enums.Phenotype`, and it is deliberately the least clever
module in the repository.

**What version 1 accepts.** Transport-level formatting differences and nothing
else: surrounding whitespace, and case. ``"POOR"``, ``"poor"`` and ``" Poor "``
all name the canonical token ``POOR``. That is the whole vocabulary.

**What it refuses, and why it refuses rather than guesses.** ``PM``, ``poor
metabolizer``, ``zayıf``, ``decreased_function``, ``*1/*2``, an activity
score, a laboratory line, a sentence - every one of these is *plausibly*
mappable, and mapping any of them is a scientific claim about what a source
meant. Legacy ``normalize_profile_phenotype`` makes exactly those mappings,
including a substring rule under which ``"poor response"`` becomes ``POOR``,
and a ``decreased`` rule that invents a group the P0 model does not have. A
future reviewed vocabulary can be ``pgx-phenotype-input/2``; until somebody
qualified has approved one, the honest answer to an unrecognised token is that
it is unsupported.

So there is no substring test, no prefix test, no edit distance, no regular
expression over content, no similarity, no "closest" phenotype, no numeric
coercion, and no fallback to ``NORMAL``. Unrecognised input produces an
``UNSUPPORTED`` observation carrying a reason code, which downstream must
carry through as an absence of assessment rather than an absence of risk
(``SAFETY-INV-001``).

Two refusals are given their own reason codes because they are the two
mistakes most likely to be made on purpose: a genotype-shaped value, and a
broad functional group. Both are real inputs somebody will try; both are
inference this system does not perform.
"""

from __future__ import annotations

import unicodedata
from typing import Any, Dict, FrozenSet, Iterable, Mapping, Optional, Tuple

from pgx.domain.enums import Phenotype
from pgx.engine.phenotype_errors import PhenotypeProfileError
from pgx.engine.phenotype_models import (PhenotypeObservation, PhenotypeProfile)
from pgx.normalization.errors import NormalizationError
from pgx.normalization.models import EntityType, canonical_key_for
from pgx.normalization.normalize import normalize_gene_symbol

__all__ = [
    "BROAD_FUNCTION_TOKENS",
    "CANONICAL_PHENOTYPE_TOKENS",
    "GENOTYPE_MARKERS",
    "INPUT_CONTRACT_VERSION",
    "SUPPORTED_INPUT_CONTRACT_VERSIONS",
    "normalize_gene_key",
    "normalize_phenotype",
    "normalize_profile",
]

#: The contract this module implements. A stored result names it, so a reader
#: years from now knows which rules produced the verdict rather than assuming
#: today's.
INPUT_CONTRACT_VERSION = "pgx-phenotype-input/1"

#: Every contract version this module can evaluate. One, today. A caller
#: naming another is refused rather than served under this one's rules.
SUPPORTED_INPUT_CONTRACT_VERSIONS: Tuple[str, ...] = (INPUT_CONTRACT_VERSION,)

#: The accepted tokens, derived from the enum rather than retyped, so a
#: seventh phenotype cannot appear in one place and not the other.
CANONICAL_PHENOTYPE_TOKENS: Mapping[str, Phenotype] = {
    member.value: member for member in Phenotype}

#: Broad functional groups. Named so the refusal can say *which* mistake was
#: made, not to enable a mapping: none of these has an entry pointing at a
#: phenotype. ``decreased_function`` is legacy ``PROFILE_MATCH_GROUPS``'
#: invention, and expanding it into POOR or INTERMEDIATE would apply a rule
#: outside the evidence it was written from.
BROAD_FUNCTION_TOKENS: FrozenSet[str] = frozenset({
    "DECREASED_FUNCTION", "DECREASED FUNCTION", "DECREASED",
    "INCREASED_FUNCTION", "INCREASED FUNCTION", "INCREASED",
    "NO_FUNCTION", "NO FUNCTION", "NONFUNCTIONAL", "NON-FUNCTIONAL",
    "NORMAL_FUNCTION", "NORMAL FUNCTION", "REDUCED_FUNCTION",
    "REDUCED FUNCTION", "REDUCED", "UNCERTAIN_FUNCTION",
    "UNCERTAIN FUNCTION", "ALTERED_FUNCTION", "ALTERED FUNCTION",
    "POSSIBLE_DECREASED_FUNCTION", "LIKELY_DECREASED_FUNCTION",
})

#: Substrings that mark a value as genotype-shaped. This is the one place a
#: substring test appears, and it exists only to *refuse* more precisely - it
#: can never cause a value to be accepted, and a value that avoids every
#: marker is still refused unless it is an exact canonical token.
GENOTYPE_MARKERS: Tuple[str, ...] = ("*", "/", "RS", "HAPLOTYPE", "DIPLOTYPE",
                                     "ALLELE", "GENOTYPE")

#: Values that mean "nothing was supplied". Everything else non-empty is
#: either a canonical token or unsupported.
_EMPTY_TOKENS: FrozenSet[str] = frozenset({""})


def _reason(code: str) -> str:
    from pgx.engine.phenotype_models import NORMALIZATION_REASON_CODES
    return NORMALIZATION_REASON_CODES[code]


def _fold(value: str) -> str:
    """Transport-level folding, and no more.

    NFKC then upper-case, on an already-trimmed string. ``str.upper`` is used
    rather than a locale-aware mapping for the reason WP-07 gives: the Turkish
    dotless-i rule would fold ``i`` incorrectly, and Python's mapping is not
    locale-aware.
    """
    return unicodedata.normalize("NFKC", value).strip().upper()


def normalize_gene_key(value: Any) -> str:
    """The canonical gene key WP-07 would allocate for ``value``.

    Accepts either a bare symbol (``CYP2D6``) or an already-prefixed key
    (``GENE:CYP2D6``) and returns the prefixed form. WP-07's normaliser is
    imported rather than re-described: a second copy of the gene grammar would
    drift, and the day it did, a profile would key an observation on a gene the
    canonical dataset does not contain.

    Raises:
        PhenotypeProfileError: the value is not a usable gene symbol. Genes are
            the *keys* of a profile, so an uninterpretable one is a structural
            failure rather than an observation - there is nothing to record it
            against.
    """
    if not isinstance(value, str) or not value.strip():
        raise PhenotypeProfileError(
            "a gene key must be a non-empty string, got %r"
            % (type(value).__name__ if not isinstance(value, str) else value),
            code="PHENOTYPE_GENE_INVALID", location="$.gene")
    text = value.strip()
    if text.upper().startswith("GENE:"):
        text = text[len("GENE:"):]
    try:
        symbol = normalize_gene_symbol(text)
    except NormalizationError as error:
        raise PhenotypeProfileError(
            "%r is not a usable gene symbol: %s. No repair is attempted."
            % (value, error),
            code="PHENOTYPE_GENE_INVALID", location="$.gene")
    return canonical_key_for(EntityType.GENE, symbol)


def normalize_phenotype(value: Any, *, gene_canonical_key: str,
                        contract_version: str = INPUT_CONTRACT_VERSION
                        ) -> PhenotypeObservation:
    """Interpret one supplied phenotype value under the input contract.

    Never raises for a bad *value*: an unusable input is a result a caller has
    to record and carry, not an exception it may swallow. It does raise if the
    caller names a contract version this module does not implement, because
    serving a version 2 document under version 1 rules would be answering a
    question nobody asked.
    """
    if contract_version not in SUPPORTED_INPUT_CONTRACT_VERSIONS:
        raise PhenotypeProfileError(
            "input contract %r is not implemented here; supported: %s"
            % (contract_version, ", ".join(SUPPORTED_INPUT_CONTRACT_VERSIONS)),
            code="PHENOTYPE_CONTRACT_UNSUPPORTED",
            location="$.input_contract_version")

    def _observation(status: str, phenotype: Optional[Phenotype] = None,
                     code: Optional[str] = None,
                     raw: Optional[str] = None) -> PhenotypeObservation:
        return PhenotypeObservation(
            gene_canonical_key=gene_canonical_key, status=status,
            phenotype=phenotype, reason_code=code,
            reason=_reason(code) if code else None, raw_value=raw,
            input_contract_version=contract_version)

    # Absent, in every spelling of absent.
    if value is None:
        return _observation("MISSING", code="PHENOTYPE_INPUT_MISSING")

    # A non-string is not a phenotype. Note the bool test precedes the int
    # test it would otherwise satisfy, and that nothing is coerced: int(1) is
    # not INTERMEDIATE, and True is not NORMAL.
    if not isinstance(value, str):
        return _observation(
            "UNSUPPORTED", code="PHENOTYPE_INPUT_INVALID_TYPE",
            raw=repr(value) if not isinstance(value, (list, dict, tuple))
            else "%s(len=%d)" % (type(value).__name__, len(value)))

    raw = value
    folded = _fold(value)
    if folded in _EMPTY_TOKENS:
        return _observation("MISSING", code="PHENOTYPE_INPUT_MISSING", raw=raw)

    # INDETERMINATE is a determination that none could be made. It is recorded
    # as its own status rather than as a phenotype, so it can never be handed
    # to a matcher as a value to compare.
    if folded == Phenotype.INDETERMINATE.value:
        return _observation("INDETERMINATE",
                            code="PHENOTYPE_INPUT_INDETERMINATE", raw=raw)

    phenotype = CANONICAL_PHENOTYPE_TOKENS.get(folded)
    if phenotype is not None:
        return _observation("NORMALIZED", phenotype=phenotype, raw=raw)

    # From here everything is unsupported. The remaining tests only choose
    # which reason to report; none of them can accept a value.
    if folded in BROAD_FUNCTION_TOKENS:
        return _observation(
            "UNSUPPORTED", code="PHENOTYPE_INPUT_BROAD_GROUP_NOT_ALLOWED",
            raw=raw)
    if any(marker in folded for marker in GENOTYPE_MARKERS):
        return _observation(
            "UNSUPPORTED", code="PHENOTYPE_INPUT_GENOTYPE_NOT_ALLOWED", raw=raw)
    return _observation("UNSUPPORTED", code="PHENOTYPE_INPUT_UNSUPPORTED",
                        raw=raw)


def normalize_profile(phenotypes: Any, *,
                      profile_id: Optional[str] = None,
                      known_gene_keys: Optional[Iterable[str]] = None,
                      require_known_genes: bool = False,
                      metadata: Optional[Mapping[str, Any]] = None,
                      contract_version: str = INPUT_CONTRACT_VERSION
                      ) -> PhenotypeProfile:
    """Normalise a whole gene-to-phenotype mapping into a canonical profile.

    Every supplied gene produces an observation, including the ones whose
    values could not be interpreted: a profile that dropped them would look
    complete. The caller's mapping is copied, so mutating it afterwards cannot
    change the profile.

    ``require_known_genes`` turns on catalogue validation against
    ``known_gene_keys``. It fails closed in the literal sense: asking for
    validation while supplying an empty catalogue is refused rather than
    treated as "nothing to check against". An empty catalogue means nothing is
    known to exist, which is not the same as everything being fine.

    Raises:
        PhenotypeProfileError: the input is not a mapping; a gene key is
            unusable; two keys normalise to one canonical gene; or catalogue
            validation was requested and either the catalogue is empty or a
            gene is outside it.
    """
    if phenotypes is None or not isinstance(phenotypes, Mapping):
        raise PhenotypeProfileError(
            "a phenotype profile is a mapping of gene to value, got %s"
            % type(phenotypes).__name__,
            code="PHENOTYPE_PROFILE_MALFORMED", location="$.phenotypes")

    catalogue = frozenset(known_gene_keys or ())
    if require_known_genes and not catalogue:
        raise PhenotypeProfileError(
            "gene catalogue validation was requested with an empty catalogue. "
            "An empty catalogue means no gene is known to exist, so every gene "
            "would be outside it; this refuses rather than passing everything.",
            code="PHENOTYPE_CATALOGUE_EMPTY", location="$.known_gene_keys")

    observations: Dict[str, PhenotypeObservation] = {}
    raw_by_key: Dict[str, str] = {}
    for raw_gene, raw_value in dict(phenotypes).items():
        gene_key = normalize_gene_key(raw_gene)
        if gene_key in observations:
            # Two spellings of one gene. Choosing either would be inventing an
            # observation, and choosing the first would make the result depend
            # on dictionary order.
            raise PhenotypeProfileError(
                "%r and %r both normalise to %s; a profile may state a gene "
                "once" % (raw_by_key[gene_key], raw_gene, gene_key),
                code="PHENOTYPE_PROFILE_DUPLICATE_GENE",
                location="$.phenotypes.%s" % gene_key,
                detail={"gene": gene_key,
                        "spellings": sorted([raw_by_key[gene_key],
                                             str(raw_gene)])})
        if require_known_genes and gene_key not in catalogue:
            raise PhenotypeProfileError(
                "%s is not in the pinned canonical gene catalogue" % gene_key,
                code="PHENOTYPE_GENE_NOT_IN_CATALOGUE",
                location="$.phenotypes.%s" % gene_key,
                detail={"gene": gene_key})
        raw_by_key[gene_key] = str(raw_gene)
        observations[gene_key] = normalize_phenotype(
            raw_value, gene_canonical_key=gene_key,
            contract_version=contract_version)

    return PhenotypeProfile(
        observations=tuple(observations.values()),
        input_contract_version=contract_version,
        profile_id=profile_id,
        metadata=dict(metadata or {}))
