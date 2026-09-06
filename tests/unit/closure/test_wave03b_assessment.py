# -*- coding: utf-8 -*-
"""The Wave 3B integration gate's runtime behaviour (G5-G9).

Every assertion here is one the integration brief names. They are written
against the application service rather than the evaluator, so what is proved is
what a caller actually gets.
"""

from __future__ import annotations

import copy
import io
import json
import os
import shutil
import tempfile
import unittest

from pgx.application.assessment_models import AssessmentInput
from pgx.application.candidate_assessment_service import (
    CandidateAssessmentService)
from pgx.application.candidate_release import (CandidateReleaseError,
                                               CandidateReleaseResolver,
                                               load_active_candidate_release)
from pgx.domain.claims import (P0_CANDIDATE_CLAIM_BOUNDARY, P0_CLAIM_BOUNDARY,
                               OperationMode, PermittedInputKind)
from pgx.domain.enums import AttentionLevel, CoverageStatus, Phenotype
from pgx.engine.phenotype_models import (PhenotypeObservation, PhenotypeProfile)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


def profile(**genes):
    return PhenotypeProfile(
        observations=tuple(
            PhenotypeObservation(gene_canonical_key="GENE:" + name,
                                 status="NORMALIZED", phenotype=value)
            for name, value in sorted(genes.items())),
        input_contract_version="pgx-test/1")


def request(medications, *, care_setting=None, mode=OperationMode.DEMO,
            release=None, **genes):
    return AssessmentInput(
        mode=mode,
        input_kind=PermittedInputKind.SYNTHETIC_PHENOTYPE_PROFILE,
        profile=profile(**genes),
        medications=tuple(medications),
        care_setting=care_setting,
        requested_release_public_id=release)


