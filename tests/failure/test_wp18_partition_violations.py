# -*- coding: utf-8 -*-
"""Ways somebody could break the validation partition, and the refusals.

``tests/failure`` holds the tests whose job is to be refused. This module is
the WP-18 entry: each case below is a plausible mistake - not a contrived one -
and the assertion is that it does not work.

The mistakes are plausible on purpose. Nobody sets out to leak a holdout; they
copy a case to save typing, or rename one because the old name was confusing,
or reach for the demo profiles because they are the cases that already exist.
"""

from __future__ import annotations

import unittest

from pgx.validation.cases import (Provenance, RestrictedPayload,
                                  ValidationCaseId, ValidationCaseMetadata)
from pgx.validation.compatibility import UNPINNED
from pgx.validation.errors import (ProvenanceError, SeparationError,
                                   ValidationCaseError, VisibilityError)
from pgx.validation.separation import audit_partition, require_separation
from pgx.validation.vocabulary import (DataClassification, ValidationCaseRole,
                                       VisibilityLevel)
from tests.fixtures.wp18.synthetic import (NO_PII, NOW, case, content,
                                           development_case,
                                           internal_holdout_case, provenance)


class TestTheDemoProfilesCannotBecomeHoldout(unittest.TestCase):
    """The most likely mistake, because those cases already exist."""

    def test_a_wp17_case_relabelled_as_holdout_is_refused(self):
        from pgx.validation.catalog import development_cases
        import os

        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        first = development_cases(root)[0]
        with self.assertRaises(ProvenanceError):
            ValidationCaseMetadata(
                case_id=ValidationCaseId("PGX-VAL-INT-STOLEN"),
                role=ValidationCaseRole.INTERNAL_HOLDOUT,
                classification=first.classification,
                provenance=first.provenance,
                content_fingerprint=first.content_fingerprint,
                no_pii_assertion=first.no_pii_assertion,
                created_at=first.created_at,
                compatibility=first.compatibility)

    def test_copying_the_content_into_a_new_holdout_is_caught(self):
        """Fresh identifier, fresh provenance, same case."""
        from pgx.validation.catalog import development_cases
        import os

        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        cases = development_cases(root)
        copied = ValidationCaseMetadata(
            case_id=ValidationCaseId("PGX-VAL-INT-COPIED"),
            role=ValidationCaseRole.INTERNAL_HOLDOUT,
            classification=DataClassification.SYNTHETIC,
            provenance=provenance(development=False,
                                  source="TEST-INDEPENDENT-SOURCE"),
            content_fingerprint=cases[1].content_fingerprint,
            no_pii_assertion=NO_PII, created_at=NOW,
            compatibility=UNPINNED("1.0.0"))
        audit = audit_partition(list(cases) + [copied])
        self.assertIn("CONTENT_DUPLICATE_ACROSS_PARTITIONS",
                      audit.issue_codes)


class TestARenameIsNotIndependence(unittest.TestCase):

    def test_a_new_identifier_over_old_content_is_caught(self):
        body = content()
        with self.assertRaises(SeparationError):
            require_separation([
                case("PGX-VAL-DEV-ORIG", ValidationCaseRole.DEVELOPMENT,
                     body=body, prov=provenance(development=True)),
                case("PGX-VAL-INT-RENAMED",
                     ValidationCaseRole.INTERNAL_HOLDOUT, body=body,
                     prov=provenance(development=False,
                                     source="TEST-OTHER-SOURCE"))])

    def test_a_new_title_over_old_content_is_caught(self):
        """Display text has no vote. Content decides."""
        body = content()
        left = case("PGX-VAL-DEV-TITLED", ValidationCaseRole.DEVELOPMENT,
                    body=body, prov=provenance(development=True))
        right = case("PGX-VAL-INT-TITLED", ValidationCaseRole.INTERNAL_HOLDOUT,
                     body=body, prov=provenance(development=False,
                                                source="TEST-OTHER"))
        self.assertEqual(left.content_fingerprint, right.content_fingerprint)
        self.assertFalse(audit_partition([left, right]).is_clean)


