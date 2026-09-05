# -*- coding: utf-8 -*-
"""View models: immutable, complete, and incapable of deciding anything.

The assessment model is checked hardest, because it is the one whose omissions
would be invisible: a page missing a reason code looks finished.
"""

from __future__ import annotations

import dataclasses
import unittest

from apps.web.view_models.assessment import (ABSENT_MARKER,
                                             AssessmentPageModel,
                                             build_assessment_page)
from apps.web.view_models.base import (PageContext, StatusPair,
                                       build_page_context, build_status_pair)
from apps.web.view_models.pages import (MedicationChoice, ValidationBoardModel,
                                        build_error_page,
                                        build_expert_review_page,
                                        build_login_page,
                                        build_validation_board)
from apps.web.view_models.preservation import (FactPreservationError,
                                               PROTECTED_ASSESSMENT_FACTS,
                                               require_preserved,
                                               response_facts)
from pgx.domain.claims import canonical_clinical_warning
from tests.fixtures.wp13.synthetic import DRUG_1, GENE_1
from tests.fixtures.wp16.synthetic import create_request
from tests.fixtures.wp17.synthetic import (execution_context,
                                           synthetic_web_provider)
from tests.unit.web._support import synthetic_world

UNKNOWN_DRUG = "DRUG:unknown-medicine-x"


class _Assessed(unittest.TestCase):
    """One real assessment, calculated by the real engine."""

    MEDICATIONS = (DRUG_1, UNKNOWN_DRUG)

    def setUp(self):
        self.world = synthetic_world()
        self.addCleanup(self.world.close)
        self.provider = synthetic_web_provider(self.world)
        self.document = self.provider.client.create_assessment(
            create_request(medications=list(self.MEDICATIONS)),
            context=execution_context()).document
        self.model = build_assessment_page(self.document)


