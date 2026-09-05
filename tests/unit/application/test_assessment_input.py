# -*- coding: utf-8 -*-
"""The assessment input contract (section A).

Two properties, and the second is the one that will be argued with.

The input hash covers *the question*: the mode, the input kind, the phenotype
profile and the medications, canonically sorted. Two people asking the same
question get the same hash, which is what makes "same input, same release,
different answer" a detectable event.

And the input contract refuses what this product does not accept - a genotype,
a diplotype, an activity score, a VCF, an EHR reference, a clinical narrative,
a diagnosis, a dose. Refused as a whole request rather than ignored field by
field: a request carrying a VCF path was written by somebody who believed this
system reads VCFs, and quietly using the acceptable half would confirm it.
"""

from __future__ import annotations

import dataclasses
import unittest

from pgx.application.assessment_models import (ASSESSMENT_INPUT_SCHEMA_VERSION,
                                               REFUSED_INPUT_FIELDS,
                                               AssessmentInput,
                                               build_assessment_input)
from pgx.domain.claims import (DEFAULT_CLAIM_BOUNDARY, OperationMode,
                               PermittedInputKind)
from pgx.engine.risk_errors import AssessmentInputError
from tests.fixtures.wp13.synthetic import (DRUG_1, DRUG_2, GENE_1, GENE_2,
                                           GENE_3, UNKNOWN_DRUG,
                                           synthetic_profile)
from tests.fixtures.wp14.synthetic import synthetic_claim_boundary

SYNTHETIC = PermittedInputKind.SYNTHETIC_PHENOTYPE_PROFILE


def make_input(**overrides):
    values = dict(mode=OperationMode.DEMO, input_kind=SYNTHETIC,
                  profile=synthetic_profile({GENE_1: "POOR", GENE_2: "POOR"}),
                  medications=(DRUG_1,), case_id="TEST-CASE-1")
    values.update(overrides)
    return AssessmentInput(**values)


class TestModeAndInputKind(unittest.TestCase):

    def test_demo_and_validation_are_accepted_by_an_approved_boundary(self):
        boundary = synthetic_claim_boundary()
        for mode in (OperationMode.DEMO, OperationMode.VALIDATION):
            with self.subTest(mode=mode.value):
                make_input(mode=mode).require_permitted(boundary)

    def test_pilot_is_refused_even_under_an_approved_boundary(self):
        """PILOT requires a formally expanded intended purpose and a P2 gate.
        An approved boundary is not an unrestricted one."""
        with self.assertRaises(AssessmentInputError) as caught:
            make_input(mode=OperationMode.PILOT).require_permitted(
                synthetic_claim_boundary())
        self.assertEqual(caught.exception.code,
                         "ASSESSMENT_MODE_NOT_PERMITTED")

    def test_a_free_string_mode_is_refused(self):
        """A string cannot be checked against the claim boundary."""
        for value in ("DEMO", "demo", "PILOT", 1, None):
            with self.subTest(mode=value):
                with self.assertRaises(AssessmentInputError) as caught:
                    make_input(mode=value)
                self.assertEqual(caught.exception.code,
                                 "ASSESSMENT_MODE_NOT_PERMITTED")

    def test_a_free_string_input_kind_is_refused(self):
        for value in ("SYNTHETIC_PHENOTYPE_PROFILE", "vcf", None):
            with self.subTest(input_kind=value):
                with self.assertRaises(AssessmentInputError) as caught:
                    make_input(input_kind=value)
                self.assertEqual(caught.exception.code,
                                 "ASSESSMENT_INPUT_KIND_NOT_PERMITTED")

    def test_an_input_kind_outside_the_boundary_is_refused(self):
        narrow = synthetic_claim_boundary(
            permitted_input_kinds=frozenset({
                PermittedInputKind.MEDICATION_NAME_LIST}))
        with self.assertRaises(AssessmentInputError) as caught:
            make_input().require_permitted(narrow)
        self.assertEqual(caught.exception.code,
                         "ASSESSMENT_INPUT_KIND_NOT_PERMITTED")

    def test_the_default_boundary_refuses_everything(self):
        """The shipped boundary is DRAFT. Nothing executes under it, and the
        refusal names the boundary rather than the mode - because the mode is
        not the problem."""
        with self.assertRaises(AssessmentInputError) as caught:
            make_input().require_permitted(DEFAULT_CLAIM_BOUNDARY)
        self.assertEqual(caught.exception.code,
                         "ASSESSMENT_CLAIM_BOUNDARY_NOT_APPROVED")

    def test_the_boundary_is_checked_before_the_mode(self):
        """An unapproved boundary refuses a permitted mode too. Order matters:
        reporting 'mode not permitted' would suggest another mode might work."""
        with self.assertRaises(AssessmentInputError) as caught:
            make_input(mode=OperationMode.VALIDATION).require_permitted(
                DEFAULT_CLAIM_BOUNDARY)
        self.assertEqual(caught.exception.code,
                         "ASSESSMENT_CLAIM_BOUNDARY_NOT_APPROVED")

    def test_no_code_here_makes_the_default_boundary_approved(self):
        self.assertFalse(DEFAULT_CLAIM_BOUNDARY.is_approved)
        self.assertIn("DRAFT", DEFAULT_CLAIM_BOUNDARY.status)


