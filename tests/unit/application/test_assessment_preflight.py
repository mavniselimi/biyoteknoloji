# -*- coding: utf-8 -*-
"""The five WP-14 repairs WP-15 could not be built on top of.

Each section here corresponds to a defect that was real, was found by asking
"could a report actually be rendered from what WP-14 stored?", and was
repaired before any reporting code was written.

1. **Identities were minted, not resolved.** ``_as_domain_assessment`` called
   ``DrugId.new()`` and ``GeneId.new()`` once per row, so two runs of one
   question recorded two different drugs and the stored assessment joined to
   nothing.
2. **The input snapshot dropped the phenotype profile.** The half of the
   question that decides every finding was not stored, so a stored assessment
   could be recognised but not re-asked and not shown.
3. **The coverage result was reduced to a hash.** A report must name every
   axis; a hash names none, and recomputing them in the reporting layer would
   be a second engine.
4. **Retrieval returned a summary.** Six fields and two counts is not a render
   source.
5. **The pointer generation was inside the output hash.** An activation
   elsewhere in the system made an unchanged assessment look changed.
"""

from __future__ import annotations

import ast
import copy
import io
import os
import unittest

from pgx.application.assessment_models import CanonicalEntityIndex
from pgx.application.assessment_read_model import (
    ASSESSMENT_READ_MODEL_SCHEMA_VERSION, READ_MODEL_ROW_KEYS,
    build_assessment_read_model)
from pgx.application.assessment_service import AssessmentService
from pgx.application.assessment_snapshot import (
    ASSESSMENT_INPUT_SNAPSHOT_SCHEMA_VERSION, FORBIDDEN_SNAPSHOT_KEYS,
    SNAPSHOT_REQUIRED_KEYS, build_input_snapshot,
    rebuild_input_semantic_content, verify_input_snapshot)
from pgx.domain.enums import CoverageStatus
from pgx.domain.hashing import sha256_digest
from pgx.engine.risk import (COMPUTATION_ENVELOPE_KEYS, POINTER_AUDIT_FIELDS,
                             embedded_coverage_result, hashed_projection)
from pgx.engine.risk_errors import (AssessmentArtifactError,
                                    AssessmentEngineError,
                                    AssessmentInputError,
                                    AssessmentPersistenceError)
from tests.fixtures.wp13.synthetic import (DRUG_1, DRUG_2, GENE_1, GENE_2,
                                           GENE_3, UNKNOWN_DRUG)
from tests.fixtures.wp14.synthetic import (NOW, SYNTHETIC_DRUG_IDS,
                                           SYNTHETIC_GENE_IDS, TEST_ACTOR,
                                           synthetic_entity_index)
from tests.unit.application._assessment_support import (
    REPO_ROOT, SyntheticAssessmentWorld, assessment_row_mapping,
    axis_row_mappings, finding_row_mappings, medication_row_mappings)

SERVICE_MODULE = os.path.join(REPO_ROOT, "pgx", "application",
                              "assessment_service.py")
READ_MODEL_MODULE = os.path.join(REPO_ROOT, "pgx", "application",
                                 "assessment_read_model.py")
DB_ADAPTER_MODULE = os.path.join(REPO_ROOT, "pgx", "infrastructure", "db",
                                 "assessments.py")


