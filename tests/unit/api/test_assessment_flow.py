# -*- coding: utf-8 -*-
"""C, D and K. Creating, reading and round-tripping an assessment.

Everything here runs the real path: the real request adapter, the real WP-12
normaliser, the real WP-14 service over the real engine, the real in-memory
persistence and the real response adapters. What is synthetic is the governed
world - the ruleset, the release, the dataset - and it is labelled as such.

**These assessments are synthetic implementation evidence. None of them is a
pharmacogenomic assessment of any person.** They exist to prove that the
transport layer loses nothing and invents nothing between a request and a
stored result.
"""

from __future__ import annotations

import unittest

from apps.api.adapters.assessment import (assessment_document_from_read_model,
                                          assessment_document_from_result)
from apps.api.adapters.request import adapt_assessment_request
from apps.api.contracts.validate import ContractViolation, validate_document
from apps.api.errors import ApiError, map_exception, status_for_code
from pgx.application.assessment_snapshot import build_input_snapshot
from pgx.application.execution_context import (ExecutionChannel,
                                               ExecutionContext)
from pgx.engine.phenotype_errors import PhenotypeProfileError
from tests.fixtures.wp13.synthetic import DRUG_1, DRUG_2, GENE_1, GENE_2
from tests.fixtures.wp16.synthetic import (TEST_REQUEST_ID, create_request,
                                           DEMO_PRINCIPAL)
from tests.unit.api._support import synthetic_world

UNKNOWN_DRUG = "DRUG:unknown-medicine-x"


def _context(request_id: str = TEST_REQUEST_ID) -> ExecutionContext:
    return ExecutionContext(actor=DEMO_PRINCIPAL.actor,
                            role=DEMO_PRINCIPAL.role.value,
                            channel=ExecutionChannel.API,
                            request_id=request_id,
                            authenticated_by=DEMO_PRINCIPAL.authenticated_by)


class _World(unittest.TestCase):
    """One synthetic world per test class, torn down after."""

    def setUp(self):
        self.world = synthetic_world()
        self.addCleanup(self.world.close)

    def execute(self, document=None, *, context=None):
        document = create_request() if document is None else document
        assessment_input = adapt_assessment_request(document)
        result = self.world.service.execute(assessment_input,
                                            context=context or _context())
        return assessment_input, result

    def post_document(self, document=None, *, context=None):
        assessment_input, result = self.execute(document, context=context)
        return assessment_document_from_result(
            result, input_snapshot=build_input_snapshot(assessment_input))

    def get_document(self, assessment_id):
        read_model = self.world.store.read_model(assessment_id)
        self.assertIsNotNone(read_model)
        return assessment_document_from_read_model(read_model)


class TestCreatingAnAssessment(_World):

    def test_the_response_satisfies_the_contract(self):
        self.assertTrue(validate_document("AssessmentResponse",
                                          self.post_document()))

    def test_the_service_is_invoked_exactly_once_and_pins_once(self):
        before = self.world.resolver.pointer_reads
        self.execute()
        self.assertEqual(self.world.resolver.pointer_reads - before, 1)

    def test_the_response_reports_both_hashes(self):
        document = self.post_document()
        self.assertTrue(document["input_hash"].startswith("sha256:"))
        self.assertTrue(document["output_hash"].startswith("sha256:"))
        self.assertTrue(
            document["coverage_result_hash"].startswith("sha256:"))

    def test_the_response_carries_the_complete_pinned_provenance(self):
        release = self.post_document()["release"]
        for name in ("release_public_id", "release_manifest_hash",
                     "dataset_public_id", "canonical_build_content_hash",
                     "ruleset_public_id", "ruleset_content_hash",
                     "evidence_build_key", "evidence_build_content_hash",
                     "coverage_manifest_hash", "software_version",
                     "protocol_version", "source_policy_version"):
            with self.subTest(field=name):
                self.assertTrue(release.get(name))

    def test_attention_and_coverage_are_reported_together(self):
        document = self.post_document()
        self.assertEqual(sorted(document["status"]),
                         ["attention", "coverage", "coverage_reason_codes"])
        for medication in document["medications"]:
            with self.subTest(drug=medication["drug"]):
                self.assertEqual(sorted(medication["status"]),
                                 ["attention", "coverage",
                                  "coverage_reason_codes"])

    def test_the_canonical_warning_is_attached(self):
        from pgx.domain.claims import canonical_clinical_warning
        self.assertEqual(self.post_document()["clinical_warning"],
                         canonical_clinical_warning())

    def test_a_result_is_only_returned_after_persistence(self):
        document = self.post_document()
        self.assertTrue(document["persisted"])
        self.assertIsNotNone(
            self.world.store.read_model(
                __import__("pgx.domain.identifiers", fromlist=["AssessmentId"])
                .AssessmentId.parse(document["assessment_id"])))

    def test_an_unpersisted_result_is_never_serialised_as_stored(self):
        """A service composed without persistence returns a calculation. It
        must not be presented as an assessment anyone can retrieve."""
        world = synthetic_world(persist=False)
        self.addCleanup(world.close)
        assessment_input = adapt_assessment_request(create_request())
        result = world.service.execute(assessment_input, context=_context())
        self.assertFalse(result.persisted)
        with self.assertRaises(ApiError) as caught:
            assessment_document_from_result(
                result, input_snapshot=build_input_snapshot(assessment_input))
        self.assertEqual(caught.exception.code, "PERSISTENCE_REFUSED")

    def test_a_persistence_failure_returns_no_result(self):
        world = synthetic_world(fail_on_commit=True)
        self.addCleanup(world.close)
        assessment_input = adapt_assessment_request(create_request())
        with self.assertRaises(Exception) as caught:
            world.service.execute(assessment_input, context=_context())
        code, _ = map_exception(caught.exception)
        self.assertEqual(code, "PERSISTENCE_REFUSED")
        # 500 rather than 503. The request was valid and the failure is the
        # server's, but 503 promises "temporarily unavailable, retry" - and
        # this code also covers a duplicate assessment identity, which no
        # amount of retrying resolves. A promise the code cannot keep is
        # worse than a generic one.
        self.assertEqual(status_for_code(code), 500)
        self.assertEqual(world.store.list_ids(), ())