class TestRefusedInputData(unittest.TestCase):

    def test_every_refused_field_refuses_the_whole_request(self):
        for field in REFUSED_INPUT_FIELDS:
            with self.subTest(field=field):
                with self.assertRaises(AssessmentInputError) as caught:
                    build_assessment_input(
                        {"medications": [DRUG_1], field: "anything"},
                        profile=synthetic_profile(), mode=OperationMode.DEMO,
                        input_kind=SYNTHETIC)
                self.assertEqual(caught.exception.code,
                                 "ASSESSMENT_INPUT_KIND_NOT_PERMITTED")
                self.assertIn(field, caught.exception.detail["refused_fields"])

    def test_the_named_categories_are_all_covered(self):
        for field in ("genotype", "diplotype", "star_allele", "activity_score",
                      "vcf", "ehr", "patient_narrative", "clinical_notes",
                      "diagnosis", "dose"):
            with self.subTest(field=field):
                self.assertIn(field, REFUSED_INPUT_FIELDS)

    def test_every_refusal_says_why(self):
        for field, reason in REFUSED_INPUT_FIELDS.items():
            with self.subTest(field=field):
                self.assertGreater(len(reason), 4)

    def test_a_refused_field_is_not_partially_honoured(self):
        """The acceptable half of an unacceptable request is not used."""
        with self.assertRaises(AssessmentInputError):
            build_assessment_input(
                {"medications": [DRUG_1, DRUG_2], "case_id": "C-1",
                 "vcf_path": "/tmp/sample.vcf"},
                profile=synthetic_profile(), mode=OperationMode.DEMO,
                input_kind=SYNTHETIC)

    def test_an_acceptable_request_builds(self):
        built = build_assessment_input(
            {"medications": [DRUG_2, DRUG_1], "case_id": "C-1",
             "release_id": "PGX-REL-29991231-001"},
            profile=synthetic_profile(), mode=OperationMode.DEMO,
            input_kind=SYNTHETIC)
        self.assertEqual(built.medications, (DRUG_1, DRUG_2))
        self.assertEqual(built.case_id, "C-1")
        self.assertEqual(built.requested_release_public_id,
                         "PGX-REL-29991231-001")

    def test_a_request_that_is_not_an_object_is_refused(self):
        with self.assertRaises(AssessmentInputError) as caught:
            build_assessment_input([DRUG_1], profile=synthetic_profile(),
                                   mode=OperationMode.DEMO,
                                   input_kind=SYNTHETIC)
        self.assertEqual(caught.exception.code, "ASSESSMENT_INPUT_INVALID")


class TestMedicationHandling(unittest.TestCase):

    def test_medications_are_canonically_sorted(self):
        self.assertEqual(make_input(medications=(DRUG_2, DRUG_1)).medications,
                         (DRUG_1, DRUG_2))

    def test_a_duplicate_medication_is_refused_not_merged(self):
        with self.assertRaises(AssessmentInputError) as caught:
            make_input(medications=(DRUG_1, DRUG_1))
        self.assertEqual(caught.exception.code, "ASSESSMENT_INPUT_INVALID")
        self.assertEqual(caught.exception.detail["medication"], DRUG_1)

    def test_an_empty_request_is_refused(self):
        with self.assertRaises(AssessmentInputError) as caught:
            make_input(medications=())
        self.assertEqual(caught.exception.code, "ASSESSMENT_INPUT_INVALID")

    def test_a_blank_medication_is_refused(self):
        for value in ("", "   ", None, 7):
            with self.subTest(value=value):
                with self.assertRaises(AssessmentInputError):
                    make_input(medications=(value,))

    def test_an_unknown_drug_is_preserved_not_dropped(self):
        """It becomes an unsupported medication for coverage. Dropping it
        would make an unanswerable question look answered."""
        built = make_input(medications=(DRUG_1, UNKNOWN_DRUG))
        self.assertIn(UNKNOWN_DRUG, built.medications)
        self.assertEqual(len(built.medications), 2)

    def test_free_text_is_not_resolved_here(self):
        """Resolving a brand name is WP-07's work. This contract stores what
        it was given; coverage reports what the pinned dataset makes of it."""
        built = make_input(medications=("Plavix",))
        self.assertEqual(built.medications, ("Plavix",))


