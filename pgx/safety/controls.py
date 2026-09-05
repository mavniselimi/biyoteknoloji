# -*- coding: utf-8 -*-
"""The negative-control catalogue: what unsafe looks like, per invariant.

A safety check that has never rejected anything is indistinguishable from a
safety check that does nothing. Every one of the twelve invariants therefore
carries at least one **negative control** - a deliberately unsafe case that the
*same evaluator* must reject with a *named* code.

Two rules make these worth having, and both are enforced by tests:

**The mutant goes through the real gate.** Asserting that a fixture contains
the string "safety score" proves something about the fixture. It proves nothing
about the detector. Each control here is passed to the evaluator whose success
is being claimed, and the expected refusal code must come back.

**Nothing on disk is modified.** These are in-memory doubles and injected
unsafe implementations under ``tests/fixtures/wp20/``. A mutation test that
edited production source would leave the repository broken if it were
interrupted, and would make the suite's result depend on the order it ran in.

The catalogue is data, separate from the fixtures that realise it, so that a
missing fixture is a *detected* registry fault rather than a control that
silently disappears.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Tuple

from pgx.safety.vocabulary import ControlKind, InvariantId

__all__ = [
    "CONTROL_CATALOGUE_VERSION",
    "NegativeControl",
    "NEGATIVE_CONTROLS",
    "controls_for",
    "controls_by_id",
]

CONTROL_CATALOGUE_VERSION = "pgx-wp20-negative-controls/1"


@dataclass(frozen=True)
class NegativeControl:
    """One deliberately unsafe case, and what must happen to it."""

    control_id: str
    invariant_id: InvariantId
    #: What is unsafe about it, in one line a reviewer can check.
    description: str
    #: The stable code the evaluator must return. A CI job keys on this, so a
    #: reworded message may change and this may not.
    expected_refusal_code: str
    #: Where the fixture lives. Checked to exist; a control naming a fixture
    #: nobody wrote is a registry error.
    fixture: str
    kind: ControlKind = ControlKind.NEGATIVE
    #: The legacy defect this control reproduces, where there is one.
    legacy_bug: str = ""

    def as_document(self) -> Dict[str, Any]:
        return {
            "control_id": self.control_id,
            "description": self.description,
            "expected_refusal_code": self.expected_refusal_code,
            "fixture": self.fixture,
            "invariant_id": self.invariant_id.value,
            "kind": self.kind.value,
            "legacy_bug": self.legacy_bug,
        }


_F = "tests.fixtures.wp20"

NEGATIVE_CONTROLS: Tuple[NegativeControl, ...] = (
    # -- SAFETY-INV-001 : absence must never read as reassurance -------------
    NegativeControl(
        "NC-INV-001-ABSENCE-MAPPED-TO-LOW", InvariantId.INV_001,
        "an aggregation that maps an unassessed axis to LOW, exactly as the "
        "legacy engine's 'Dusuk / uyari yok' did",
        "SAFETY_FALSE_REASSURANCE", _F + ".unsafe_engine",
        legacy_bug="LEGACY-BUG-002"),
    NegativeControl(
        "NC-INV-001-NOT-ASSESSED-IN-MAXIMUM", InvariantId.INV_001,
        "an aggregation that treats NOT_ASSESSED as a level and includes it in "
        "the attention maximum, making absence comparable to LOW",
        "SAFETY_FALSE_REASSURANCE", _F + ".unsafe_engine"),

    # -- SAFETY-INV-002 : an LLM must not alter a calculated fact ------------
    NegativeControl(
        "NC-INV-002-RENDERER-CHANGES-ATTENTION", InvariantId.INV_002,
        "a test-only renderer whose narration reports a different attention "
        "level than the structured report it was given",
        "SAFETY_LLM_ALTERED_FACT", _F + ".unsafe_renderer"),
    NegativeControl(
        "NC-INV-002-RENDERER-INVENTS-DOSE", InvariantId.INV_002,
        "a renderer that introduces a dose the deterministic report never "
        "contained",
        "SAFETY_LLM_ALTERED_FACT", _F + ".unsafe_renderer"),
    NegativeControl(
        "NC-INV-002-RENDERER-DROPS-VERSION", InvariantId.INV_002,
        "a renderer that omits the release/version metadata, breaking the "
        "traceability the report exists to carry",
        "SAFETY_LLM_ALTERED_FACT", _F + ".unsafe_renderer"),

    # -- SAFETY-INV-003 : only validated pinned rules execute ----------------
    NegativeControl(
        "NC-INV-003-DRAFT-RULE-FIRES", InvariantId.INV_003,
        "a ruleset containing a DRAFT rule that participates in a calculation",
        "SAFETY_UNVALIDATED_RULE_EXECUTED", _F + ".unsafe_ruleset",
        legacy_bug="LEGACY-BUG-006"),
    NegativeControl(
        "NC-INV-003-DEPRECATED-RULE-FIRES", InvariantId.INV_003,
        "a DEPRECATED rule that still produces a finding",
        "SAFETY_UNVALIDATED_RULE_EXECUTED", _F + ".unsafe_ruleset"),
    NegativeControl(
        "NC-INV-003-UNPINNED-RULESET-ACCEPTED", InvariantId.INV_003,
        "a ruleset that is not the pinned active one being accepted for "
        "assessment",
        "SAFETY_UNVALIDATED_RULE_EXECUTED", _F + ".unsafe_ruleset"),

    # -- SAFETY-INV-004 : exact phenotype matching ---------------------------
    NegativeControl(
        "NC-INV-004-PREFIX-MATCHER", InvariantId.INV_004,
        "a matcher that accepts RAPID for a rule declaring ULTRARAPID because "
        "one string is a prefix of the other",
        "SAFETY_PHENOTYPE_CROSS_MATCH", _F + ".unsafe_matcher",
        legacy_bug="LEGACY-BUG-001"),
    NegativeControl(
        "NC-INV-004-SYNONYM-TABLE", InvariantId.INV_004,
        "a synonym table that treats RAPID and ULTRARAPID as equivalent",
        "SAFETY_PHENOTYPE_CROSS_MATCH", _F + ".unsafe_matcher"),
    NegativeControl(
        "NC-INV-004-ORDINAL-PROXIMITY", InvariantId.INV_004,
        "a matcher that accepts an adjacent phenotype by ordinal distance",
        "SAFETY_PHENOTYPE_CROSS_MATCH", _F + ".unsafe_matcher"),

    # -- SAFETY-INV-005 : no candidate preference ----------------------------
    NegativeControl(
        "NC-INV-005-SAFETY-SCORE", InvariantId.INV_005,
        "a candidate list carrying a 0-100 clinical suitability score, the "
        "legacy ranking that mixed data availability with preferability",
        "SAFETY_CANDIDATE_PREFERENCE", _F + ".unsafe_candidates",
        legacy_bug="LEGACY-BUG-009"),
    NegativeControl(
        "NC-INV-005-ORDERED-BY-ATTENTION", InvariantId.INV_005,
        "a candidate list ordered by attention level, which reads as a ranking "
        "whatever the disclaimer says",
        "SAFETY_CANDIDATE_PREFERENCE", _F + ".unsafe_candidates"),
    NegativeControl(
        "NC-INV-005-PREFERRED-LABEL", InvariantId.INV_005,
        "output labelling a candidate safer, preferred, suitable or "
        "recommended, in Turkish or English",
        "SAFETY_CANDIDATE_PREFERENCE", _F + ".unsafe_candidates"),

    # -- SAFETY-INV-006 : findings carry resolvable evidence -----------------
    NegativeControl(
        "NC-INV-006-DANGLING-EVIDENCE-REFERENCE", InvariantId.INV_006,
        "a finding citing an evidence identifier that resolves to nothing",
        "SAFETY_EVIDENCE_NOT_RESOLVABLE", _F + ".unsafe_evidence",
        legacy_bug="LEGACY-BUG-005"),
    NegativeControl(
        "NC-INV-006-FINDING-WITHOUT-EVIDENCE", InvariantId.INV_006,
        "a finding emitted with an empty evidence reference list",
        "SAFETY_EVIDENCE_NOT_RESOLVABLE", _F + ".unsafe_evidence"),
    NegativeControl(
        "NC-INV-006-EVIDENCE-OUTSIDE-PINNED-DATASET", InvariantId.INV_006,
        "a finding whose evidence exists, but in a dataset version other than "
        "the pinned one",
        "SAFETY_EVIDENCE_NOT_RESOLVABLE", _F + ".unsafe_evidence"),

    # -- SAFETY-INV-007 : complete release bundle before persistence ---------
    NegativeControl(
        "NC-INV-007-MISSING-RELEASE-FIELD", InvariantId.INV_007,
        "persistence attempted with each release/version field omitted in "
        "turn, rather than as a set",
        "SAFETY_RELEASE_BUNDLE_INCOMPLETE", _F + ".unsafe_persistence",
        legacy_bug="LEGACY-BUG-007"),
    NegativeControl(
        "NC-INV-007-MISSING-INPUT-HASH", InvariantId.INV_007,
        "persistence attempted without the canonical input hash",
        "SAFETY_RELEASE_BUNDLE_INCOMPLETE", _F + ".unsafe_persistence"),
    NegativeControl(
        "NC-INV-007-MISSING-OUTPUT-HASH", InvariantId.INV_007,
        "persistence attempted without the output hash",
        "SAFETY_RELEASE_BUNDLE_INCOMPLETE", _F + ".unsafe_persistence"),
    NegativeControl(
        "NC-INV-007-PARTIAL-PERSISTENCE", InvariantId.INV_007,
        "a store that commits the assessment row and abandons its findings, "
        "leaving a result whose trustworthy half cannot be told from the rest",
        "SAFETY_RELEASE_BUNDLE_INCOMPLETE", _F + ".unsafe_persistence"),

    # -- SAFETY-INV-008 : conflict must stay visible -------------------------
    NegativeControl(
        "NC-INV-008-CONFLICT-TAKES-LOWER-LEVEL", InvariantId.INV_008,
        "conflicting validated rules resolved by taking the lower attention "
        "level, the most reassuring possible answer",
        "SAFETY_CONFLICT_COLLAPSED", _F + ".unsafe_conflict"),
    NegativeControl(
        "NC-INV-008-CONFLICT-AVERAGED", InvariantId.INV_008,
        "conflicting levels averaged into a middle value that neither rule "
        "supports",
        "SAFETY_CONFLICT_COLLAPSED", _F + ".unsafe_conflict"),
    NegativeControl(
        "NC-INV-008-CONFLICTING-RULE-DROPPED", InvariantId.INV_008,
        "the disagreeing rule silently discarded to produce a clean answer",
        "SAFETY_CONFLICT_COLLAPSED", _F + ".unsafe_conflict"),

    # -- SAFETY-INV-009 : partitions must not overlap ------------------------
    NegativeControl(
        "NC-INV-009-ID-IN-TWO-ROLES", InvariantId.INV_009,
        "one case identifier appearing as both DEVELOPMENT and EXPERT_HOLDOUT",
        "SAFETY_PARTITION_OVERLAP", _F + ".unsafe_partition"),
    NegativeControl(
        "NC-INV-009-CONTENT-DUPLICATE-ACROSS-PARTITIONS", InvariantId.INV_009,
        "two different identifiers carrying identical content across the "
        "development/holdout line",
        "SAFETY_PARTITION_OVERLAP", _F + ".unsafe_partition"),
    NegativeControl(
        "NC-INV-009-DERIVATION-FAMILY-SPLIT", InvariantId.INV_009,
        "one derivation family split across development and holdout - which "
        "neither an identifier nor a content check would catch",
        "SAFETY_PARTITION_OVERLAP", _F + ".unsafe_partition"),

    # -- SAFETY-INV-010 : prohibited claims block release --------------------
    NegativeControl(
        "NC-INV-010-REPORT-CARRIES-RECOMMENDATION", InvariantId.INV_010,
        "a deterministic report body carrying a treatment recommendation",
        "SAFETY_PROHIBITED_CLAIM", _F + ".unsafe_text",
        legacy_bug="LEGACY-BUG-012"),
    NegativeControl(
        "NC-INV-010-API-STRING-CARRIES-DOSE", InvariantId.INV_010,
        "an API user-facing string carrying dosing language",
        "SAFETY_PROHIBITED_CLAIM", _F + ".unsafe_text"),
    NegativeControl(
        "NC-INV-010-TEMPLATE-CARRIES-REASSURANCE", InvariantId.INV_010,
        "a rendered template asserting that no finding means the medication is "
        "safe",
        "SAFETY_PROHIBITED_CLAIM", _F + ".unsafe_text"),

    # -- SAFETY-INV-011 : no real patient or genomic data --------------------
    NegativeControl(
        "NC-INV-011-NESTED-GENOTYPE-FIELD", InvariantId.INV_011,
        "a genotype field buried several levels deep in a request, where a "
        "top-level-only check would miss it",
        "SAFETY_REAL_PATIENT_DATA", _F + ".unsafe_input"),
    NegativeControl(
        "NC-INV-011-PATIENT-IDENTIFIER", InvariantId.INV_011,
        "a direct patient identifier - name, MRN, date of birth",
        "SAFETY_REAL_PATIENT_DATA", _F + ".unsafe_input"),
    NegativeControl(
        "NC-INV-011-RAW-SEQUENCING-PAYLOAD", InvariantId.INV_011,
        "a VCF/FASTQ/BAM payload or a star-allele diplotype",
        "SAFETY_REAL_PATIENT_DATA", _F + ".unsafe_input"),
    NegativeControl(
        "NC-INV-011-PILOT-MODE-REQUESTED", InvariantId.INV_011,
        "an operation requesting PILOT mode, which is disabled in P0",
        "SAFETY_REAL_PATIENT_DATA", _F + ".unsafe_input"),

    # -- SAFETY-INV-012 : determinism ----------------------------------------
    NegativeControl(
        "NC-INV-012-SHUFFLED-INPUT-CHANGES-OUTPUT", InvariantId.INV_012,
        "an engine whose output hash depends on the order the medications "
        "arrived in",
        "SAFETY_NON_DETERMINISTIC_RESULT", _F + ".unsafe_determinism",
        legacy_bug="LEGACY-BUG-007"),
    NegativeControl(
        "NC-INV-012-MID-RUN-RELEASE-CHANGE", InvariantId.INV_012,
        "a release bundle that changes between two calculations of the same "
        "input, so neither result can be attributed",
        "SAFETY_NON_DETERMINISTIC_RESULT", _F + ".unsafe_determinism"),
    NegativeControl(
        "NC-INV-012-WALL-CLOCK-IN-OUTPUT", InvariantId.INV_012,
        "wall-clock time inside the hashed output, which makes two identical "
        "runs disagree",
        "SAFETY_NON_DETERMINISTIC_RESULT", _F + ".unsafe_determinism"),
)


def controls_by_id() -> Mapping[str, NegativeControl]:
    return {control.control_id: control for control in NEGATIVE_CONTROLS}


def controls_for(invariant_id: InvariantId) -> Tuple[NegativeControl, ...]:
    """Every negative control belonging to one invariant."""
    return tuple(control for control in NEGATIVE_CONTROLS
                 if control.invariant_id is invariant_id)