class TestVisibilityCannotBeWidenedByConstruction(unittest.TestCase):

    def test_a_holdout_cannot_be_declared_author_visible(self):
        with self.assertRaises(VisibilityError):
            internal_holdout_case(visibility=VisibilityLevel.AUTHOR_VISIBLE)

    def test_a_holdout_cannot_be_mutated_after_construction(self):
        item = internal_holdout_case()
        with self.assertRaises(Exception):
            item.visibility = VisibilityLevel.AUTHOR_VISIBLE

    def test_the_role_cannot_be_mutated_after_construction(self):
        item = development_case()
        with self.assertRaises(Exception):
            item.role = ValidationCaseRole.INTERNAL_HOLDOUT


class TestPatientDataHasNoPath(unittest.TestCase):
    """Every plausible route in, closed."""

    def test_a_case_cannot_be_built_around_a_vcf(self):
        with self.assertRaises(ValidationCaseError):
            RestrictedPayload({"vcf": "##fileformat=VCFv4.2"})

    def test_a_case_cannot_carry_a_patient_identifier(self):
        with self.assertRaises(ValidationCaseError):
            RestrictedPayload({"observations": [], "mrn": "TEST-000"})

    def test_a_case_cannot_carry_a_diagnosis_or_a_dose(self):
        for field in ("diagnosis", "dose", "indication"):
            with self.subTest(field=field):
                with self.assertRaises(ValidationCaseError):
                    RestrictedPayload({"observations": [], field: "x"})

    def test_a_case_cannot_carry_a_genotype_even_nested(self):
        with self.assertRaises(ValidationCaseError):
            RestrictedPayload({"observations": [
                {"gene": "GENE:TESTGENE1", "detail": {"diplotype": "*1/*2"}}]})

    def test_an_upload_field_is_refused(self):
        for field in ("upload", "uploaded_file", "attachment", "file_content"):
            with self.subTest(field=field):
                with self.assertRaises(ValidationCaseError):
                    RestrictedPayload({"observations": [], field: "x"})


class TestAnExpectedAnswerHasNoPath(unittest.TestCase):

    def test_it_cannot_be_a_payload_field(self):
        for field in ("expected_result", "gold_standard", "ground_truth",
                      "answer_key", "reference_answer"):
            with self.subTest(field=field):
                with self.assertRaises(ValidationCaseError):
                    RestrictedPayload({"observations": [], field: "HIGH"})

    def test_it_cannot_be_a_metadata_field(self):
        with self.assertRaises(TypeError):
            ValidationCaseMetadata(
                case_id=ValidationCaseId("PGX-VAL-DEV-ANS"),
                role=ValidationCaseRole.DEVELOPMENT,
                classification=DataClassification.SYNTHETIC,
                provenance=provenance(development=True),
                content_fingerprint="sha256:" + "a" * 64,
                no_pii_assertion=NO_PII, created_at=NOW,
                compatibility=UNPINNED("1.0.0"),
                expected_result="HIGH")

    def test_it_cannot_hide_in_extra(self):
        """``extra`` is the one open-ended field, so it is walked too."""
        with self.assertRaises(ValidationCaseError):
            ValidationCaseMetadata(
                case_id=ValidationCaseId("PGX-VAL-DEV-HIDDEN2"),
                role=ValidationCaseRole.DEVELOPMENT,
                classification=DataClassification.SYNTHETIC,
                provenance=provenance(development=True),
                content_fingerprint="sha256:" + "a" * 64,
                no_pii_assertion=NO_PII, created_at=NOW,
                compatibility=UNPINNED("1.0.0"),
                extra={"scoring": {"ground_truth": "HIGH"}})


class TestAnEmptyDenominatorCannotBeDressedUp(unittest.TestCase):

    def test_the_gate_status_reports_zero_rather_than_the_target(self):
        import os

        from pgx.validation.gate_status import build_wp18_gate_status

        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        status = build_wp18_gate_status(root, environ={})
        self.assertEqual(status["holdout_case_count"], 0)
        self.assertNotEqual(status["holdout_case_count"],
                            status["p0_target_case_count"])

    def test_development_cases_are_not_counted_as_holdout(self):
        import os

        from pgx.validation.gate_status import build_wp18_gate_status

        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        status = build_wp18_gate_status(root, environ={})
        self.assertEqual(status["development_case_count"], 7)
        self.assertEqual(status["holdout_case_count"], 0)
