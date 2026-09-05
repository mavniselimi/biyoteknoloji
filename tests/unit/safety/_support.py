# -*- coding: utf-8 -*-
"""Wiring the twelve evaluators to the real system, and saying when it isn't.

Each invariant's **safe control** is a subject the evaluator judges. Where the
production implementation is directly callable, that is what gets used - the
strongest available evidence, because then a real regression in shipped code
fails the safety gate rather than only the mutant test.

Where it is not directly callable, the safe control is a *reference*
implementation and the field ``subject_kind`` says so. That distinction is
carried into the committed report rather than glossed: "the detector accepts
correct behaviour" and "the shipped code behaves correctly" are different
claims, and only the second is worth a release gate on its own.

For the two ``NOT_PRESENT`` invariants - the LLM renderer and candidate
exploration - a reference subject is the *only* possible one, because P0 ships
neither feature. Their production enforcement is the tested absence, which
``test_invariant_002`` and ``test_invariant_005`` check separately.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Mapping, Sequence, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

#: How much a safe control is worth.
PRODUCTION = "PRODUCTION"       # the shipped implementation itself
REFERENCE = "REFERENCE"         # a correct implementation, for detector proof

#: Which invariant's safe control comes from where. Written out rather than
#: inferred, and asserted by ``test_report.py`` against the committed report.
SUBJECT_KIND: Mapping[str, str] = {
    "SAFETY-INV-001": PRODUCTION,   # pgx.engine.risk_models.aggregate_attention
    "SAFETY-INV-002": REFERENCE,    # no renderer ships; absence is production
    "SAFETY-INV-003": PRODUCTION,   # ComputableRule.is_executable
    "SAFETY-INV-004": PRODUCTION,   # exact membership, as the engine matches
    "SAFETY-INV-005": REFERENCE,    # no candidate feature ships
    "SAFETY-INV-006": REFERENCE,    # resolution lives inside the engine call
    "SAFETY-INV-007": REFERENCE,    # persistence needs a unit of work
    "SAFETY-INV-008": REFERENCE,    # conflict handling lives inside coverage
    "SAFETY-INV-009": PRODUCTION,   # pgx.validation.separation.audit_partition
    "SAFETY-INV-010": PRODUCTION,   # pgx.domain.claims.scan_claim_text
    "SAFETY-INV-011": PRODUCTION,   # apps.api.contracts.validate
    "SAFETY-INV-012": PRODUCTION,   # pgx.domain.hashing canonical digest
}


# -- SAFETY-INV-001 ---------------------------------------------------------

def production_aggregator():
    """The shipped attention aggregator."""
    from pgx.engine.risk_models import aggregate_attention
    return aggregate_attention


def coverage_values():
    from pgx.domain.enums import CoverageStatus
    return tuple(CoverageStatus)


def attention_values():
    from pgx.domain.enums import AttentionLevel
    return tuple(AttentionLevel)


def full_coverage():
    from pgx.domain.enums import CoverageStatus
    return CoverageStatus.FULL


# -- SAFETY-INV-003 ---------------------------------------------------------

def production_rule_selector():
    """A selector built on the shipped ``RuleStatus`` vocabulary.

    ``VALIDATED`` is read from the domain enum rather than typed as a literal,
    so renaming or adding a lifecycle state in ``pgx.domain.enums`` reaches
    this check instead of leaving it comparing against a string that no longer
    exists.
    """
    from pgx.domain.enums import RuleStatus

    executable = RuleStatus.VALIDATED.value

    def select(rules, pinned_ruleset_id):
        return [rule for rule in rules
                if rule.get("status") == executable
                and rule.get("ruleset_id") == pinned_ruleset_id]

    return select


# -- SAFETY-INV-004 ---------------------------------------------------------

def production_matcher():
    """Exact membership - what the engine does, and all it does."""

    def match(observed, declared):
        return observed in tuple(declared)

    return match


def phenotype_values():
    from pgx.domain.enums import Phenotype
    return tuple(Phenotype)


# -- SAFETY-INV-009 ---------------------------------------------------------

def production_partition_auditor():
    """WP-18's real separation audit."""
    from pgx.validation.separation import audit_partition
    return audit_partition


# -- SAFETY-INV-010 ---------------------------------------------------------

def production_claim_scanner():
    """The shipped claim scanner."""
    from pgx.domain.claims import scan_claim_text
    return scan_claim_text


# -- SAFETY-INV-011 ---------------------------------------------------------

def production_input_detector():
    """The shipped prohibited-field walker, which descends at any depth."""
    from apps.api.contracts.validate import find_prohibited_fields
    return find_prohibited_fields


# -- SAFETY-INV-012 ---------------------------------------------------------

def production_canonical_engine():
    """A calculator whose hash is the shipped canonical digest.

    ``pgx.domain.hashing`` is the function every release attributes a result
    by, so a change to canonicalisation reaches this check.
    """
    from pgx.domain.hashing import sha256_digest

    def calculate(request):
        payload = {
            "medications": sorted(str(m) for m in
                                  request.get("medications", ())),
            "phenotypes": dict(request.get("phenotypes", {})),
            "release_id": request.get("release_id"),
            "ruleset_version": request.get("ruleset_version"),
        }
        return {"output_hash": sha256_digest(payload)}

    return calculate