class TestGovernedFactsSurviveSerialisation(_World):

    def test_an_unsupported_medication_is_reported_not_dropped(self):
        document = self.post_document(
            create_request(medications=[DRUG_1, UNKNOWN_DRUG]))
        drugs = {item["drug"] for item in document["medications"]}
        self.assertEqual(drugs, {DRUG_1, UNKNOWN_DRUG})
        unsupported = [item for item in document["medications"]
                       if item["drug"] == UNKNOWN_DRUG][0]
        self.assertEqual(unsupported["status"]["coverage"], "UNSUPPORTED_DRUG")
        self.assertEqual(unsupported["status"]["attention"], "NOT_ASSESSED")
        self.assertIn("DRUG_NOT_IN_CANONICAL_DATASET",
                      unsupported["status"]["coverage_reason_codes"])

    def test_not_assessed_is_never_softened(self):
        document = self.post_document(
            create_request(medications=[UNKNOWN_DRUG]))
        self.assertEqual(document["status"]["attention"], "NOT_ASSESSED")
        self.assertNotEqual(document["status"]["attention"],
                            "NO_ACTIVE_ATTENTION")

    def test_every_reason_code_is_preserved(self):
        assessment_input, result = self.execute()
        document = assessment_document_from_result(
            result, input_snapshot=build_input_snapshot(assessment_input))
        expected = [code.value for code
                    in result.computation.overall_coverage_reason_codes]
        self.assertEqual(document["status"]["coverage_reason_codes"], expected)

    def test_axes_and_findings_are_preserved_with_their_references(self):
        assessment_input, result = self.execute()
        document = assessment_document_from_result(
            result, input_snapshot=build_input_snapshot(assessment_input))
        axes = [axis for item in document["medications"]
                for axis in item["axes"]]
        findings = [finding for item in document["medications"]
                    for finding in item["findings"]]
        self.assertTrue(axes)
        self.assertTrue(findings)
        self.assertEqual(len(findings), len(result.computation.findings))
        for finding in findings:
            with self.subTest(rule=finding["rule_id"]):
                self.assertTrue(finding["evidence_references"])
                self.assertTrue(finding["rule_content_hash"])

    def test_governed_text_codes_are_never_invented(self):
        document = self.post_document()
        for medication in document["medications"]:
            for finding in medication["findings"]:
                with self.subTest(rule=finding["rule_id"]):
                    self.assertIsNone(finding["effect_code"])
                    self.assertIsNone(finding["explanation_code"])

    def test_the_supplied_phenotype_token_is_not_echoed(self):
        document = self.post_document(
            create_request(phenotypes={GENE_1: "TEST-UNRECOGNISED-TOKEN"}))
        rendered = repr(document)
        self.assertNotIn("TEST-UNRECOGNISED-TOKEN", rendered)
        observations = {item["gene"]: item for item in
                        document["observations"]}
        self.assertEqual(observations[GENE_1]["status"], "UNSUPPORTED")
        self.assertIsNone(observations[GENE_1]["phenotype"])
        self.assertTrue(observations[GENE_1]["reason_code"])