class TestImmutability(_Assessed):

    def test_the_model_is_frozen(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.model.output_hash = "sha256:" + "0" * 64

    def test_every_nested_model_is_frozen(self):
        medication = self.model.medications[0]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            medication.drug = "DRUG:something-else"
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.model.status.attention_code = "LOW"

    def test_collections_are_tuples(self):
        self.assertIsInstance(self.model.medications, tuple)
        self.assertIsInstance(self.model.observations, tuple)
        self.assertIsInstance(self.model.status.reason_codes, tuple)


class TestFactPreservation(_Assessed):

    def test_the_built_model_preserves_every_protected_fact(self):
        require_preserved(self.document, self.model)

    def test_the_projection_covers_the_declared_facts(self):
        projected = set(response_facts(self.document))
        self.assertEqual(projected, set(PROTECTED_ASSESSMENT_FACTS))

    def test_a_dropped_medication_is_detected(self):
        broken = dataclasses.replace(self.model,
                                     medications=self.model.medications[:1])
        with self.assertRaises(FactPreservationError):
            require_preserved(self.document, broken)

    def test_a_changed_hash_is_detected(self):
        broken = dataclasses.replace(self.model,
                                     output_hash="sha256:" + "0" * 64)
        with self.assertRaises(FactPreservationError) as caught:
            require_preserved(self.document, broken)
        self.assertEqual(caught.exception.differences, ("$.output_hash",))

    def test_a_dropped_reason_code_is_detected(self):
        status = self.model.status
        broken_status = StatusPair(
            attention_code=status.attention_code,
            attention_label=status.attention_label,
            coverage_code=status.coverage_code,
            coverage_label=status.coverage_label,
            reason_codes=status.reason_codes[:-1],
            reason_labels=status.reason_labels[:-1])
        broken = dataclasses.replace(self.model, status=broken_status)
        with self.assertRaises(FactPreservationError):
            require_preserved(self.document, broken)

    def test_a_reordered_medication_list_is_detected(self):
        """Reordering is not a presentation choice; it is a ranking."""
        broken = dataclasses.replace(
            self.model, medications=tuple(reversed(self.model.medications)))
        with self.assertRaises(FactPreservationError):
            require_preserved(self.document, broken)

    def test_the_refusal_names_locations_and_not_values(self):
        broken = dataclasses.replace(self.model,
                                     output_hash="sha256:" + "0" * 64)
        with self.assertRaises(FactPreservationError) as caught:
            require_preserved(self.document, broken)
        rendered = str(caught.exception)
        self.assertNotIn(self.model.output_hash, rendered)
        self.assertNotIn("0" * 64, rendered)


class TestNothingIsComputed(_Assessed):

    def test_medication_order_is_the_response_order(self):
        self.assertEqual([item.drug for item in self.model.medications],
                         [item["drug"] for item in
                          self.document["medications"]])

    def test_the_model_exposes_no_summary_or_score(self):
        names = set(AssessmentPageModel.__dataclass_fields__)
        for forbidden in ("score", "rank", "severity", "worst",
                          "highest_attention", "summary", "finding_count",
                          "risk"):
            with self.subTest(field=forbidden):
                self.assertNotIn(forbidden, names)

    def test_absent_governed_codes_stay_absent(self):
        for medication in self.model.medications:
            for finding in medication.findings:
                with self.subTest(rule=finding.rule_id):
                    self.assertIsNone(finding.effect_code)
                    self.assertIsNone(finding.explanation_code)
                    self.assertEqual(finding.effect_display, ABSENT_MARKER)
                    self.assertNotEqual(finding.effect_display, "")

    def test_axis_partitioning_filters_and_never_reorders(self):
        for medication in self.model.medications:
            recombined = (list(medication.evaluated_axes)
                          + list(medication.unevaluated_axes))
            with self.subTest(drug=medication.drug):
                self.assertEqual(sorted(item.gene for item in recombined),
                                 sorted(item.gene
                                        for item in medication.axes))


class TestAttentionAndCoverageArePaired(_Assessed):

    def test_the_overall_status_carries_both(self):
        self.assertTrue(self.model.status.attention_code)
        self.assertTrue(self.model.status.coverage_code)

    def test_every_medication_status_carries_both(self):
        for medication in self.model.medications:
            with self.subTest(drug=medication.drug):
                self.assertTrue(medication.status.attention_code)
                self.assertTrue(medication.status.coverage_code)

    def test_a_status_pair_without_coverage_cannot_be_built(self):
        with self.assertRaises(ValueError):
            StatusPair(attention_code="LOW", attention_label="x",
                       coverage_code="", coverage_label="",
                       reason_codes=(), reason_labels=())

    def test_a_status_pair_without_attention_cannot_be_built(self):
        with self.assertRaises(ValueError):
            StatusPair(attention_code="", attention_label="",
                       coverage_code="FULL", coverage_label="x",
                       reason_codes=(), reason_labels=())

    def test_every_reason_code_carries_a_governed_label(self):
        self.assertEqual(len(self.model.status.reason_codes),
                         len(self.model.status.reason_labels))
        for label in self.model.status.reason_labels:
            with self.subTest(label=label):
                self.assertTrue(label)
                self.assertNotEqual(label, label.upper())


class TestGovernedStatesSurvive(_Assessed):

    def test_not_assessed_is_preserved_and_labelled_as_such(self):
        unsupported = [item for item in self.model.medications
                       if item.drug == UNKNOWN_DRUG][0]
        self.assertEqual(unsupported.status.attention_code, "NOT_ASSESSED")
        self.assertIn("Değerlendirilmedi",
                      unsupported.status.attention_label)
        self.assertTrue(unsupported.status.is_not_assessed)

    def test_not_assessed_is_never_rendered_as_low_or_no_attention(self):
        for medication in self.model.medications:
            if medication.status.attention_code != "NOT_ASSESSED":
                continue
            label = medication.status.attention_label.lower()
            with self.subTest(drug=medication.drug):
                for forbidden in ("düşük", "low", "güvenli", "safe",
                                  "no active", "etkin dikkat bulgusu"):
                    self.assertNotIn(forbidden, label)

    def test_an_unsupported_medication_is_present_not_dropped(self):
        drugs = {item.drug for item in self.model.medications}
        self.assertEqual(drugs, set(self.MEDICATIONS))

    def test_partial_coverage_lists_its_reasons(self):
        self.assertEqual(self.model.status.coverage_code, "PARTIAL")
        self.assertTrue(self.model.status.reason_codes)
        self.assertTrue(self.model.status.is_partial)

    def test_unevaluated_axes_are_kept_with_their_reasons(self):
        covered = [item for item in self.model.medications
                   if item.drug == DRUG_1][0]
        self.assertTrue(covered.unevaluated_axes)
        for axis in covered.unevaluated_axes:
            with self.subTest(gene=axis.gene):
                self.assertTrue(axis.reason_codes)
                self.assertEqual(len(axis.reason_codes),
                                 len(axis.reason_labels))

    def test_evidence_references_become_internal_links(self):
        for medication in self.model.medications:
            for finding in medication.findings:
                with self.subTest(rule=finding.rule_id):
                    self.assertEqual(len(finding.evidence_references),
                                     len(finding.evidence_urls))
                    for url in finding.evidence_urls:
                        self.assertTrue(url.startswith("/evidence/"))


class TestSourceConflictIsPreserved(unittest.TestCase):
    """A conflicted axis keeps every reference. It never becomes a finding."""

    def test_conflict_references_survive_into_the_model(self):
        document = {
            "contract_version": "pgx-api-contract/1",
            "assessment_id": "11111111-1111-4111-8111-111111111111",
            "mode": "DEMO", "input_kind": "SYNTHETIC_PHENOTYPE_PROFILE",
            "case_id": None, "created_at": "2099-01-04T10:00:00+00:00",
            "input_hash": "sha256:" + "a" * 64,
            "output_hash": "sha256:" + "b" * 64,
            "coverage_result_hash": "sha256:" + "c" * 64,
            "status": {"attention": "NOT_ASSESSED",
                       "coverage": "SOURCE_CONFLICT",
                       "coverage_reason_codes": ["VALIDATED_RULES_CONFLICT"]},
            "medications": [{
                "drug": DRUG_1, "requested_value": DRUG_1,
                "status": {"attention": "NOT_ASSESSED",
                           "coverage": "SOURCE_CONFLICT",
                           "coverage_reason_codes":
                               ["VALIDATED_RULES_CONFLICT"]},
                "axis_count": 1, "conflicted_axis_count": 1,
                "axes": [{"gene": GENE_1, "drug": DRUG_1,
                          "coverage": "SOURCE_CONFLICT",
                          "coverage_reason_codes":
                              ["VALIDATED_RULES_CONFLICT"],
                          "observed_phenotype": "POOR",
                          "observation_state": "NORMALIZED",
                          "declaration_id": "TEST-DECL-1",
                          "evidence_references": [],
                          "conflict_references": ["TEST-CONFLICT-1",
                                                  "TEST-CONFLICT-2"]}],
                "findings": []}],
            "observations": [{"gene": GENE_1, "status": "NORMALIZED",
                              "phenotype": "POOR", "reason_code": None}],
            "release": {}, "warnings": [], "clinical_warning": "x",
            "persisted": True,
        }
        model = build_assessment_page(document)
        axis = model.medications[0].axes[0]
        self.assertEqual(axis.conflict_references,
                         ("TEST-CONFLICT-1", "TEST-CONFLICT-2"))
        self.assertTrue(axis.is_conflicted)
        self.assertTrue(model.status.is_conflicted)
        self.assertEqual(model.medications[0].findings, ())


class TestMalformedResponsesAreRefused(_Assessed):

    def test_a_response_missing_its_identity_is_refused(self):
        broken = dict(self.document)
        broken["assessment_id"] = None
        with self.assertRaises(Exception):
            build_assessment_page(broken)

    def test_a_response_missing_its_output_hash_is_refused(self):
        broken = dict(self.document)
        broken["output_hash"] = None
        with self.assertRaises(Exception):
            build_assessment_page(broken)

    def test_a_response_with_an_ungoverned_attention_code_is_refused(self):
        broken = dict(self.document)
        broken["status"] = dict(broken["status"], attention="EXTREMELY_HIGH")
        with self.assertRaises(Exception):
            build_assessment_page(broken)


class TestThePageFrame(unittest.TestCase):

    def test_the_warning_is_the_canonical_one(self):
        context = build_page_context(route_name="web.home")
        self.assertEqual(context.warning, canonical_clinical_warning("tr"))

    def test_a_route_cannot_supply_its_own_warning(self):
        with self.assertRaises(ValueError):
            PageContext(locale="tr", title="x", route_name="web.home",
                        environment="", warning="Kısa bir uyarı.",
                        warning_heading="h", navigation=(), request_id="",
                        asset_version="1")

    def test_a_page_without_a_warning_cannot_be_built(self):
        with self.assertRaises(ValueError):
            PageContext(locale="tr", title="x", route_name="web.home",
                        environment="", warning="", warning_heading="h",
                        navigation=(), request_id="", asset_version="1")

    def test_navigation_marks_exactly_one_current_page(self):
        context = build_page_context(route_name="web.cases")
        current = [item for item in context.navigation if item.is_current]
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0].name, "web.cases")


