# -*- coding: utf-8 -*-
"""The case model: what it requires, and what it will not hold (WP-18).

The class under test is two classes on purpose, and most of these tests are
about the seam between them. A validation case that could be published with an
expected answer in it is a leaked holdout, and the defence is that the
publishable object has nowhere to put one - so the tests check the *absence of
a place*, not merely the absence of a value.
"""

from __future__ import annotations

import datetime as _dt
import unittest

from pgx.validation.cases import (PROHIBITED_CASE_FIELDS, Provenance,
                                  RestrictedPayload, ValidationCaseId,
                                  ValidationCaseMetadata,
                                  assert_no_prohibited_fields,
                                  default_visibility_for)
from pgx.validation.compatibility import ReleaseCompatibility, UNPINNED
from pgx.validation.errors import (ProvenanceError, ValidationCaseError,
                                   VisibilityError)
from pgx.validation.vocabulary import (DataClassification, ValidationCaseRole,
                                       VisibilityLevel)
from tests.fixtures.wp18.synthetic import (NO_PII, NOW, case, content,
                                           development_case,
                                           expert_holdout_case,
                                           internal_holdout_case, provenance)


class TestTheIdentifierIsAType(unittest.TestCase):

    def test_it_refuses_a_non_string(self):
        with self.assertRaises(ValidationCaseError):
            ValidationCaseId(7)

    def test_it_refuses_an_identifier_from_another_namespace(self):
        for value in ("WP17-CASE-P1", "PGX-DATA-20260830-900", "",
                      "PGX-VAL-", "pgx-val-lowercase"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationCaseError):
                    ValidationCaseId(value)

    def test_two_identifiers_with_one_value_are_equal(self):
        self.assertEqual(ValidationCaseId("PGX-VAL-DEV-A"),
                         ValidationCaseId("PGX-VAL-DEV-A"))

    def test_it_is_not_equal_to_the_bare_string(self):
        """A plain string would compare equal to anything spelled the same.

        Including, eventually, something that is not a case identifier at all.
        """
        self.assertNotEqual(ValidationCaseId("PGX-VAL-DEV-A"), "PGX-VAL-DEV-A")


class TestEveryCaseRecordsWhereItCameFrom(unittest.TestCase):

    def test_a_case_without_a_source_is_refused(self):
        with self.assertRaises(ProvenanceError):
            Provenance(source_identity="", derivation_method="authored",
                       derived_from_development=False)

    def test_a_case_without_a_derivation_method_is_refused(self):
        with self.assertRaises(ProvenanceError):
            Provenance(source_identity="TEST-SOURCE/1", derivation_method="",
                       derived_from_development=False)

    def test_derivation_from_development_is_a_claim_not_a_guess(self):
        """It must be stated as a bool, because nobody else can know it.

        A case built by editing a demo profile is not independent however much
        it was changed, and only its author knows. Inferring it from a string
        would mean a rename could defeat the check.
        """
        with self.assertRaises(ProvenanceError):
            Provenance(source_identity="TEST-SOURCE/1",
                       derivation_method="authored",
                       derived_from_development="no")

    def test_a_malformed_source_digest_is_refused(self):
        with self.assertRaises(ProvenanceError):
            Provenance(source_identity="TEST-SOURCE/1",
                       derivation_method="authored",
                       derived_from_development=False,
                       source_digest="not-a-digest")


