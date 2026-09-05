# -*- coding: utf-8 -*-
"""Determinism (section G).

The contract in one sentence: *the same question against the same pinned
release produces the same structured facts and the same output hash, however
and whenever it is run.*

What that rules out is a specific list, and each item is tested: a different
assessment id, a different actor, a different clock, a shuffled medication
list, a shuffled phenotype mapping, a shuffled rule store, a shuffled coverage
declaration order. None may change the answer. And the converse matters as
much: a change to a rule, a dataset or a release **must** change the hash or
fail, because a version identity that does not affect the hash is a version
identity nobody can verify.
"""

from __future__ import annotations

import datetime as _dt
import json
import unittest

from pgx.domain.enums import AttentionLevel
from pgx.domain.identifiers import AssessmentId
from pgx.engine.risk import engine_contract
from tests.fixtures.wp13.synthetic import (DRUG_1, DRUG_2, GENE_1, GENE_2,
                                           GENE_3, UNKNOWN_DRUG,
                                           declarations_for,
                                           synthetic_manifest)
from tests.fixtures.wp14.synthetic import NOW, TEST_ACTOR
from tests.unit.application._assessment_support import SyntheticAssessmentWorld


class DeterminismCase(unittest.TestCase):

    def setUp(self):
        self.world = SyntheticAssessmentWorld()
        self.addCleanup(self.world.close)


class TestTheSameQuestionGivesTheSameAnswer(DeterminismCase):

    def test_two_runs_produce_the_same_output_hash(self):
        one = self.world.execute(medications=[DRUG_1, DRUG_2])
        two = self.world.execute(medications=[DRUG_1, DRUG_2])
        self.assertEqual(one.output_hash, two.output_hash)
        self.assertEqual(one.input_hash, two.input_hash)

    def test_two_runs_produce_byte_identical_documents(self):
        one = self.world.execute(medications=[DRUG_1, DRUG_2])
        two = self.world.execute(medications=[DRUG_1, DRUG_2])
        self.assertEqual(
            json.dumps(one.computation.to_json(), sort_keys=True),
            json.dumps(two.computation.to_json(), sort_keys=True))

    def test_different_assessment_ids_do_not_change_the_hash(self):
        one = self.world.execute(medications=[DRUG_1])
        two = self.world.execute(medications=[DRUG_1])
        self.assertNotEqual(one.assessment_id, two.assessment_id)
        self.assertEqual(one.output_hash, two.output_hash)

    def test_different_actors_do_not_change_the_hash(self):
        one = self.world.execute(medications=[DRUG_1], actor="TEST-actor-a")
        two = self.world.execute(medications=[DRUG_1], actor="TEST-actor-b")
        self.assertEqual(one.output_hash, two.output_hash)

    def test_different_clocks_do_not_change_the_hash(self):
        """Two services over the *same* artifacts, differing only in their
        clock. Two separate worlds would differ in their synthetic rule
        identities too, and the test would pass or fail for the wrong
        reason."""
        from pgx.application.assessment_service import AssessmentService
        early = AssessmentService(
            release_resolver=self.world.resolver,
            claim_boundary=self.world.boundary,
            clock=lambda: _dt.datetime(2099, 1, 1, tzinfo=_dt.timezone.utc))
        late = AssessmentService(
            release_resolver=self.world.resolver,
            claim_boundary=self.world.boundary,
            clock=lambda: _dt.datetime(2099, 12, 31, tzinfo=_dt.timezone.utc))
        request = self.world.input(medications=[DRUG_1])
        one = early.execute(request, actor=TEST_ACTOR)
        two = late.execute(request, actor=TEST_ACTOR)
        self.assertNotEqual(one.created_at, two.created_at)
        self.assertEqual(one.output_hash, two.output_hash)

    def test_a_shuffled_medication_list_does_not_change_the_hash(self):
        one = self.world.execute(medications=[DRUG_1, DRUG_2, UNKNOWN_DRUG])
        two = self.world.execute(medications=[UNKNOWN_DRUG, DRUG_1, DRUG_2])
        self.assertEqual(one.output_hash, two.output_hash)

    def test_a_shuffled_phenotype_mapping_does_not_change_the_hash(self):
        one = self.world.execute(
            medications=[DRUG_1],
            phenotypes={GENE_1: "POOR", GENE_2: "POOR", GENE_3: "NORMAL"})
        two = self.world.execute(
            medications=[DRUG_1],
            phenotypes={GENE_3: "NORMAL", GENE_2: "POOR", GENE_1: "POOR"})
        self.assertEqual(one.output_hash, two.output_hash)

    def test_a_shuffled_rule_store_does_not_change_the_hash(self):
        """The frozen ruleset sorts its members canonically, so the order they
        happen to sit in memory cannot reach the answer."""
        import dataclasses
        one = self.world.dry_run(medications=[DRUG_1])
        shuffled = dataclasses.replace(
            self.world.frozen,
            definitions=tuple(reversed(self.world.frozen.definitions)))
        self.world.resolver.frozen_ruleset = shuffled
        two = self.world.dry_run(medications=[DRUG_1])
        self.assertEqual(one.output_hash(), two.output_hash())

    def test_a_shuffled_coverage_declaration_does_not_change_the_hash(self):
        one = self.world.dry_run(medications=[DRUG_1])
        raw = declarations_for(self.world.frozen, expected_extra_gene=True)
        reordered = dict(raw[0])
        reordered["supported_axes"] = tuple(
            reversed(reordered["supported_axes"]))
        reordered["expected_gene_keys"] = tuple(
            reversed(reordered["expected_gene_keys"]))
        rebuilt = synthetic_manifest(self.world.frozen,
                                     declarations=(reordered,))
        self.world.resolver.coverage_manifest = rebuilt
        self.world.resolver.coverage_manifests = [rebuilt]
        two = self.world.dry_run(medications=[DRUG_1])
        self.assertEqual(one.output_hash(), two.output_hash())

    def test_a_different_case_id_does_not_change_the_hash(self):
        one = self.world.execute(medications=[DRUG_1], case_id="CASE-A")
        two = self.world.execute(medications=[DRUG_1], case_id="CASE-B")
        self.assertEqual(one.output_hash, two.output_hash)


