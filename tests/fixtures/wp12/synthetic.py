# -*- coding: utf-8 -*-
"""SYNTHETIC WP-12 phenotype fixtures. TEST ONLY. NOT CLINICAL DATA.

NOT FOR REAL ASSESSMENT. Every gene, phenotype and profile below is invented
to exercise normalisation and matching. Nothing here was reviewed by anybody,
and none of it is a statement about any medicine.

The synthetic genes deliberately are not real CYP genes: a fixture naming
CYP2D6 and a phenotype reads as a claim about CYP2D6, and screenshots of tests
outlive their context. The legacy comparison harness is the one place real
gene names appear, because it is reading a real legacy artifact.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

from pgx.domain.enums import Phenotype
from pgx.engine.phenotype_normalization import (INPUT_CONTRACT_VERSION,
                                                normalize_phenotype,
                                                normalize_profile)
from pgx.rules.conditions import PhenotypeMatch, RuleCondition

SYNTHETIC_MARKERS: Tuple[str, ...] = (
    "SYNTHETIC", "TEST ONLY", "NOT CLINICAL DATA", "NOT FOR REAL ASSESSMENT")

#: Matches the WP-11 fixture vocabulary, so a WP-12 profile can be compared
#: with a WP-11 synthetic rule without either inventing a second world.
SYNTHETIC_GENE = "GENE:TESTGENE1"
SYNTHETIC_GENE_2 = "GENE:TESTGENE2"
SYNTHETIC_DRUG = "DRUG:testdrug-alpha"

#: Every phenotype a rule may be keyed on, and the one it may not.
DETERMINATE = (Phenotype.POOR, Phenotype.INTERMEDIATE, Phenotype.NORMAL,
               Phenotype.RAPID, Phenotype.ULTRARAPID)


def observation(value: Any, gene: str = SYNTHETIC_GENE):
    """One normalised observation, for the gene the fixtures use."""
    return normalize_phenotype(value, gene_canonical_key=gene)


def exact(phenotype: Phenotype) -> PhenotypeMatch:
    return PhenotypeMatch(operator="EXACT", values=(phenotype,))


def one_of(*phenotypes: Phenotype) -> PhenotypeMatch:
    return PhenotypeMatch(operator="ONE_OF", values=tuple(phenotypes))


def condition(phenotype_match: Optional[PhenotypeMatch] = None,
              gene: str = SYNTHETIC_GENE,
              drug: str = SYNTHETIC_DRUG) -> RuleCondition:
    """A WP-11 condition over the synthetic axis."""
    return RuleCondition(
        gene_canonical_key=gene, drug_canonical_key=drug,
        phenotype=phenotype_match or exact(Phenotype.POOR))


def profile(values: Optional[Mapping[str, Any]] = None,
            profile_id: str = "TEST-PROFILE-SYNTHETIC-1",
            **kwargs: Any):
    """A synthetic profile. Every default value is valid, so a test changing
    one thing can attribute the failure to that thing."""
    payload: Dict[str, Any] = dict(values if values is not None else {
        SYNTHETIC_GENE: "POOR", SYNTHETIC_GENE_2: "NORMAL"})
    metadata = kwargs.pop("metadata", {"markers": list(SYNTHETIC_MARKERS)})
    return normalize_profile(payload, profile_id=profile_id,
                             metadata=metadata, **kwargs)