class TestReadingAnAssessment(_World):

    def test_post_and_get_return_identical_governed_facts(self):
        assessment_input, result = self.execute()
        post = assessment_document_from_result(
            result, input_snapshot=build_input_snapshot(assessment_input))
        get = self.get_document(result.assessment_id)
        self.assertEqual({k: v for k, v in post.items() if k != "created_at"},
                         {k: v for k, v in get.items() if k != "created_at"})

    def test_reading_is_byte_stable(self):
        _, result = self.execute()
        first = self.get_document(result.assessment_id)
        second = self.get_document(result.assessment_id)
        import json
        self.assertEqual(json.dumps(first, sort_keys=True),
                         json.dumps(second, sort_keys=True))

    def test_reading_runs_no_engine_and_reads_no_pointer(self):
        _, result = self.execute()
        before = self.world.resolver.pointer_reads
        self.get_document(result.assessment_id)
        self.assertEqual(self.world.resolver.pointer_reads, before)

    def test_a_superseded_release_does_not_change_a_stored_assessment(self):
        _, result = self.execute()
        stored = self.get_document(result.assessment_id)
        self.world.resolver.move_pointer()
        again = self.get_document(result.assessment_id)
        self.assertEqual(stored, again)
        self.assertEqual(again["release"]["release_public_id"],
                         result.pinned.release_public_id)

    def test_the_actor_is_not_exposed(self):
        _, result = self.execute()
        document = self.get_document(result.assessment_id)
        self.assertNotIn("actor", document)
        self.assertNotIn(DEMO_PRINCIPAL.actor, repr(document))

    def test_a_corrupt_stored_result_fails_closed(self):
        """A row whose document no longer hashes back must produce no JSON at
        all - not a partial document with the suspect parts removed."""
        _, result = self.execute()
        read_model = self.world.store.read_model(result.assessment_id)
        broken = dict(read_model.computation)
        broken["overall_attention"] = "LOW"

        class _Tampered:
            assessment_id = read_model.assessment_id
            created_at = read_model.created_at
            completed_at = read_model.completed_at
            input_hash = read_model.input_hash
            output_hash = read_model.output_hash
            input_snapshot = read_model.input_snapshot
            computation = broken

        with self.assertRaises(ApiError) as caught:
            assessment_document_from_read_model(_Tampered())
        self.assertEqual(caught.exception.code, "STORED_RESULT_INCONSISTENT")
        self.assertEqual(status_for_code(caught.exception.code), 500)


class TestPointerMovementDuringExecution(_World):
    """§8: an activation committing mid-request changes nothing already pinned.

    The pointer is read once, into a value. Moving it afterwards cannot reach
    a calculation that already holds that value, and the assertion is that the
    response reports the release that was pinned rather than the one that is
    active by the time the response is built.
    """

    def test_moving_the_pointer_after_pinning_changes_no_response(self):
        assessment_input = adapt_assessment_request(create_request())
        pinned_generation = self.world.resolver.generation
        result = self.world.service.execute(assessment_input,
                                            context=_context())
        self.world.resolver.move_pointer()
        self.assertNotEqual(self.world.resolver.generation, pinned_generation)

        document = assessment_document_from_result(
            result, input_snapshot=build_input_snapshot(assessment_input))
        self.assertEqual(result.pinned.active_pointer_generation,
                         pinned_generation)
        self.assertEqual(document["release"]["release_public_id"],
                         result.pinned.release_public_id)
        # And the generation is not in the response at all: it is pointer
        # audit metadata, and beside pinned provenance it would read as part
        # of the pinned identity.
        self.assertNotIn("active_pointer_generation", document["release"])

    def test_two_assessments_across_a_pointer_move_agree_on_facts(self):
        first = self.post_document()
        self.world.resolver.move_pointer()
        second = self.post_document()
        self.assertEqual(first["output_hash"], second["output_hash"])
        self.assertEqual(first["status"], second["status"])


class TestUnsupportedAndMalformedInput(_World):

    def test_a_malformed_document_is_a_contract_violation(self):
        with self.assertRaises(ContractViolation) as caught:
            adapt_assessment_request(dict(create_request(), surprise=1))
        code, _ = map_exception(caught.exception)
        self.assertEqual(code, "REQUEST_CONTRACT_VIOLATION")
        self.assertEqual(status_for_code(code), 422)

    def test_a_prohibited_field_maps_to_its_own_code(self):
        with self.assertRaises(ContractViolation) as caught:
            adapt_assessment_request(dict(create_request(), genotype="*1/*2"))
        code, details = map_exception(caught.exception)
        self.assertEqual(code, "PROHIBITED_INPUT_FIELD")
        self.assertEqual(status_for_code(code), 422)
        self.assertNotIn("*1/*2", repr(details))

    def test_two_gene_keys_naming_one_gene_are_refused(self):
        document = create_request()
        document["profile"]["observations"] = [
            {"gene": GENE_1, "value": "POOR"},
            {"gene": GENE_1, "value": "NORMAL"}]
        with self.assertRaises(ContractViolation) as caught:
            adapt_assessment_request(document)
        self.assertEqual(caught.exception.codes, ("DUPLICATE_ITEM",))
        self.assertEqual([issue.location for issue in caught.exception.issues],
                         ["$.profile.observations[1].gene"])

    def test_an_uninterpretable_token_is_recorded_rather_than_guessed(self):
        assessment_input = adapt_assessment_request(
            create_request(phenotypes={GENE_1: "VERY-FAST"}))
        observation = assessment_input.profile.observations[0]
        self.assertIsNone(observation.phenotype)
        self.assertEqual(observation.status, "UNSUPPORTED")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