class TestWhatMustChangeTheHash(DeterminismCase):

    def test_a_different_phenotype_changes_the_hash(self):
        one = self.world.dry_run(medications=[DRUG_1],
                                 phenotypes={GENE_1: "POOR", GENE_2: "POOR"})
        two = self.world.dry_run(medications=[DRUG_1],
                                 phenotypes={GENE_1: "NORMAL",
                                             GENE_2: "POOR"})
        self.assertNotEqual(one.output_hash(), two.output_hash())

    def test_a_different_medication_set_changes_the_hash(self):
        one = self.world.dry_run(medications=[DRUG_1])
        two = self.world.dry_run(medications=[DRUG_1, DRUG_2])
        self.assertNotEqual(one.output_hash(), two.output_hash())

    def test_a_changed_ruleset_changes_the_hash_or_fails(self):
        """A version identity that did not affect the hash would be one
        nobody could verify."""
        import dataclasses
        one = self.world.dry_run(medications=[DRUG_1])
        provenance = dataclasses.replace(
            self.world.resolver.resolve().provenance,
            ruleset_content_hash="sha256:" + "f" * 64)
        self.assertNotEqual(provenance.ruleset_content_hash,
                            one.provenance.ruleset_content_hash)
        self.assertNotEqual(
            dataclasses.replace(one, provenance=provenance).output_hash(),
            one.output_hash())

    def test_a_changed_dataset_changes_the_hash(self):
        import dataclasses
        one = self.world.dry_run(medications=[DRUG_1])
        provenance = dataclasses.replace(one.provenance,
                                         dataset_public_id="PGX-DATA-OTHER")
        self.assertNotEqual(
            dataclasses.replace(one, provenance=provenance).output_hash(),
            one.output_hash())

    def test_a_changed_release_changes_the_hash(self):
        import dataclasses
        one = self.world.dry_run(medications=[DRUG_1])
        provenance = dataclasses.replace(
            one.provenance, release_public_id="PGX-REL-19700101-001")
        self.assertNotEqual(
            dataclasses.replace(one, provenance=provenance).output_hash(),
            one.output_hash())

    def test_a_changed_coverage_result_changes_the_hash(self):
        """The coverage result is embedded whole, so a changed axis changes
        the hash. A summary that carried only its hash would too - but could
        not be shown to a reader, which is the other half of the contract."""
        one = self.world.dry_run(medications=[DRUG_1],
                                 phenotypes={GENE_1: "POOR", GENE_2: "POOR"})
        two = self.world.dry_run(medications=[DRUG_1],
                                 phenotypes={GENE_1: "POOR", GENE_2: "POOR",
                                             GENE_3: "NORMAL"})
        self.assertNotEqual(one.output_hash(), two.output_hash())