class TestRoleDecidesVisibility(unittest.TestCase):

    def test_development_defaults_to_author_visible(self):
        self.assertIs(default_visibility_for(ValidationCaseRole.DEVELOPMENT),
                      VisibilityLevel.AUTHOR_VISIBLE)

    def test_both_holdout_roles_default_to_restricted(self):
        for role in (ValidationCaseRole.INTERNAL_HOLDOUT,
                     ValidationCaseRole.EXPERT_HOLDOUT):
            with self.subTest(role=role):
                self.assertIs(default_visibility_for(role),
                              VisibilityLevel.RESTRICTED)

    def test_a_holdout_may_not_be_constructed_author_visible(self):
        """The one combination the whole partition exists to prevent."""
        for role in (ValidationCaseRole.INTERNAL_HOLDOUT,
                     ValidationCaseRole.EXPERT_HOLDOUT):
            with self.subTest(role=role):
                with self.assertRaises(VisibilityError):
                    case("PGX-VAL-XTEST-1", role,
                         visibility=VisibilityLevel.AUTHOR_VISIBLE,
                         prov=provenance(development=False))

    def test_a_holdout_derived_from_development_is_refused(self):
        with self.assertRaises(ProvenanceError):
            case("PGX-VAL-INT-TEST-2", ValidationCaseRole.INTERNAL_HOLDOUT,
                 prov=provenance(development=True))

    def test_a_holdout_without_verifiable_provenance_is_refused(self):
        with self.assertRaises(ProvenanceError):
            case("PGX-VAL-INT-TEST-3", ValidationCaseRole.INTERNAL_HOLDOUT,
                 prov=provenance(development=False, citation=None,
                                 digest=None))


class TestOnlyHoldoutIsValidationEvidence(unittest.TestCase):

    def test_a_development_case_is_never_evidence(self):
        self.assertFalse(development_case().is_validation_evidence)

    def test_both_holdout_roles_are_evidence(self):
        self.assertTrue(internal_holdout_case().is_validation_evidence)
        self.assertTrue(expert_holdout_case().is_validation_evidence)

    def test_evidence_is_derived_from_the_role_not_stored(self):
        """So it cannot be set to something the role contradicts.

        A stored boolean beside a role is two sources of truth, and the day
        they disagree the wrong one gets read.
        """
        self.assertNotIn("is_validation_evidence",
                         ValidationCaseMetadata.__slots__)


class TestThePublicHalfCannotHoldAnAnswer(unittest.TestCase):

    def test_the_metadata_class_has_no_expected_result_field(self):
        fields = set(ValidationCaseMetadata.__slots__)
        for name in ("expected_result", "expected_attention",
                     "expected_coverage", "expected_findings", "answer",
                     "gold_standard", "ground_truth", "payload", "content",
                     "observations", "medications"):
            with self.subTest(field=name):
                self.assertNotIn(name, fields)

    def test_its_json_carries_no_prohibited_field(self):
        for factory in (development_case, internal_holdout_case,
                        expert_holdout_case):
            with self.subTest(case=factory.__name__):
                assert_no_prohibited_fields(factory().to_json(),
                                            PROHIBITED_CASE_FIELDS)

    def test_an_answer_smuggled_into_extra_is_refused(self):
        """``extra`` is the one open-ended field, so it is walked too."""
        with self.assertRaises(ValidationCaseError):
            ValidationCaseMetadata(
                case_id=ValidationCaseId("PGX-VAL-DEV-5"),
                role=ValidationCaseRole.DEVELOPMENT,
                classification=DataClassification.SYNTHETIC,
                provenance=provenance(development=True),
                content_fingerprint="sha256:" + "a" * 64,
                no_pii_assertion=NO_PII, created_at=NOW,
                compatibility=UNPINNED("1.0.0"),
                extra={"notes": {"expected_result": "HIGH"}})