class TestTheHonestShells(unittest.TestCase):

    def test_the_validation_board_reports_null_not_zero(self):
        board = build_validation_board(development_case_count=7)
        self.assertEqual(board.development_case_count, 7)
        self.assertIsNone(board.internal_holdout_count)
        self.assertIsNone(board.expert_holdout_count)
        self.assertIsNone(board.validation_run_count)

    def test_the_board_has_no_field_for_a_rate(self):
        names = set(ValidationBoardModel.__dataclass_fields__)
        for forbidden in ("pass_rate", "concordance", "accuracy",
                          "percentage", "ratio", "score"):
            with self.subTest(field=forbidden):
                self.assertNotIn(forbidden, names)

    def test_a_non_zero_holdout_count_cannot_be_recorded(self):
        with self.assertRaises(ValueError):
            ValidationBoardModel(
                development_case_count=7, internal_holdout_count=5,
                expert_holdout_count=None, validation_run_count=None,
                architecture_note="a", no_run_note="b", metrics_note="c",
                separation_note="d", no_conclusion_note="e", blockers=())

    def test_the_login_shell_offers_no_working_sign_out(self):
        model = build_login_page()
        self.assertFalse(model.authentication_configured)
        self.assertFalse(model.logout_available)

    def test_no_medication_can_be_preselected(self):
        with self.assertRaises(ValueError):
            MedicationChoice(canonical_key="DRUG:x", display_name="x",
                             declared=True, selected=True)

    def test_the_expert_page_preserves_the_phase_order(self):
        """``superseded_by`` left this assertion at WP-22 because WP-22 is
        what superseded it. The order it guarded is unchanged."""
        page = build_expert_review_page("TEST-CASE-1")
        self.assertEqual(len(page.phases), 3)
        self.assertEqual(page.superseded_by, "")
        self.assertTrue(page.phases[0][0].startswith("1."))
        self.assertTrue(page.phases[1][0].startswith("2."))
        self.assertTrue(page.phases[2][0].startswith("3."))

    def test_a_blinded_expert_page_cannot_hold_a_result(self):
        """The structural guarantee, asserted where the model is built.

        A page that is blinded and carries a result is the one defect this
        work package exists to prevent, so it raises rather than rendering.
        """
        from apps.web.view_models.pages import (ExpertReviewPageModel,
                                                RevealedResultSummary)
        result = RevealedResultSummary(
            attention_level="HIGH", coverage_status="FULL",
            coverage_reason="", firing_rule_id="", finding_count=1,
            traceable_finding_count=1, output_hash="sha256:" + "0" * 64,
            revealed_at="2026-01-01T00:00:00Z",
            pinned_expectation_hash="sha256:" + "1" * 64)
        with self.assertRaises(ValueError):
            ExpertReviewPageModel(
                case_id="TEST-CASE-1", state="ASSIGNED", blinded=True,
                available=True, forms_enabled=False, unavailable_note="",
                order_note="", no_disclosure_note="", blinded_note="",
                phases=(), release_public_id="", protocol_version="",
                protocol_approved=False, protocol_note="", result=result)

    def test_an_enabled_form_requires_a_csrf_token(self):
        """A control that cannot submit safely is worse than none: a reviewer
        would fill it in and believe it was recorded."""
        from apps.web.view_models.pages import ExpertReviewPageModel
        with self.assertRaises(ValueError):
            ExpertReviewPageModel(
                case_id="TEST-CASE-1", state="ASSIGNED", blinded=True,
                available=True, forms_enabled=True, unavailable_note="",
                order_note="", no_disclosure_note="", blinded_note="",
                phases=(), release_public_id="", protocol_version="",
                protocol_approved=True, protocol_note="", csrf_token=None)

    def test_the_error_model_has_no_field_for_exception_text(self):
        from apps.web.view_models.pages import ErrorPageModel
        names = set(ErrorPageModel.__dataclass_fields__)
        for forbidden in ("exception", "traceback", "detail", "message",
                          "stack"):
            with self.subTest(field=forbidden):
                self.assertNotIn(forbidden, names)

    def test_the_error_model_carries_the_api_code(self):
        model = build_error_page("ASSESSMENT_NOT_FOUND",
                                 request_id="11111111-1111-4111-8111-111111111111")
        self.assertEqual(model.code, "ASSESSMENT_NOT_FOUND")
        self.assertEqual(model.status, 404)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