class TestThePointerGenerationIsRecordedAndNotHashed(DeterminismCase):
    """WP-15 preflight 3.5.

    The pointer generation is where the WP-03 active-release pointer had got
    to when this run pinned its release. It is a fact about *this execution*,
    not about the case: the same question, against the same release bundle
    with the same content hashes, has the same answer whether it was pinned at
    generation 3 or generation 40.

    Hashing it made an activation elsewhere in the system - one that did not
    touch this release, this ruleset or this dataset - look like a change to
    the assessment. That destroys the only comparison the output hash exists
    to support. So it is recorded, and it is not hashed.
    """

    def test_the_generation_does_not_change_the_output_hash(self):
        import dataclasses
        one = self.world.dry_run(medications=[DRUG_1])
        provenance = dataclasses.replace(one.provenance,
                                         active_pointer_generation=9)
        self.assertNotEqual(provenance.active_pointer_generation,
                            one.provenance.active_pointer_generation)
        self.assertEqual(
            dataclasses.replace(one, provenance=provenance).output_hash(),
            one.output_hash())

    def test_the_hashed_provenance_omits_it(self):
        computation = self.world.dry_run(medications=[DRUG_1])
        hashed = computation.semantic_content()["release_provenance"]
        self.assertNotIn("active_pointer_generation", hashed)

    def test_every_other_pinned_version_is_still_hashed(self):
        """Excluding one field must not quietly exclude its neighbours."""
        computation = self.world.dry_run(medications=[DRUG_1])
        hashed = computation.semantic_content()["release_provenance"]
        full = computation.provenance.to_json()
        self.assertEqual(sorted(hashed),
                         sorted(name for name in full
                                if name != "active_pointer_generation"))

    def test_the_generation_is_still_recorded(self):
        computation = self.world.dry_run(medications=[DRUG_1])
        audit = computation.to_json()["pointer_audit"]
        self.assertEqual(audit["active_pointer_generation"],
                         computation.provenance.active_pointer_generation)

    def test_the_generation_is_still_persisted(self):
        result = self.world.execute(medications=[DRUG_1])
        stored = self.world.store.row(result.assessment_id)
        self.assertEqual(
            stored["provenance"].active_pointer_generation,
            self.world.resolver.generation)
        self.assertEqual(
            stored["output_snapshot"]["pointer_audit"][
                "active_pointer_generation"],
            self.world.resolver.generation)

    def test_the_contract_publishes_the_exclusion(self):
        contract = engine_contract()
        self.assertIn("active_pointer_generation",
                      contract["excluded_from_output_hash"])
        self.assertIn("active_pointer_generation",
                      contract["recorded_but_not_hashed"]["fields"])