class TestProhibitedFieldsAreRefusedAtAnyDepth(unittest.TestCase):
    """Depth matters more than breadth.

    A top-level check is satisfied by one extra layer of nesting, and the
    person who adds that layer is usually not being devious - they are
    following a shape that felt natural.
    """

    REAL_PATIENT = ("patient_name", "mrn", "date_of_birth", "ehr",
                    "lab_report", "diagnosis", "dose", "clinical_note")
    GENOTYPE = ("genotype", "diplotype", "star_allele", "activity_score",
                "vcf", "fastq", "bam", "variant")
    ANSWERS = ("expected_result", "gold_standard", "ground_truth", "score",
               "accuracy", "pass_rate")

    def test_every_real_patient_field_is_refused(self):
        for name in self.REAL_PATIENT:
            with self.subTest(field=name):
                with self.assertRaises(ValidationCaseError):
                    assert_no_prohibited_fields({name: "x"},
                                                PROHIBITED_CASE_FIELDS)

    def test_every_genotype_level_field_is_refused(self):
        for name in self.GENOTYPE:
            with self.subTest(field=name):
                with self.assertRaises(ValidationCaseError):
                    assert_no_prohibited_fields({name: "x"},
                                                PROHIBITED_CASE_FIELDS)

    def test_every_expected_answer_field_is_refused(self):
        for name in self.ANSWERS:
            with self.subTest(field=name):
                with self.assertRaises(ValidationCaseError):
                    assert_no_prohibited_fields({name: "x"},
                                                PROHIBITED_CASE_FIELDS)

    def test_nesting_does_not_hide_one(self):
        deep = {"a": {"b": [{"c": {"vcf_path": "/somewhere"}}]}}
        with self.assertRaises(ValidationCaseError) as caught:
            assert_no_prohibited_fields(deep, PROHIBITED_CASE_FIELDS)
        self.assertIn("$.a.b[0].c.vcf_path", str(caught.exception))

    def test_the_refusal_names_the_location_and_not_the_value(self):
        """An error raised over a genotype must not carry the genotype."""
        secret = "TEST-NEVER-LOG-*1/*17"
        with self.assertRaises(ValidationCaseError) as caught:
            assert_no_prohibited_fields({"genotype": secret},
                                        PROHIBITED_CASE_FIELDS)
        self.assertNotIn(secret, str(caught.exception))

    def test_case_and_padding_do_not_evade_it(self):
        for spelling in ("GENOTYPE", " genotype ", "Genotype"):
            with self.subTest(spelling=spelling):
                with self.assertRaises(ValidationCaseError):
                    assert_no_prohibited_fields({spelling: "x"},
                                                PROHIBITED_CASE_FIELDS)

    def test_a_payload_is_held_to_the_same_list(self):
        with self.assertRaises(ValidationCaseError):
            RestrictedPayload({"observations": [], "genotype": "x"})


class TestTheCaseIsImmutable(unittest.TestCase):

    def test_metadata_cannot_be_reassigned(self):
        item = development_case()
        with self.assertRaises(Exception):
            item.role = ValidationCaseRole.EXPERT_HOLDOUT

    def test_payload_content_is_frozen(self):
        body = {"observations": [{"gene": "GENE:TESTGENE1", "value": "POOR"}]}
        stored = RestrictedPayload(body)
        body["observations"].append({"gene": "GENE:TESTGENE2",
                                     "value": "NORMAL"})
        self.assertEqual(len(stored.content["observations"]), 1)

    def test_the_created_time_is_utc(self):
        item = ValidationCaseMetadata(
            case_id=ValidationCaseId("PGX-VAL-DEV-7"),
            role=ValidationCaseRole.DEVELOPMENT,
            classification=DataClassification.SYNTHETIC,
            provenance=provenance(development=True),
            content_fingerprint="sha256:" + "b" * 64,
            no_pii_assertion=NO_PII,
            created_at=_dt.datetime(2026, 1, 1, 9, 0,
                                    tzinfo=_dt.timezone.utc),
            compatibility=UNPINNED("1.0.0"))
        self.assertEqual(item.created_at.tzinfo, _dt.timezone.utc)


class TestHashesAreDeterministic(unittest.TestCase):

    def test_the_same_case_hashes_the_same_twice(self):
        self.assertEqual(development_case().metadata_hash(),
                         development_case().metadata_hash())

    def test_a_changed_role_changes_the_hash(self):
        left = case("PGX-VAL-ATEST-1", ValidationCaseRole.DEVELOPMENT,
                    prov=provenance(development=True))
        right = case("PGX-VAL-ATEST-1", ValidationCaseRole.INTERNAL_HOLDOUT,
                     prov=provenance(development=False))
        self.assertNotEqual(left.metadata_hash(), right.metadata_hash())

    def test_a_payload_hash_and_a_fingerprint_answer_different_questions(self):
        """One asks 'same case', the other asks 'same bytes'."""
        stored = RestrictedPayload(content())
        self.assertNotEqual(stored.fingerprint, stored.payload_hash)
