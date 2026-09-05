# -*- coding: utf-8 -*-
"""SYNTHETIC WP-13 coverage fixtures. TEST ONLY. NOT CLINICAL DATA.

NOT FOR REAL ASSESSMENT. Every gene, drug, phenotype, coverage declaration and
approving actor below is invented to exercise the coverage engine. Nothing
here was reviewed by anybody, and none of it is a statement about any medicine.

The synthetic entities deliberately are not real CYP genes or real drugs: a
fixture declaring coverage for CYP2D6 and codeine reads as a claim about them,
and screenshots of tests outlive their context. The legacy regression is the
one place real names appear, because it reads the real pinned catalogue in
order to report honestly what that catalogue does and does not contain.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from pgx.domain.enums import Phenotype
from pgx.engine.coverage_manifest import (CoverageManifestApproval,
                                          build_coverage_manifest)
from pgx.engine.phenotype_normalization import normalize_profile

SYNTHETIC_MARKERS: Tuple[str, ...] = (
    "SYNTHETIC", "TEST ONLY", "NOT CLINICAL DATA", "NOT FOR REAL ASSESSMENT")

#: The same invented vocabulary WP-11 and WP-12 use, so one synthetic world
#: runs the whole way through instead of three.
GENE_1 = "GENE:TESTGENE1"
GENE_2 = "GENE:TESTGENE2"
GENE_3 = "GENE:TESTGENE3"
DRUG_1 = "DRUG:testdrug-alpha"
DRUG_2 = "DRUG:testdrug-beta"
UNKNOWN_DRUG = "DRUG:testdrug-omega"

#: A pinned canonical catalogue. Membership means the dataset contains the
#: entity and nothing else - it is the precondition for asking the coverage
#: question, never an answer to it.
SYNTHETIC_DRUG_CATALOGUE: Tuple[str, ...] = (DRUG_1, DRUG_2)
SYNTHETIC_GENE_CATALOGUE: Tuple[str, ...] = (GENE_1, GENE_2, GENE_3)

TEST_DECLARER = "TEST-coverage-declarer-1"
TEST_REVIEWER = "TEST-coverage-reviewer-1"
TEST_APPROVER = "TEST-coverage-approver-1"


def synthetic_approval(**overrides: Any) -> CoverageManifestApproval:
    values: Dict[str, Any] = {
        "declared_by": TEST_DECLARER,
        "reviewed_by": TEST_REVIEWER,
        "approved_by": TEST_APPROVER,
        "approved_at": "2099-01-04T10:00:00Z",
        "approval_reference": "TEST-COVERAGE-APPROVAL-1 (SYNTHETIC, TEST ONLY)",
    }
    values.update(overrides)
    return CoverageManifestApproval(**values)


def synthetic_evidence_resolver(known: Optional[Sequence[str]] = None):
    """A resolver over the WP-11 fixture's evidence uuids."""
    from tests.fixtures.wp11.synthetic import SYNTHETIC_EVIDENCE_UUIDS
    catalogue = frozenset(known if known is not None
                          else SYNTHETIC_EVIDENCE_UUIDS)
    return lambda reference: reference in catalogue


def synthetic_frozen_ruleset(destination: str, count: int = 2):
    """A WP-11 frozen ruleset, built through WP-11's own services.

    Returns ``(frozen_ruleset, definitions)``. The rules are keyed on
    ``GENE:TESTGENE1`` and ``GENE:TESTGENE2`` against ``DRUG:testdrug-alpha``,
    all on ``POOR``, which is what the default declarations below claim.
    """
    from pgx.rules.registry import FrozenRulesetRegistry
    from tests.fixtures.wp11.synthetic import frozen_ruleset
    root = os.path.dirname(destination)
    _service, _store, definitions, _result = frozen_ruleset(destination,
                                                            count=count)
    registry = FrozenRulesetRegistry(root)
    loaded = registry.load("PGX-RULESET-29991231-001")
    return loaded, definitions


def declarations_for(frozen, *, expected_extra_gene: bool = False,
                     drug: str = DRUG_1) -> Tuple[Dict[str, Any], ...]:
    """Coverage declarations matching a synthetic frozen ruleset.

    ``expected_extra_gene`` adds a gene to the expected scope that no rule
    covers, which is how a partially covered drug is expressed: the gap is
    visible only because somebody declared that the gene should have been
    considered.
    """
    axes = []
    genes = []
    for definition in frozen.rules():
        condition = definition.condition
        genes.append(condition.gene_canonical_key)
        for phenotype in condition.phenotype.values:
            axes.append({"gene_id": condition.gene_canonical_key,
                         "phenotype": phenotype.value})
    expected = sorted(set(genes))
    if expected_extra_gene:
        expected = sorted(set(expected) | {GENE_3})
    return ({
        "declaration_id": "TEST-COVERAGE-DECL-1",
        "drug_id": drug,
        "expected_gene_keys": tuple(expected),
        "supported_axes": tuple(axes),
        "declared_by": TEST_DECLARER,
        "declaration_provenance":
            "SYNTHETIC TEST ONLY: an invented scope for an invented drug, "
            "declared by a fixture and reviewed by nobody.",
    },)


def synthetic_manifest(frozen, *, expected_extra_gene: bool = False,
                       declarations=None, approval=None,
                       evidence_resolver=None):
    """A verified coverage manifest over a synthetic frozen ruleset."""
    return build_coverage_manifest(
        frozen_ruleset=frozen,
        declarations=(declarations if declarations is not None
                      else declarations_for(
                          frozen, expected_extra_gene=expected_extra_gene)),
        approval=approval or synthetic_approval(),
        evidence_resolver=(evidence_resolver if evidence_resolver is not None
                           else synthetic_evidence_resolver()))


def synthetic_profile(values: Optional[Mapping[str, Any]] = None,
                      profile_id: str = "TEST-COVERAGE-PROFILE-1"):
    """A WP-12 phenotype profile over the synthetic genes."""
    payload = dict(values if values is not None
                   else {GENE_1: "POOR", GENE_2: "POOR"})
    return normalize_profile(payload, profile_id=profile_id,
                             metadata={"markers": list(SYNTHETIC_MARKERS)})


def synthetic_conflict(drug: str = DRUG_1, gene: str = GENE_1,
                       phenotype: Phenotype = Phenotype.POOR,
                       **overrides: Any):
    from pgx.engine.coverage_models import SourceConflictSignal
    values: Dict[str, Any] = {
        "conflict_id": "TEST-CONFLICT-1",
        "drug_canonical_key": drug,
        "gene_canonical_key": gene,
        "phenotype": phenotype,
        "rule_ids": ("11111111-0000-4000-8000-000000000001",
                     "11111111-0000-4000-8000-000000000002"),
        "evidence_references": ("aaaaaaaa-0000-4000-8000-000000000001",),
        "provenance": "SYNTHETIC TEST ONLY: an invented disagreement.",
    }
    values.update(overrides)
    return SourceConflictSignal(**values)