class TestWhatTheHashExcludes(DeterminismCase):

    def test_the_contract_names_every_exclusion(self):
        excluded = engine_contract()["excluded_from_output_hash"]
        for name in ("assessment_id", "created_at", "completed_at", "actor",
                     "database insertion order", "local paths",
                     "wall-clock time", "process id", "runtime duration",
                     "UI labels", "report prose",
                     "active_pointer_generation"):
            with self.subTest(excluded=name):
                self.assertIn(name, excluded)

    def test_the_hashed_document_contains_none_of_them(self):
        computation = self.world.dry_run(medications=[DRUG_1])
        content = computation.semantic_content()
        text = json.dumps(content)
        for forbidden in ("assessment_id", "created_at", "completed_at",
                          "actor", "duration", "/tmp/", "/home/",
                          "/sessions/", "process_id", "pid"):
            with self.subTest(field=forbidden):
                self.assertNotIn(forbidden, text)

    def test_no_temporary_path_leaks_into_the_result(self):
        """The synthetic ruleset lives on a temp path. Nothing about where it
        was read from may reach a calculated fact."""
        computation = self.world.dry_run(medications=[DRUG_1])
        text = json.dumps(computation.to_json())
        self.assertNotIn(self.world.tmp, text)

    def test_the_output_hash_covers_the_provenance(self):
        computation = self.world.dry_run(medications=[DRUG_1])
        self.assertIn("release_provenance", computation.semantic_content())

    def test_the_output_hash_covers_the_input_hash(self):
        computation = self.world.dry_run(medications=[DRUG_1])
        self.assertIn("input_hash", computation.semantic_content())

    def test_the_output_hash_covers_the_coverage_result(self):
        computation = self.world.dry_run(medications=[DRUG_1])
        self.assertIn("coverage_result_hash", computation.semantic_content())
        self.assertIn("coverage_result", computation.semantic_content())


class TestCollectionsAreCanonicallyOrdered(DeterminismCase):

    def test_medications_are_sorted(self):
        computation = self.world.dry_run(
            medications=[UNKNOWN_DRUG, DRUG_2, DRUG_1])
        keys = [item.drug_canonical_key for item in computation.medications]
        self.assertEqual(keys, sorted(keys))

    def test_findings_are_sorted(self):
        computation = self.world.dry_run(
            medications=[DRUG_1], phenotypes={GENE_1: "POOR", GENE_2: "POOR"})
        keys = [finding.sort_key for finding in computation.findings]
        self.assertEqual(keys, sorted(keys))

    def test_axes_are_sorted_inside_the_coverage_result(self):
        computation = self.world.dry_run(
            medications=[DRUG_1],
            phenotypes={GENE_3: "POOR", GENE_1: "POOR", GENE_2: "POOR"})
        for medication in computation.coverage_result.medications:
            keys = [axis.axis_key for axis in medication.axes]
            with self.subTest(drug=medication.medication.requested_value):
                self.assertEqual(keys, sorted(keys))

    def test_evidence_references_are_sorted_and_deduplicated(self):
        computation = self.world.dry_run(
            medications=[DRUG_1], phenotypes={GENE_1: "POOR"})
        for finding in computation.findings:
            with self.subTest(gene=finding.gene_canonical_key):
                references = list(finding.evidence_references)
                self.assertEqual(references, sorted(set(references)))

    def test_reason_codes_are_ordered_deterministically(self):
        one = self.world.dry_run(medications=[DRUG_1, DRUG_2, UNKNOWN_DRUG])
        two = self.world.dry_run(medications=[UNKNOWN_DRUG, DRUG_2, DRUG_1])
        self.assertEqual(
            [code.value for code in one.overall_coverage_reason_codes],
            [code.value for code in two.overall_coverage_reason_codes])


class TestPersistedResultsMatchTheCalculation(DeterminismCase):

    def test_the_stored_output_hash_is_the_calculated_one(self):
        result = self.world.execute(medications=[DRUG_1])
        stored = self.world.store.row(result.assessment_id)
        self.assertEqual(stored["assessment"].output_hash, result.output_hash)
        self.assertEqual(stored["output_snapshot"]["output_hash"],
                         result.output_hash)

    def test_retrieval_returns_identical_structured_facts(self):
        result = self.world.execute(medications=[DRUG_1, DRUG_2])
        stored = self.world.store.row(result.assessment_id)
        self.assertEqual(stored["output_snapshot"],
                         result.computation.to_json())

    def test_the_stored_input_hash_is_the_calculated_one(self):
        result = self.world.execute(medications=[DRUG_1])
        stored = self.world.store.row(result.assessment_id)
        self.assertEqual(stored["assessment"].input_hash, result.input_hash)
        self.assertEqual(stored["input_snapshot"]["input_hash"],
                         result.input_hash)

    def test_two_stored_runs_of_one_question_agree_on_the_facts(self):
        one = self.world.execute(medications=[DRUG_1])
        two = self.world.execute(medications=[DRUG_1])
        first = self.world.store.row(one.assessment_id)["output_snapshot"]
        second = self.world.store.row(two.assessment_id)["output_snapshot"]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
