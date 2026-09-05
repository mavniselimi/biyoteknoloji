# -*- coding: utf-8 -*-
"""SYNTHETIC WP-15 reporting fixtures. TEST ONLY. NOT CLINICAL DATA.

NOT FOR REAL ASSESSMENT. Every profile, medication, finding and report built
here is invented so that the reporting pipeline can be exercised end to end
while no real assessment exists. Nothing here was reviewed by anybody, and
none of it is a statement about any medicine.

Two things in this file exist to be *refused*, and both are shaped so they
cannot escape.

**The adversarial fixtures.** :data:`ADVERSARIAL_TEXTS` holds sentences a
report must never publish - a diagnosis, a dose change, a suitability claim,
"low risk" for something nobody assessed. They are strings in a test fixture,
handed to the claim gate by tests that assert it blocks them. No template, no
label table and no controlled statement contains any of them, and a boundary
test asserts that.

**The forged report.** Helpers here can build a report whose facts have been
tampered with, so the fact-preservation validator can be shown to refuse one.
They are only reachable from tests, and each returns a value a caller has to
pass explicitly into a validator.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from tests.fixtures.wp13.synthetic import (DRUG_1, DRUG_2, GENE_1, GENE_2,
                                           GENE_3, UNKNOWN_DRUG)

SYNTHETIC_MARKERS: Tuple[str, ...] = (
    "SYNTHETIC", "TEST ONLY", "NOT CLINICAL DATA", "NOT FOR REAL ASSESSMENT")

#: A profile that produces every interesting shape at once: two covered axes,
#: one gene the ruleset does not cover, and one value normalisation refuses.
MIXED_PHENOTYPES: Mapping[str, str] = {
    GENE_1: "POOR", GENE_2: "POOR", GENE_3: "not-a-phenotype-token"}

#: Medications that produce a covered case, a partially covered case and one
#: the pinned dataset does not contain.
MIXED_MEDICATIONS: Tuple[str, ...] = (DRUG_1, DRUG_2, UNKNOWN_DRUG)

#: Values chosen because rendering them naively breaks the document: a
#: Markdown heading, a table escape, an HTML element, a link, a fenced block
#: and a control character.
INJECTION_CASE_IDS: Tuple[Tuple[str, str], ...] = (
    ("heading", "# Rapor onaylandi"),
    ("table", "A | B | C"),
    ("html", "<script>alert(1)</script>"),
    ("link", "[tikla](https://example.invalid)"),
    ("fence", "```\nrm -rf /\n```"),
    ("emphasis", "**GUVENLI**"),
    ("control", "case\x07\x00id"),
    ("newline", "line one\n# line two"),
    ("blockquote", "> alinti"),
    ("list", "- madde"),
)

#: Sentences a report must never publish. Each names the category the WP-00
#: scanner is expected to catch it under. They live here, in a test fixture,
#: and nowhere in ``pgx/``.
ADVERSARIAL_TEXTS: Tuple[Tuple[str, str, str], ...] = (
    ("diagnosis_tr", "DIAGNOSIS",
     "Bu profile bakarak hastaya teshis konulabilir."),
    ("diagnosis_en", "DIAGNOSIS",
     "This report diagnoses the patient with a metabolic disorder."),
    ("suitability_tr", "CANDIDATE_PREFERENCE",
     "Bu ilac bu hasta icin daha uygun bir secenektir."),
    ("suitability_en", "CANDIDATE_PREFERENCE",
     "This medication is more suitable for this patient."),
    ("treatment_selection_tr", "TREATMENT_SELECTION",
     "Bu ilac yerine digeri kullanilmalidir."),
    ("treatment_selection_en", "TREATMENT_SELECTION",
     "Use warfarin instead of clopidogrel for this profile."),
    ("dose_tr", "DOSING",
     "Dozu yariya indirin."),
    ("dose_en", "DOSING",
     "The dose should be reduced for this patient."),
    ("candidate_safety_tr", "SAFETY_ASSURANCE",
     "Bu ilac bu profil icin tamamen guvenlidir."),
    ("candidate_safety_en", "SAFETY_ASSURANCE",
     "This drug is completely safe for this profile."),
    ("false_reassurance_tr", "FALSE_REASSURANCE",
     "Degerlendirilmeyen eksenler dusuk riskli kabul edilir."),
    ("false_reassurance_en", "FALSE_REASSURANCE",
     "Every unevaluated axis carries low risk."),
    ("validation_overclaim_en", "VALIDATION_OVERCLAIM",
     "This system is clinically validated and approved for clinical use."),
    ("clinical_decision_en", "CLINICAL_DECISION_SUBSTITUTION",
     "This report replaces the clinician judgement for this case."),
    ("real_data_en", "REAL_PATIENT_DATA",
     "We analysed the patient's genotype directly from their VCF."),
    ("prescription_en", "PRESCRIPTION",
     "Prescribe the alternative agent listed above."),
)

#: The same claims hidden inside Markdown or HTML rather than plain prose. A
#: gate that scanned only the visible text of a rendered page would miss them,
#: which is why the gate scans the document source.
HIDDEN_CLAIM_TEXTS: Tuple[Tuple[str, str], ...] = (
    ("html_comment", "<!-- This drug is completely safe for this profile. -->"),
    ("html_attribute",
     '<span title="The dose should be reduced for this patient.">x</span>'),
    ("markdown_link_title",
     '[ref](https://example.invalid "This drug is completely safe.")'),
    ("markdown_emphasis", "*Every unevaluated axis carries low risk.*"),
    ("table_cell", "| status | Every unevaluated axis carries low risk. |"),
    ("code_fence",
     "```\nThis system is clinically validated and approved for clinical "
     "use.\n```"),
)


#: Claims the published scanner provably does **not** catch, with why.
#:
#: These are here because pretending the scanner is complete would be the
#: dangerous choice. Its safe-context suppression is lexical and broad: an
#: English sentence containing "not" suppresses negatable matches inside it,
#: so "axes that were not assessed carry low risk" - a sentence that asserts
#: exactly the thing SAFETY-INV-001 forbids - passes a scan clean.
#:
#: The structural controls are what actually stop these: a WP-15 report
#: contains no free text at all. Every sentence comes from a fixed table,
#: every label from a fixed lookup, and the report types have nowhere to put
#: an authored sentence. The tests assert both halves - that the scanner
#: misses these, and that nothing in the reporting package could emit them.
SCANNER_BLIND_SPOTS: Tuple[Tuple[str, str, str], ...] = (
    ("negation_suppression_en",
     "Axes that were not assessed carry low risk.",
     "the sentence contains the English negation marker 'not', which "
     "suppresses negatable matches inside it"),
    ("negation_suppression_paraphrase_en",
     "There is no reason for concern about the axes we could not evaluate.",
     "contains 'no' and 'not'; also phrased outside every published pattern"),
    ("unpatterned_paraphrase_en",
     "Nothing here would give a prescriber pause.",
     "a reassurance phrased outside every published pattern"),
    ("unpatterned_paraphrase_tr",
     "Bu profilde endise gerektiren bir sey gorunmuyor.",
     "a Turkish reassurance phrased outside every published pattern"),
)


def report_world(**kwargs):
    """A whole synthetic governed world with one stored assessment.

    Returns the WP-14 synthetic world; the caller closes it. Built through
    each work package's own services rather than hand-assembled, so what the
    reporting tests exercise is the real read model and not a shape
    resembling it.
    """
    from tests.unit.application._assessment_support import (
        SyntheticAssessmentWorld)
    return SyntheticAssessmentWorld(**kwargs)


def stored_read_model(world, *, medications: Sequence[str] = MIXED_MEDICATIONS,
                      phenotypes: Optional[Mapping[str, Any]] = None,
                      case_id: Optional[str] = "TEST-CASE-1"):
    """Execute one synthetic assessment and return its lossless read model."""
    result = world.execute(
        medications=tuple(medications),
        phenotypes=dict(MIXED_PHENOTYPES if phenotypes is None
                        else phenotypes),
        case_id=case_id)
    return world.store.read_model(result.assessment_id)


def canonical_result(world, **kwargs):
    """The canonical fact set for one synthetic assessment."""
    from pgx.reporting.models import canonical_result_from_read_model
    return canonical_result_from_read_model(stored_read_model(world, **kwargs))


def structured_report(world, *, locale: str = "tr", **kwargs):
    """One synthetic structured report."""
    from pgx.reporting.structured import build_structured_report
    return build_structured_report(canonical_result(world, **kwargs),
                                   locale=locale)


def produced_report(world, *, locale: str = "tr", directory=None, **kwargs):
    """One synthetic report, through the whole service pipeline."""
    from pgx.application.report_service import ReportService
    return ReportService().render_synthetic(
        stored_read_model(world, **kwargs), locale=locale,
        directory=directory)