def _source(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def _function(path, name):
    """The AST of one function or method, wherever it is defined."""
    for node in ast.walk(ast.parse(_source(path), filename=path)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                node.name == name:
            return node
    raise AssertionError("%s defines no %s" % (path, name))


def _called_attributes(node):
    """Every ``x.y(...)`` attribute name called inside ``node``."""
    found = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and \
                isinstance(child.func, ast.Attribute):
            found.add(child.func.attr)
    return found


def _called_names(node):
    """Every bare ``y(...)`` name called inside ``node``."""
    found = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
            found.add(child.func.id)
    return found


class PreflightCase(unittest.TestCase):

    def setUp(self):
        self.world = SyntheticAssessmentWorld()
        self.addCleanup(self.world.close)

    def stored(self, result):
        return self.world.store.row(result.assessment_id)


# ---------------------------------------------------------------------------
# 3.1  Canonical entity identities are resolved, never minted
# ---------------------------------------------------------------------------


class TestIdentitiesAreResolvedNotMinted(PreflightCase):

    def test_two_runs_of_one_question_record_the_same_drug_identity(self):
        one = self.world.execute(medications=[DRUG_1])
        two = self.world.execute(medications=[DRUG_1])
        first = self.stored(one)["assessment"].coverage
        second = self.stored(two)["assessment"].coverage
        self.assertEqual([item.drug_id for item in first],
                         [item.drug_id for item in second])

    def test_two_runs_of_one_question_record_the_same_gene_identity(self):
        one = self.world.execute(medications=[DRUG_1])
        two = self.world.execute(medications=[DRUG_1])
        first = self.stored(one)["assessment"].findings
        second = self.stored(two)["assessment"].findings
        self.assertTrue(first)
        self.assertEqual([item.gene_id for item in first],
                         [item.gene_id for item in second])

    def test_the_recorded_identity_is_the_one_the_dataset_holds(self):
        result = self.world.execute(medications=[DRUG_1])
        assessment = self.stored(result)["assessment"]
        for entry in assessment.coverage:
            if entry.drug_id is None:
                continue
            with self.subTest(drug=entry.drug_canonical_key):
                self.assertEqual(
                    entry.drug_id.to_json(),
                    SYNTHETIC_DRUG_IDS[entry.drug_canonical_key])
        for finding in assessment.findings:
            with self.subTest(finding=finding.rule_id.to_json()):
                self.assertIn(finding.gene_id.to_json(),
                              set(SYNTHETIC_GENE_IDS.values()))
                self.assertIn(finding.drug_id.to_json(),
                              set(SYNTHETIC_DRUG_IDS.values()))

    def test_the_persistence_conversion_mints_no_identity(self):
        """The defect, asserted at the exact site it lived at."""
        node = _function(SERVICE_MODULE, "_as_domain_assessment")
        self.assertNotIn("new", _called_attributes(node))
        self.assertNotIn("uuid4", _called_attributes(node))
        self.assertNotIn("uuid4", _called_names(node))

    def test_the_whole_service_module_mints_no_drug_or_gene_identity(self):
        """Checked against the syntax tree, not the text.

        The module *says* ``DrugId.new()`` in a docstring, explaining why it
        must not call one. A text scan would fail on the explanation and teach
        the next person to delete it.
        """
        node = ast.parse(_source(SERVICE_MODULE), filename=SERVICE_MODULE)
        minted = []
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            func = child.func
            if isinstance(func, ast.Attribute) and func.attr == "new" and \
                    isinstance(func.value, ast.Name) and \
                    func.value.id in ("DrugId", "GeneId"):
                minted.append(func.value.id)
        self.assertEqual(minted, [])

    def test_the_stored_rows_carry_the_expected_canonical_identities(self):
        result = self.world.execute(medications=[DRUG_1, DRUG_2])
        assessment = self.stored(result)["assessment"]
        recorded = {entry.drug_canonical_key: entry.drug_id
                    for entry in assessment.coverage}
        self.assertEqual(sorted(recorded), sorted([DRUG_1, DRUG_2]))
        for key, identity in recorded.items():
            with self.subTest(drug=key):
                self.assertEqual(identity.to_json(), SYNTHETIC_DRUG_IDS[key])

    def test_an_unknown_gene_key_fails_closed(self):
        index = synthetic_entity_index()
        with self.assertRaises(AssessmentArtifactError) as caught:
            index.gene_id("GENE:NOT-IN-THE-DATASET")
        self.assertEqual(caught.exception.code,
                         "ASSESSMENT_ENTITY_NOT_RESOLVABLE")

    def test_an_unknown_drug_key_fails_closed(self):
        index = synthetic_entity_index()
        with self.assertRaises(AssessmentArtifactError) as caught:
            index.drug_id(UNKNOWN_DRUG)
        self.assertEqual(caught.exception.code,
                         "ASSESSMENT_ENTITY_NOT_RESOLVABLE")

    def test_an_ambiguous_canonical_key_is_refused(self):
        """Two rows claiming one key is not a tie to be broken."""
        with self.assertRaises(AssessmentArtifactError) as caught:
            CanonicalEntityIndex.from_pairs(
                drugs=((DRUG_1, SYNTHETIC_DRUG_IDS[DRUG_1]),
                       (DRUG_1, SYNTHETIC_DRUG_IDS[DRUG_2])))
        self.assertEqual(caught.exception.code,
                         "ASSESSMENT_ENTITY_NOT_RESOLVABLE")

    def test_the_same_key_twice_with_the_same_identity_is_not_ambiguous(self):
        index = CanonicalEntityIndex.from_pairs(
            drugs=((DRUG_1, SYNTHETIC_DRUG_IDS[DRUG_1]),
                   (DRUG_1, SYNTHETIC_DRUG_IDS[DRUG_1])))
        self.assertEqual(index.drug_id(DRUG_1).to_json(),
                         SYNTHETIC_DRUG_IDS[DRUG_1])

    def test_a_medication_outside_the_dataset_records_no_invented_identity(
            self):
        result = self.world.execute(medications=[DRUG_1, UNKNOWN_DRUG])
        assessment = self.stored(result)["assessment"]
        unknown = [entry for entry in assessment.coverage
                   if entry.drug_canonical_key == UNKNOWN_DRUG]
        self.assertEqual(len(unknown), 1)
        self.assertIsNone(unknown[0].drug_id)
        self.assertEqual(unknown[0].drug_canonical_key, UNKNOWN_DRUG)
        self.assertTrue(unknown[0].reason_codes)

    def test_an_absent_identity_still_names_its_medication(self):
        """Absent identity must not become an absent medication."""
        result = self.world.execute(medications=[DRUG_1, UNKNOWN_DRUG])
        keys = [entry.drug_canonical_key
                for entry in self.stored(result)["assessment"].coverage]
        self.assertIn(UNKNOWN_DRUG, keys)

    def test_a_missing_entity_index_fails_closed(self):
        self.world.resolver.entity_index = None
        with self.assertRaises(AssessmentEngineError) as caught:
            self.world.execute(medications=[DRUG_1])
        self.assertEqual(caught.exception.code,
                         "ASSESSMENT_ENTITY_NOT_RESOLVABLE")

    def test_an_index_that_disagrees_with_the_catalogue_fails_closed(self):
        """A drug the catalogue recognises and the index does not know is a
        disagreement between two pinned artifacts, not a missing drug."""
        self.world.resolver.entity_index = synthetic_entity_index(
            drugs={DRUG_2: SYNTHETIC_DRUG_IDS[DRUG_2]})
        with self.assertRaises(AssessmentEngineError) as caught:
            self.world.execute(medications=[DRUG_1])
        self.assertEqual(caught.exception.code,
                         "ASSESSMENT_ENTITY_NOT_RESOLVABLE")

    def test_a_missing_gene_identity_fails_closed(self):
        self.world.resolver.entity_index = synthetic_entity_index(
            genes={GENE_3: SYNTHETIC_GENE_IDS[GENE_3]})
        with self.assertRaises(AssessmentEngineError) as caught:
            self.world.execute(medications=[DRUG_1])
        self.assertEqual(caught.exception.code,
                         "ASSESSMENT_ENTITY_NOT_RESOLVABLE")

    def test_the_round_trip_preserves_the_exact_identities(self):
        result = self.world.execute(medications=[DRUG_1, DRUG_2])
        stored = self.world.store.get(result.assessment_id)
        self.assertEqual(
            [entry.drug_id for entry in stored.coverage],
            [entry.drug_id for entry in
             self.stored(result)["assessment"].coverage])
        self.assertEqual(
            [(finding.gene_id, finding.drug_id)
             for finding in stored.findings],
            [(finding.gene_id, finding.drug_id) for finding in
             self.stored(result)["assessment"].findings])

    def test_the_index_hashes_deterministically(self):
        self.assertEqual(synthetic_entity_index().content_hash(),
                         synthetic_entity_index().content_hash())

    def test_the_index_is_immutable(self):
        index = synthetic_entity_index()
        with self.assertRaises(Exception):
            index.drugs[DRUG_1] = "something-else"


# ---------------------------------------------------------------------------
# 3.2  The stored input snapshot is complete and reproducible
# ---------------------------------------------------------------------------


class TestTheInputSnapshotIsReproducible(PreflightCase):

    def snapshot(self, **kwargs):
        result = self.world.execute(**kwargs)
        return result, self.stored(result)["input_snapshot"]

    def test_it_names_its_schema_version(self):
        _result, snapshot = self.snapshot(medications=[DRUG_1])
        self.assertEqual(snapshot["input_snapshot_schema_version"],
                         ASSESSMENT_INPUT_SNAPSHOT_SCHEMA_VERSION)

    def test_it_carries_every_required_key(self):
        _result, snapshot = self.snapshot(medications=[DRUG_1])
        for name in SNAPSHOT_REQUIRED_KEYS:
            with self.subTest(key=name):
                self.assertIn(name, snapshot)

    def test_it_carries_the_normalised_profile(self):
        _result, snapshot = self.snapshot(
            medications=[DRUG_1],
            phenotypes={GENE_1: "POOR", GENE_2: "NORMAL"})
        genes = [item["gene_id"] for item in snapshot["profile"]["observations"]]
        self.assertEqual(sorted(genes), sorted([GENE_1, GENE_2]))

    def test_it_carries_every_observation_including_the_failures(self):
        """A profile that dropped what it could not interpret would look
        complete, and the report built from it would look complete too."""
        _result, snapshot = self.snapshot(
            medications=[DRUG_1],
            phenotypes={GENE_1: "POOR", GENE_2: "not-a-phenotype"})
        by_gene = {item["gene_id"]: item
                   for item in snapshot["profile"]["observations"]}
        self.assertEqual(by_gene[GENE_1]["status"], "NORMALIZED")
        self.assertEqual(by_gene[GENE_1]["phenotype"], "POOR")
        self.assertNotEqual(by_gene[GENE_2]["status"], "NORMALIZED")
        self.assertIsNone(by_gene[GENE_2]["phenotype"])
        self.assertTrue(by_gene[GENE_2]["reason_code"])

    def test_it_hashes_back_to_the_assessment_input_hash(self):
        result, snapshot = self.snapshot(medications=[DRUG_1, DRUG_2])
        rebuilt = rebuild_input_semantic_content(snapshot)
        self.assertEqual(sha256_digest(rebuilt), result.input_hash)

    def test_verification_reports_what_it_recomputed(self):
        result, snapshot = self.snapshot(medications=[DRUG_1])
        record = verify_input_snapshot(snapshot, input_hash=result.input_hash)
        self.assertTrue(record["verified"])
        self.assertEqual(record["recomputed_input_hash"], result.input_hash)
        self.assertEqual(record["medication_count"], 1)

    def test_it_holds_no_raw_supplied_value(self):
        _result, snapshot = self.snapshot(
            medications=[DRUG_1], phenotypes={GENE_1: "  poor  "})
        text = str(snapshot)
        self.assertNotIn("raw_value", text)
        self.assertNotIn("  poor  ", text)

    def test_it_holds_no_refused_input_field(self):
        _result, snapshot = self.snapshot(medications=[DRUG_1])
        for name in FORBIDDEN_SNAPSHOT_KEYS:
            with self.subTest(key=name):
                self.assertNotIn('"%s"' % name, str(snapshot))

    def test_a_snapshot_carrying_a_forbidden_key_is_refused(self):
        _result, snapshot = self.snapshot(medications=[DRUG_1])
        tampered = copy.deepcopy(dict(snapshot))
        tampered["profile"]["observations"][0]["raw_value"] = "*1/*2"
        with self.assertRaises(AssessmentInputError) as caught:
            verify_input_snapshot(tampered)
        self.assertEqual(caught.exception.code,
                         "ASSESSMENT_INPUT_SNAPSHOT_INVALID")

    def test_an_incomplete_snapshot_is_refused(self):
        _result, snapshot = self.snapshot(medications=[DRUG_1])
        for name in SNAPSHOT_REQUIRED_KEYS:
            tampered = copy.deepcopy(dict(snapshot))
            tampered.pop(name)
            with self.subTest(missing=name):
                with self.assertRaises(AssessmentInputError):
                    verify_input_snapshot(tampered)

    def test_a_dropped_observation_is_refused(self):
        _result, snapshot = self.snapshot(
            medications=[DRUG_1], phenotypes={GENE_1: "POOR", GENE_2: "POOR"})
        tampered = copy.deepcopy(dict(snapshot))
        tampered["profile"]["observations"].pop()
        with self.assertRaises(AssessmentInputError):
            verify_input_snapshot(tampered)

    def test_a_changed_phenotype_is_refused(self):
        _result, snapshot = self.snapshot(medications=[DRUG_1])
        tampered = copy.deepcopy(dict(snapshot))
        tampered["profile"]["observations"][0]["phenotype"] = "NORMAL"
        with self.assertRaises(AssessmentInputError):
            verify_input_snapshot(tampered)

    def test_a_changed_medication_list_is_refused(self):
        _result, snapshot = self.snapshot(medications=[DRUG_1])
        tampered = copy.deepcopy(dict(snapshot))
        tampered["medications"] = [DRUG_2]
        with self.assertRaises(AssessmentInputError):
            verify_input_snapshot(tampered)

    def test_an_unknown_schema_version_is_refused(self):
        _result, snapshot = self.snapshot(medications=[DRUG_1])
        tampered = copy.deepcopy(dict(snapshot))
        tampered["input_snapshot_schema_version"] = "pgx-something-else/9"
        with self.assertRaises(AssessmentInputError):
            verify_input_snapshot(tampered)

    def test_a_snapshot_of_a_different_question_is_refused(self):
        """The row and the snapshot are compared against each other, not each
        against itself."""
        _one, first = self.snapshot(medications=[DRUG_1])
        two = self.world.execute(medications=[DRUG_2])
        with self.assertRaises(AssessmentInputError) as caught:
            verify_input_snapshot(first, input_hash=two.input_hash)
        self.assertEqual(caught.exception.code,
                         "ASSESSMENT_INPUT_SNAPSHOT_INVALID")

    def test_an_unknown_observation_field_is_refused(self):
        _result, snapshot = self.snapshot(medications=[DRUG_1])
        tampered = copy.deepcopy(dict(snapshot))
        tampered["profile"]["observations"][0]["confidence"] = 0.9
        with self.assertRaises(AssessmentInputError):
            verify_input_snapshot(tampered)

    def test_the_case_id_is_recorded_and_stays_outside_the_hash(self):
        one = self.world.execute(medications=[DRUG_1], case_id="CASE-A")
        two = self.world.execute(medications=[DRUG_1], case_id="CASE-B")
        self.assertEqual(self.stored(one)["input_snapshot"]["case_id"],
                         "CASE-A")
        self.assertEqual(self.stored(two)["input_snapshot"]["case_id"],
                         "CASE-B")
        self.assertEqual(one.input_hash, two.input_hash)

    def test_building_a_snapshot_verifies_it(self):
        request = self.world.input(medications=[DRUG_1])
        snapshot = build_input_snapshot(request)
        self.assertEqual(snapshot["input_hash"], request.content_hash())


# ---------------------------------------------------------------------------
# 3.3  The coverage result is embedded whole
# ---------------------------------------------------------------------------


class TestTheCoverageResultIsEmbeddedWhole(PreflightCase):

    def document(self, **kwargs):
        return self.world.dry_run(**kwargs).semantic_content()

    def test_the_stored_computation_carries_the_whole_result(self):
        content = self.document(
            medications=[DRUG_1],
            phenotypes={GENE_1: "POOR", GENE_2: "POOR", GENE_3: "NORMAL"})
        embedded = content["coverage_result"]
        self.assertEqual(embedded["medication_count"],
                         len(embedded["medications"]))
        axes = [axis for item in embedded["medications"]
                for axis in item["axes"]]
        self.assertTrue(axes)

    def test_every_axis_carries_its_status_phenotype_and_reasons(self):
        content = self.document(
            medications=[DRUG_1],
            phenotypes={GENE_1: "POOR", GENE_2: "POOR", GENE_3: "NORMAL"})
        for medication in content["coverage_result"]["medications"]:
            for axis in medication["axes"]:
                with self.subTest(axis=(axis["drug_id"], axis["gene_id"])):
                    self.assertIn("status", axis)
                    self.assertIn("observed_phenotype", axis)
                    self.assertIn("reason_codes", axis)
                    self.assertIn("observation_state", axis)
                    self.assertIn("rule_references", axis)
                    self.assertIn("evidence_references", axis)
                    self.assertIn("conflict_references", axis)

    def test_a_full_axis_still_names_its_rule_and_evidence(self):
        content = self.document(medications=[DRUG_1],
                                phenotypes={GENE_1: "POOR", GENE_2: "POOR"})
        full = [axis for medication in content["coverage_result"]["medications"]
                for axis in medication["axes"]
                if axis["status"] == CoverageStatus.FULL.value]
        self.assertTrue(full)
        for axis in full:
            with self.subTest(gene=axis["gene_id"]):
                self.assertTrue(axis["rule_references"])
                self.assertTrue(axis["evidence_references"])

    def test_an_uncovered_axis_still_names_why(self):
        content = self.document(
            medications=[DRUG_1],
            phenotypes={GENE_1: "POOR", GENE_2: "POOR", GENE_3: "NORMAL"})
        uncovered = [axis
                     for medication in content["coverage_result"]["medications"]
                     for axis in medication["axes"]
                     if axis["status"] != CoverageStatus.FULL.value]
        for axis in uncovered:
            with self.subTest(gene=axis["gene_id"]):
                self.assertTrue(axis["reason_codes"])

    def test_the_result_is_not_reduced_to_counts(self):
        content = self.document(medications=[DRUG_1])
        embedded = content["coverage_result"]
        self.assertNotEqual(sorted(embedded), ["medication_count", "status"])
        self.assertIn("profile_content_hash", embedded)
        self.assertIn("ruleset_content_hash", embedded)

    def test_the_hash_is_retained_beside_the_document(self):
        content = self.document(medications=[DRUG_1])
        self.assertIn("coverage_result_hash", content)
        self.assertEqual(content["coverage_result"]["content_hash"],
                         content["coverage_result_hash"])

    def test_the_embedded_result_is_verified_against_the_hash(self):
        content = self.document(medications=[DRUG_1])
        verified = embedded_coverage_result(content)
        self.assertEqual(verified["content_hash"],
                         content["coverage_result_hash"])

    def test_a_tampered_embedded_result_is_refused(self):
        content = copy.deepcopy(self.document(medications=[DRUG_1]))
        content["coverage_result"]["status"] = "FULL"
        with self.assertRaises(AssessmentArtifactError):
            embedded_coverage_result(content)

    def test_a_missing_embedded_result_is_refused(self):
        content = copy.deepcopy(self.document(medications=[DRUG_1]))
        content.pop("coverage_result")
        with self.assertRaises(AssessmentArtifactError):
            embedded_coverage_result(content)

    def test_a_conflict_reference_would_survive_the_projection(self):
        """Nothing in the projection filters axis references by status."""
        content = self.document(medications=[DRUG_1])
        for medication in content["coverage_result"]["medications"]:
            for axis in medication["axes"]:
                with self.subTest(gene=axis["gene_id"]):
                    self.assertIsInstance(axis["conflict_references"], list)


# ---------------------------------------------------------------------------
# 3.4  Retrieval returns a lossless render source
# ---------------------------------------------------------------------------


class TestTheReadModelIsLossless(PreflightCase):

    def read_model(self, **kwargs):
        result = self.world.execute(**kwargs)
        return result, self.world.store.read_model(result.assessment_id)

    def test_it_returns_none_for_an_assessment_that_is_not_stored(self):
        from pgx.domain.identifiers import AssessmentId
        self.assertIsNone(self.world.store.read_model(AssessmentId.new()))

    def test_it_names_its_schema_version(self):
        _result, view = self.read_model(medications=[DRUG_1])
        self.assertEqual(view.read_model_schema_version,
                         ASSESSMENT_READ_MODEL_SCHEMA_VERSION)

    def test_it_returns_every_axis(self):
        _result, view = self.read_model(
            medications=[DRUG_1],
            phenotypes={GENE_1: "POOR", GENE_2: "POOR", GENE_3: "NORMAL"})
        embedded = [axis for medication in view.coverage_result["medications"]
                    for axis in medication["axes"]]
        self.assertEqual(len(view.axes), len(embedded))
        self.assertTrue(view.axes_for(DRUG_1))

    def test_it_returns_every_finding_with_its_provenance(self):
        _result, view = self.read_model(medications=[DRUG_1])
        self.assertTrue(view.findings)
        for finding in view.findings:
            with self.subTest(gene=finding["gene_canonical_key"]):
                for name in ("rule_id", "rule_version", "rule_content_hash",
                             "rationale_reference", "curation_revision_id",
                             "curation_revision_hash", "evidence_record_ids"):
                    self.assertTrue(finding[name], name)

    def test_it_returns_the_whole_input_snapshot(self):
        import json
        result, view = self.read_model(medications=[DRUG_1])
        self.assertEqual(
            json.loads(json.dumps(view.to_json()["input_snapshot"],
                                  sort_keys=True)),
            json.loads(json.dumps(self.stored(result)["input_snapshot"],
                                  sort_keys=True)))
        self.assertTrue(view.input_snapshot["profile"]["observations"])

    def test_it_returns_every_pinned_version(self):
        result, view = self.read_model(medications=[DRUG_1])
        expected = result.pinned.provenance.to_json()
        for name, value in expected.items():
            if name in POINTER_AUDIT_FIELDS:
                continue
            with self.subTest(field=name):
                self.assertEqual(view.release_provenance[name], value)

    def test_it_returns_the_pointer_generation_it_does_not_hash(self):
        result, view = self.read_model(medications=[DRUG_1])
        self.assertEqual(view.pointer_audit["active_pointer_generation"],
                         result.pinned.active_pointer_generation)

    def test_it_reports_what_it_verified(self):
        result, view = self.read_model(medications=[DRUG_1])
        self.assertEqual(view.verification["recomputed_output_hash"],
                         result.output_hash)
        self.assertTrue(view.verification["row_and_snapshot_agree"])
        self.assertTrue(view.verification["input_snapshot"]["verified"])

    def test_it_carries_everything_the_summary_carried(self):
        """The summary is not replaced, so nothing that read it breaks - but
        every fact it held must still be reachable from the richer view, or
        the read model would be lossless in name only."""
        import json
        result, view = self.read_model(medications=[DRUG_1, DRUG_2])
        summary = self.world.store.summary(result.assessment_id)
        self.assertEqual(view.assessment_id, summary["assessment_id"])
        self.assertEqual(view.input_hash, summary["input_hash"])
        self.assertEqual(view.output_hash, summary["output_hash"])
        self.assertEqual(view.overall_coverage, summary["overall_coverage"])
        self.assertEqual(view.overall_attention, summary["overall_attention"])
        self.assertEqual(view.release_provenance["release_public_id"],
                         summary["release_public_id"])
        self.assertEqual(view.medication_count, summary["medication_count"])
        self.assertEqual(view.finding_count, summary["finding_count"])
        self.assertEqual(
            json.loads(json.dumps(view.to_json()["computation"],
                                  sort_keys=True)),
            json.loads(json.dumps(summary["output_snapshot"],
                                  sort_keys=True)))

    def test_it_is_strictly_richer_than_the_summary(self):
        _result, view = self.read_model(medications=[DRUG_1, DRUG_2])
        document = view.to_json()
        for name in ("axes", "findings", "coverage_result", "input_snapshot",
                     "release_provenance", "verification", "pointer_audit"):
            with self.subTest(field=name):
                self.assertIn(name, document)
        self.assertTrue(document["axes"])
        self.assertTrue(document["findings"])

    def test_it_is_deeply_immutable(self):
        _result, view = self.read_model(medications=[DRUG_1])
        with self.assertRaises(Exception):
            view.computation["overall_attention"] = "HIGH"
        with self.assertRaises(Exception):
            view.medications[0]["attention_level"] = "HIGH"

    def test_a_row_missing_a_column_is_refused(self):
        result = self.world.execute(medications=[DRUG_1])
        stored = self.stored(result)
        for name in READ_MODEL_ROW_KEYS:
            row = assessment_row_mapping(stored)
            row.pop(name)
            with self.subTest(missing=name):
                with self.assertRaises(AssessmentPersistenceError):
                    build_assessment_read_model(row=row)

    def test_a_row_that_disagrees_with_its_snapshot_is_refused(self):
        result = self.world.execute(medications=[DRUG_1])
        stored = self.stored(result)
        row = assessment_row_mapping(stored)
        row["overall_attention"] = "HIGH"
        with self.assertRaises(AssessmentPersistenceError):
            build_assessment_read_model(
                row=row,
                medications=medication_row_mappings(stored["computation"]),
                axes=axis_row_mappings(stored["computation"]),
                findings=finding_row_mappings(stored["computation"]))

    def test_a_tampered_output_snapshot_is_refused(self):
        result = self.world.execute(medications=[DRUG_1])
        stored = self.stored(result)
        row = assessment_row_mapping(stored)
        row["output_snapshot"] = copy.deepcopy(dict(row["output_snapshot"]))
        row["output_snapshot"]["warnings"] = ["invented"]
        with self.assertRaises(AssessmentPersistenceError):
            build_assessment_read_model(row=row)

    def test_a_missing_medication_row_is_refused(self):
        result = self.world.execute(medications=[DRUG_1, DRUG_2])
        stored = self.stored(result)
        with self.assertRaises(AssessmentPersistenceError):
            build_assessment_read_model(
                row=assessment_row_mapping(stored),
                medications=medication_row_mappings(
                    stored["computation"])[:1],
                axes=axis_row_mappings(stored["computation"]),
                findings=finding_row_mappings(stored["computation"]))

    def test_a_finding_without_evidence_is_refused(self):
        result = self.world.execute(medications=[DRUG_1])
        stored = self.stored(result)
        findings = finding_row_mappings(stored["computation"])
        self.assertTrue(findings)
        findings[0] = dict(findings[0], evidence_record_ids=[])
        with self.assertRaises(AssessmentArtifactError):
            build_assessment_read_model(
                row=assessment_row_mapping(stored),
                medications=medication_row_mappings(stored["computation"]),
                axes=axis_row_mappings(stored["computation"]),
                findings=findings)

    def test_reconstruction_invokes_no_engine(self):
        """The property that makes a report a projection rather than a second
        calculation, asserted by name against the module's own source."""
        text = _source(READ_MODEL_MODULE)
        for forbidden in ("calculate_assessment", "evaluate_coverage",
                          "evaluate_axis_finding", "aggregate_attention",
                          "match_observation", "normalize_profile",
                          "FrozenRulesetRegistry", "release_resolver",
                          "resolve(", "active_release"):
            with self.subTest(call=forbidden):
                self.assertNotIn(forbidden, text)

    def test_reconstruction_imports_no_engine_calculation(self):
        node = ast.parse(_source(READ_MODEL_MODULE))
        imported = set()
        for child in ast.walk(node):
            if isinstance(child, ast.ImportFrom) and child.module:
                imported.update("%s.%s" % (child.module, alias.name)
                                for alias in child.names)
        for forbidden in ("pgx.engine.risk.calculate_assessment",
                          "pgx.engine.coverage.evaluate_coverage",
                          "pgx.rules.registry.FrozenRulesetRegistry"):
            with self.subTest(name=forbidden):
                self.assertNotIn(forbidden, imported)

    def test_the_sql_adapter_publishes_the_same_read_model(self):
        """SQLAlchemy cannot be installed in this environment, so the adapter
        is checked by reading it. What is checked is not that it *works* - no
        such claim is made anywhere - but that it calls the same builder over
        the same columns as the in-memory adapter the tests do exercise."""
        node = _function(DB_ADAPTER_MODULE, "read_model")
        self.assertIn("build_assessment_read_model", _called_names(node))

    def test_the_in_memory_row_shape_matches_the_sql_adapter(self):
        node = _function(DB_ADAPTER_MODULE, "_assessment_row_to_mapping")
        keys = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Dict):
                keys.update(item.value for item in child.keys
                            if isinstance(item, ast.Constant))
        result = self.world.execute(medications=[DRUG_1])
        produced = set(assessment_row_mapping(self.stored(result)))
        self.assertEqual(keys, produced)
        self.assertTrue(set(READ_MODEL_ROW_KEYS) <= keys)


# ---------------------------------------------------------------------------
# 3.5  Pointer audit metadata is recorded, and is not part of the output hash
# ---------------------------------------------------------------------------


class TestPointerMetadataIsSeparateFromTheOutputHash(PreflightCase):

    def test_two_executions_across_a_pointer_move_share_an_output_hash(self):
        one = self.world.execute(medications=[DRUG_1])
        self.world.resolver.move_pointer()
        two = self.world.execute(medications=[DRUG_1])
        self.assertNotEqual(one.pinned.active_pointer_generation,
                            two.pinned.active_pointer_generation)
        self.assertEqual(one.output_hash, two.output_hash)

    def test_both_generations_are_still_stored(self):
        one = self.world.execute(medications=[DRUG_1])
        self.world.resolver.move_pointer()
        two = self.world.execute(medications=[DRUG_1])
        self.assertEqual(
            self.stored(one)["provenance"].active_pointer_generation, 1)
        self.assertEqual(
            self.stored(two)["provenance"].active_pointer_generation, 2)

    def test_the_envelope_key_list_is_published(self):
        self.assertIn("pointer_audit", COMPUTATION_ENVELOPE_KEYS)
        self.assertIn("output_hash", COMPUTATION_ENVELOPE_KEYS)

    def test_the_projection_strips_exactly_the_envelope(self):
        computation = self.world.dry_run(medications=[DRUG_1])
        document = computation.to_json()
        projection = hashed_projection(document)
        self.assertEqual(sorted(set(document) - set(projection)),
                         sorted(COMPUTATION_ENVELOPE_KEYS[:3]))
        self.assertEqual(sha256_digest(projection), document["output_hash"])


if __name__ == "__main__":
    unittest.main()