class _Base(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        pointer = os.path.join(
            REPO, "data", "releases", "active-candidate-release.json")
        if not os.path.isfile(pointer):
            raise unittest.SkipTest("no active candidate release")
        cls.service = CandidateAssessmentService(repo_root=REPO)

    def _medication(self, result, index=0):
        return result.evaluation.medications[index]


class ClopidogrelCareSettingTest(_Base):
    """The brief: clopidogrel without ACS/PCI context must refuse."""

    def test_without_a_care_setting_it_refuses(self):
        result = self.service.execute(
            request(["DRUG:clopidogrel"], CYP2C19=Phenotype.POOR))
        medication = self._medication(result)
        self.assertIs(medication.attention_level, AttentionLevel.NOT_ASSESSED)
        self.assertIn("CARE_SETTING_NOT_DECLARED", medication.reason_codes)

    def test_with_an_explicit_care_setting_it_resolves(self):
        result = self.service.execute(
            request(["DRUG:clopidogrel"], care_setting="ACS_OR_PCI",
                    CYP2C19=Phenotype.POOR))
        medication = self._medication(result)
        self.assertIs(medication.status, CoverageStatus.FULL)
        self.assertIs(medication.attention_level, AttentionLevel.HIGH)

    def test_the_care_setting_is_never_inferred_from_the_drug(self):
        """The refusal above is the whole point; assert it is not a default."""
        result = self.service.execute(
            request(["DRUG:clopidogrel"], CYP2C19=Phenotype.NORMAL))
        self.assertIsNone(self._medication(result).care_setting)
        self.assertIs(self._medication(result).attention_level,
                      AttentionLevel.NOT_ASSESSED)

    def test_an_unknown_care_setting_is_refused_not_ignored(self):
        from pgx.application.assessment_models import AssessmentInputError
        with self.assertRaises(AssessmentInputError) as caught:
            self.service.execute(
                request(["DRUG:clopidogrel"], care_setting="ROUTINE",
                        CYP2C19=Phenotype.POOR))
        self.assertEqual(caught.exception.code,
                         "ASSESSMENT_CARE_SETTING_UNSUPPORTED")

    def test_the_care_setting_changes_the_input_hash(self):
        without = request(["DRUG:clopidogrel"], CYP2C19=Phenotype.POOR)
        with_setting = request(["DRUG:clopidogrel"], care_setting="ACS_OR_PCI",
                               CYP2C19=Phenotype.POOR)
        self.assertNotEqual(without.content_hash(),
                            with_setting.content_hash())


class AmitriptylineJointTest(_Base):
    """The brief: amitriptyline requires and evaluates both genes jointly."""

    def test_both_genes_present_produces_a_joint_finding(self):
        result = self.service.execute(
            request(["DRUG:amitriptyline"], CYP2C19=Phenotype.NORMAL,
                    CYP2D6=Phenotype.INTERMEDIATE))
        medication = self._medication(result)
        self.assertIs(medication.status, CoverageStatus.FULL)
        self.assertIs(medication.attention_level, AttentionLevel.MEDIUM)
        self.assertEqual(len(medication.axes), 1)
        self.assertTrue(medication.axes[0].is_joint)
        self.assertEqual(medication.axes[0].gene_keys,
                         ("GENE:CYP2C19", "GENE:CYP2D6"))

    def test_one_gene_missing_refuses_the_whole_medication(self):
        for present in ({"CYP2C19": Phenotype.NORMAL},
                        {"CYP2D6": Phenotype.NORMAL}):
            with self.subTest(present=sorted(present)):
                result = self.service.execute(
                    request(["DRUG:amitriptyline"], **present))
                medication = self._medication(result)
                self.assertIs(medication.attention_level,
                              AttentionLevel.NOT_ASSESSED)
                self.assertIn("PHENOTYPE_NOT_PROVIDED",
                              medication.reason_codes)

    def test_there_is_no_single_gene_amitriptyline_rule_to_fall_back_to(self):
        pinned = load_active_candidate_release(REPO)
        for rule in pinned.ruleset.rules_for("DRUG:amitriptyline"):
            self.assertTrue(rule.is_joint, rule.rule_key)

    def test_the_joint_answer_is_not_the_maximum_of_two_axes(self):
        """CYP2C19 IM + CYP2D6 IM: the guideline's joint cell is a 25% dose
        reduction, and the release answers from that cell rather than from the
        stronger of two single-gene readings."""
        result = self.service.execute(
            request(["DRUG:amitriptyline"], CYP2C19=Phenotype.INTERMEDIATE,
                    CYP2D6=Phenotype.INTERMEDIATE))
        medication = self._medication(result)
        self.assertIs(medication.attention_level, AttentionLevel.MEDIUM)
        self.assertEqual(len(medication.axes), 1)


class RefusalTest(_Base):

    def test_cyp2d6_rapid_refuses_for_every_cyp2d6_drug(self):
        for drug, genes in (("DRUG:codeine", {"CYP2D6": Phenotype.RAPID}),
                            ("DRUG:amitriptyline",
                             {"CYP2C19": Phenotype.NORMAL,
                              "CYP2D6": Phenotype.RAPID})):
            with self.subTest(drug=drug):
                result = self.service.execute(request([drug], **genes))
                medication = self._medication(result)
                self.assertIs(medication.attention_level,
                              AttentionLevel.NOT_ASSESSED)
                self.assertIn("PHENOTYPE_NOT_SUPPORTED",
                              medication.reason_codes)

    def test_an_indeterminate_observation_cannot_even_be_recorded(self):
        """A stronger guarantee than a refusal: the profile type refuses it."""
        from pgx.engine.phenotype_errors import PhenotypeProfileError
        with self.assertRaises(PhenotypeProfileError):
            PhenotypeObservation(gene_canonical_key="GENE:CYP2C19",
                                 status="NORMALIZED",
                                 phenotype=Phenotype.INDETERMINATE)

    def test_an_indeterminate_status_produces_a_refusal(self):
        supplied = PhenotypeProfile(
            observations=(PhenotypeObservation(
                gene_canonical_key="GENE:CYP2C19", status="INDETERMINATE",
                reason_code="PHENOTYPE_INPUT_INDETERMINATE",
                reason="the input could not be resolved to one phenotype"),),
            input_contract_version="pgx-test/1")
        result = self.service.execute(AssessmentInput(
            mode=OperationMode.DEMO,
            input_kind=PermittedInputKind.SYNTHETIC_PHENOTYPE_PROFILE,
            profile=supplied, medications=("DRUG:omeprazole",)))
        medication = self._medication(result)
        self.assertIs(medication.attention_level, AttentionLevel.NOT_ASSESSED)

    def test_an_out_of_scope_drug_refuses(self):
        result = self.service.execute(
            request(["DRUG:warfarin"], CYP2C19=Phenotype.POOR))
        medication = self._medication(result)
        self.assertIs(medication.status, CoverageStatus.UNSUPPORTED_DRUG)
        self.assertIs(medication.attention_level, AttentionLevel.NOT_ASSESSED)

    def test_a_refusal_is_never_reported_as_no_active_attention(self):
        for req in (request(["DRUG:codeine"], CYP2D6=Phenotype.RAPID),
                    request(["DRUG:warfarin"], CYP2C19=Phenotype.POOR),
                    request(["DRUG:clopidogrel"], CYP2C19=Phenotype.POOR)):
            result = self.service.execute(req)
            self.assertIsNot(self._medication(result).attention_level,
                             AttentionLevel.NO_ACTIVE_ATTENTION)


class ModeAndBoundaryTest(_Base):

    def test_pilot_is_rejected(self):
        from pgx.application.assessment_models import AssessmentInputError
        with self.assertRaises(AssessmentInputError) as caught:
            self.service.execute(
                request(["DRUG:codeine"], mode=OperationMode.PILOT,
                        CYP2D6=Phenotype.POOR))
        self.assertEqual(caught.exception.code,
                         "ASSESSMENT_MODE_NOT_PERMITTED")

    def test_demo_and_validation_both_work(self):
        for mode in (OperationMode.DEMO, OperationMode.VALIDATION):
            with self.subTest(mode=mode.value):
                result = self.service.execute(
                    request(["DRUG:codeine"], mode=mode,
                            CYP2D6=Phenotype.POOR))
                self.assertIs(self._medication(result).attention_level,
                              AttentionLevel.HIGH)

    def test_the_unapproved_p0_boundary_still_refuses_everything(self):
        from pgx.application.assessment_models import AssessmentInputError
        service = CandidateAssessmentService(
            repo_root=REPO, claim_boundary=P0_CLAIM_BOUNDARY)
        with self.assertRaises(AssessmentInputError) as caught:
            service.execute(request(["DRUG:codeine"], CYP2D6=Phenotype.POOR))
        self.assertEqual(caught.exception.code,
                         "ASSESSMENT_CLAIM_BOUNDARY_NOT_APPROVED")

    def test_the_result_reports_that_it_is_not_approved(self):
        result = self.service.execute(
            request(["DRUG:codeine"], CYP2D6=Phenotype.POOR))
        self.assertFalse(result.claim_boundary_is_approved)
        self.assertEqual(result.review_state,
                         "PENDING_EXTERNAL_EXPERT_REVIEW")
        self.assertEqual(result.authority_state, "PROJECT_TEAM_PROVISIONAL")
        self.assertTrue(result.warning.strip())


class ProvenanceTest(_Base):

    def test_a_finding_carries_its_rule_and_evidence_lineage(self):
        result = self.service.execute(
            request(["DRUG:codeine"], CYP2D6=Phenotype.ULTRARAPID))
        axis = self._medication(result).axes[0]
        self.assertTrue(axis.matched_rule_key)
        self.assertTrue(axis.rule_content_hash.startswith("sha256:"))
        self.assertTrue(axis.interpretation_key)
        self.assertTrue(axis.citations)
        self.assertTrue(axis.capture_record_ids)

    def test_the_result_pins_the_release_it_ran_against(self):
        result = self.service.execute(
            request(["DRUG:codeine"], CYP2D6=Phenotype.POOR))
        self.assertEqual(result.release_public_id,
                         "PGX-CANDIDATE-REL-20260906-001")
        self.assertTrue(result.manifest_hash.startswith("sha256:"))
        self.assertEqual(result.evaluation.dataset_public_id,
                         "PGX-DATA-20260906-001")

    def test_the_same_request_produces_the_same_output_hash(self):
        first = self.service.execute(
            request(["DRUG:codeine"], CYP2D6=Phenotype.POOR))
        second = self.service.execute(
            request(["DRUG:codeine"], CYP2D6=Phenotype.POOR))
        self.assertEqual(first.output_hash, second.output_hash)
        self.assertEqual(first.input_hash, second.input_hash)


class FailClosedReleaseTest(unittest.TestCase):
    """A tampered or absent release must fail closed, not degrade."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        for relative in (os.path.join("data", "releases"),
                         os.path.join("data", "candidate-rulesets"),
                         os.path.join("data", "rulesets"),
                         os.path.join("data", "canonical"),
                         os.path.join("data", "raw"),
                         "config"):
            source = os.path.join(REPO, relative)
            if os.path.isdir(source):
                shutil.copytree(source, os.path.join(self.root, relative))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _pointer(self):
        return os.path.join(self.root, "data", "releases",
                            "active-candidate-release.json")

    def test_a_missing_release_fails_closed(self):
        os.remove(self._pointer())
        with self.assertRaises(CandidateReleaseError) as caught:
            CandidateReleaseResolver(self.root).resolve()
        self.assertEqual(caught.exception.code,
                         "CANDIDATE_RELEASE_NOT_ACTIVE")

    def test_a_pointer_naming_a_different_manifest_hash_fails_closed(self):
        with io.open(self._pointer(), encoding="utf-8") as handle:
            pointer = json.load(handle)
        pointer["manifest_hash"] = "sha256:" + "0" * 64
        with io.open(self._pointer(), "w", encoding="utf-8") as handle:
            json.dump(pointer, handle)
        with self.assertRaises(CandidateReleaseError) as caught:
            CandidateReleaseResolver(self.root).resolve()
        self.assertEqual(caught.exception.code,
                         "CANDIDATE_RELEASE_POINTER_MISMATCH")

    def test_a_non_active_release_fails_closed(self):
        manifest_path = os.path.join(
            self.root, "data", "releases", "PGX-CANDIDATE-REL-20260906-001",
            "manifest.json")
        with io.open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        manifest["status"] = "RETIRED"
        with io.open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle)
        with self.assertRaises(CandidateReleaseError) as caught:
            CandidateReleaseResolver(self.root).resolve()
        self.assertEqual(caught.exception.code,
                         "CANDIDATE_RELEASE_NOT_ACTIVE")

    def test_a_mutated_ruleset_artifact_fails_closed(self):
        rules = os.path.join(self.root, "data", "candidate-rulesets",
                             "PGX-CANDIDATE-RULESET-WAVE03B", "rules.ndjson")
        with io.open(rules, "a", encoding="utf-8") as handle:
            handle.write("\n")
        with self.assertRaises(Exception):
            CandidateReleaseResolver(self.root).resolve()

    def test_requesting_an_inactive_release_is_refused(self):
        with self.assertRaises(CandidateReleaseError) as caught:
            CandidateReleaseResolver(self.root).resolve(
                requested_release_public_id="PGX-CANDIDATE-REL-19990101-001")
        self.assertEqual(caught.exception.code,
                         "CANDIDATE_RELEASE_NOT_ACTIVE")

    def test_the_healthy_copy_still_resolves(self):
        """Otherwise every assertion above could pass for the wrong reason."""
        pinned = CandidateReleaseResolver(self.root).resolve()
        self.assertEqual(pinned.release_public_id,
                         "PGX-CANDIDATE-REL-20260906-001")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