class TestTheInputHash(unittest.TestCase):

    def test_the_same_question_hashes_identically(self):
        self.assertEqual(make_input().content_hash(),
                         make_input().content_hash())

    def test_medication_order_does_not_change_the_hash(self):
        one = make_input(medications=(DRUG_1, DRUG_2, UNKNOWN_DRUG))
        two = make_input(medications=(UNKNOWN_DRUG, DRUG_2, DRUG_1))
        self.assertEqual(one.content_hash(), two.content_hash())

    def test_phenotype_order_does_not_change_the_hash(self):
        one = make_input(profile=synthetic_profile({GENE_1: "POOR",
                                                    GENE_2: "NORMAL"}))
        two = make_input(profile=synthetic_profile({GENE_2: "NORMAL",
                                                    GENE_1: "POOR"}))
        self.assertEqual(one.content_hash(), two.content_hash())

    def test_case_id_is_deliberately_outside_the_semantic_hash(self):
        """Documented and tested rather than left to be rediscovered.

        A case identifier labels a run; it is not part of what was asked. If it
        entered the hash, two runs of the same question under different case
        ids would look like different questions - which would destroy exactly
        the comparison the hash exists to support.
        """
        one = make_input(case_id="CASE-A")
        two = make_input(case_id="CASE-B")
        three = make_input(case_id=None)
        self.assertEqual(one.content_hash(), two.content_hash())
        self.assertEqual(one.content_hash(), three.content_hash())
        self.assertNotIn("case_id", one.semantic_content())

    def test_the_case_id_is_still_recorded(self):
        """Excluded from the hash is not excluded from the record."""
        self.assertEqual(make_input(case_id="CASE-A").to_json()["case_id"],
                         "CASE-A")

    def test_the_requested_release_is_outside_the_hash_too(self):
        """Which release a caller asked for is part of the asking. What was
        actually pinned is recorded separately, and it is the pinned release
        that the output hash covers."""
        one = make_input(release_id=None) if False else make_input()
        two = make_input(requested_release_public_id="PGX-REL-29991231-001")
        self.assertEqual(one.content_hash(), two.content_hash())

    def test_a_different_mode_changes_the_hash(self):
        self.assertNotEqual(
            make_input(mode=OperationMode.DEMO).content_hash(),
            make_input(mode=OperationMode.VALIDATION).content_hash())

    def test_a_different_input_kind_changes_the_hash(self):
        self.assertNotEqual(
            make_input().content_hash(),
            make_input(
                input_kind=PermittedInputKind.PUBLIC_DEMO_PROFILE
            ).content_hash())

    def test_a_different_phenotype_changes_the_hash(self):
        self.assertNotEqual(
            make_input().content_hash(),
            make_input(profile=synthetic_profile({GENE_1: "NORMAL",
                                                  GENE_2: "POOR"})
                       ).content_hash())

    def test_a_different_medication_changes_the_hash(self):
        self.assertNotEqual(make_input(medications=(DRUG_1,)).content_hash(),
                            make_input(medications=(DRUG_2,)).content_hash())

    def test_the_hash_names_its_schema_version(self):
        self.assertEqual(make_input().semantic_content()["input_schema_version"],
                         ASSESSMENT_INPUT_SCHEMA_VERSION)

    def test_the_document_says_what_it_excludes(self):
        note = make_input().to_json()["note"]
        self.assertIn("case_id", note)
        self.assertIn("not part of the semantic input", note)


class TestTheInputIsImmutable(unittest.TestCase):

    def test_it_cannot_be_mutated(self):
        with self.assertRaises((dataclasses.FrozenInstanceError,
                                AttributeError)):
            make_input().medications = ()

    def test_mutating_the_supplied_list_afterwards_changes_nothing(self):
        medications = [DRUG_1, DRUG_2]
        built = make_input(medications=tuple(medications))
        before = built.content_hash()
        medications.append(UNKNOWN_DRUG)
        self.assertEqual(built.content_hash(), before)

    def test_a_profile_is_required(self):
        for value in (None, "POOR", {"GENE:X": "POOR"}):
            with self.subTest(profile=value):
                with self.assertRaises(AssessmentInputError) as caught:
                    make_input(profile=value)
                self.assertEqual(caught.exception.code,
                                 "ASSESSMENT_INPUT_INVALID")

    def test_a_blank_case_id_is_refused(self):
        with self.assertRaises(AssessmentInputError):
            make_input(case_id="   ")


if __name__ == "__main__":
    unittest.main()
