# -*- coding: utf-8 -*-
"""The six published WP-11 schemas.

Each is checked two ways: real output validates against it, and a document
that lies in the way a hand-edited file would most usefully lie does not. A
schema nothing has ever failed is a description, not a constraint.

The validator refuses any keyword it does not implement, so a schema here can
only assert things that are actually checked.
"""

from __future__ import annotations

import copy
import datetime as _dt
import io
import json
import os
import shutil
import tempfile
import unittest

from pgx.application.rule_gate_status import build_gate_status
from pgx.application.rules_schema import (WP11_SCHEMA_PATHS, load_schema,
                                          validate_computable_rule,
                                          validate_legacy_rule_candidate_inventory,
                                          validate_ruleset_approval_list,
                                          validate_ruleset_build_log,
                                          validate_ruleset_manifest,
                                          validate_wp11_gate_status)
from pgx.rules.builder import compose_artifact
from pgx.rules.identifiers import RulesetBuildId
from pgx.rules.legacy import build_inventory
from tests.fixtures.wp11.synthetic import (synthetic_build_inputs,
                                           synthetic_condition, synthetic_rule)
from tests.unit.rules._support import REPO_ROOT

MOMENT = _dt.datetime(2099, 1, 1, 12, 0, tzinfo=_dt.timezone.utc)


def _artifact():
    definitions = (synthetic_rule(),
                   synthetic_rule(
                       condition=synthetic_condition(gene="GENE:TESTGENE2")))
    _manifest, files, _digest = compose_artifact(
        synthetic_build_inputs(definitions),
        built_by="TEST-rule-builder-1", started_at=MOMENT,
        completed_at=MOMENT,
        build_id=RulesetBuildId.parse("dddddddd-0000-4000-8000-000000000001"),
        artifact_relative_path="PGX-RULESET-29991231-001")
    return {
        "rule": json.loads(files["rules.ndjson"].decode("utf-8").splitlines()[0]),
        "manifest": json.loads(files["manifest.json"].decode("utf-8")),
        "build_log": json.loads(files["build-log.json"].decode("utf-8")),
        "approval_list": json.loads(
            files["approval-list.json"].decode("utf-8")),
    }


class TestEverySchemaIsWellFormedAndUsed(unittest.TestCase):

    def test_all_six_are_published(self):
        for path in WP11_SCHEMA_PATHS:
            with self.subTest(schema=os.path.basename(path)):
                self.assertTrue(os.path.isfile(path))

    def test_each_declares_an_id_and_a_description(self):
        for path in WP11_SCHEMA_PATHS:
            document = load_schema(path)
            with self.subTest(schema=os.path.basename(path)):
                self.assertIn("$id", document)
                self.assertGreater(len(document["description"]), 100,
                                   "a schema whose description does not say "
                                   "what it refuses is documentation debt")

    def test_each_forbids_unknown_properties(self):
        for path in WP11_SCHEMA_PATHS:
            document = load_schema(path)
            with self.subTest(schema=os.path.basename(path)):
                self.assertIs(document["additionalProperties"], False)


class TestRealOutputValidates(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.documents = _artifact()

    def test_a_real_rule_validates(self):
        self.assertEqual(validate_computable_rule(self.documents["rule"]), ())

    def test_a_real_manifest_validates(self):
        self.assertEqual(
            validate_ruleset_manifest(self.documents["manifest"]), ())

    def test_a_real_build_log_validates(self):
        self.assertEqual(
            validate_ruleset_build_log(self.documents["build_log"]), ())

    def test_a_real_approval_list_validates(self):
        self.assertEqual(
            validate_ruleset_approval_list(self.documents["approval_list"]),
            ())

    def test_the_real_gate_status_validates(self):
        self.assertEqual(
            validate_wp11_gate_status(build_gate_status(REPO_ROOT).to_json()),
            ())

    def test_the_real_legacy_inventory_validates(self):
        self.assertEqual(
            validate_legacy_rule_candidate_inventory(
                build_inventory(REPO_ROOT).to_json()), ())


class TestTheRuleSchemaRefusesTheUsefulLies(unittest.TestCase):

    def setUp(self):
        self.rule = _artifact()["rule"]

    def _refused(self, mutate):
        document = copy.deepcopy(self.rule)
        mutate(document)
        return validate_computable_rule(document)

    def test_a_wildcard_gene_is_refused(self):
        self.assertTrue(self._refused(
            lambda doc: doc["condition"].update(gene_id="*")))

    def test_a_gene_carrying_free_text_is_refused(self):
        self.assertTrue(self._refused(
            lambda doc: doc["condition"].update(
                gene_id="GENE:CYP2D6 or any hepatic gene")))

    def test_an_unknown_operator_is_refused(self):
        self.assertTrue(self._refused(
            lambda doc: doc["condition"]["phenotype"].update(
                operator="REGEX")))

    def test_an_exact_match_on_two_values_is_refused(self):
        self.assertTrue(self._refused(
            lambda doc: doc["condition"]["phenotype"].update(
                values=["POOR", "RAPID"])))

    def test_a_repeated_phenotype_is_refused(self):
        self.assertTrue(self._refused(
            lambda doc: doc["condition"]["phenotype"].update(
                operator="ONE_OF", values=["POOR", "POOR"])))

    def test_indeterminate_is_refused(self):
        self.assertTrue(self._refused(
            lambda doc: doc["condition"]["phenotype"].update(
                values=["INDETERMINATE"])))

    def test_an_extra_condition_key_is_refused(self):
        self.assertTrue(self._refused(
            lambda doc: doc["condition"].update(unless="pregnant")))

    def test_a_dose_in_the_outcome_is_refused(self):
        self.assertTrue(self._refused(
            lambda doc: doc["outcome"].update(dose="50 mg")))

    def test_a_recommendation_in_the_outcome_is_refused(self):
        self.assertTrue(self._refused(
            lambda doc: doc["outcome"].update(
                recommendation="use an alternative")))

    def test_not_assessed_as_an_outcome_is_refused(self):
        self.assertTrue(self._refused(
            lambda doc: doc["outcome"].update(
                attention_level="NOT_ASSESSED")))

    def test_a_rule_with_no_evidence_is_refused(self):
        self.assertTrue(self._refused(
            lambda doc: doc["provenance"].update(evidence_record_uuids=[])))

    def test_a_rule_without_a_curated_revision_is_refused(self):
        self.assertTrue(self._refused(
            lambda doc: doc["provenance"].pop("curation_revision_id")))

    def test_a_rule_without_an_approval_envelope_is_refused(self):
        self.assertTrue(self._refused(
            lambda doc: doc["provenance"].pop("approval_envelope_hash")))


class TestTheOtherSchemasRefuseTheirOwnUsefulLies(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.documents = _artifact()

    def test_a_manifest_member_without_a_hash_is_refused(self):
        manifest = copy.deepcopy(self.documents["manifest"])
        manifest["members"][0].pop("content_hash")
        self.assertTrue(validate_ruleset_manifest(manifest))

    def test_a_manifest_claiming_coverage_is_refused(self):
        manifest = copy.deepcopy(self.documents["manifest"])
        manifest["coverage_percent"] = 100
        self.assertTrue(validate_ruleset_manifest(manifest))

    def test_an_approval_entry_missing_a_role_is_refused(self):
        approvals = copy.deepcopy(self.documents["approval_list"])
        approvals["entries"][0].pop("reviewed_by")
        self.assertTrue(validate_ruleset_approval_list(approvals))

    def test_a_build_log_with_an_unknown_outcome_is_refused(self):
        log = copy.deepcopy(self.documents["build_log"])
        log["outcome"] = "PARTIAL"
        self.assertTrue(validate_ruleset_build_log(log))

    def test_a_gate_status_with_no_blockers_is_refused(self):
        """The most important refusal in this file: the gate report cannot be
        edited into an all-clear by deleting the reasons."""
        status = copy.deepcopy(build_gate_status(REPO_ROOT).to_json())
        status["blockers"] = []
        self.assertTrue(validate_wp11_gate_status(status))

    def test_a_gate_status_missing_a_real_count_is_refused(self):
        status = copy.deepcopy(build_gate_status(REPO_ROOT).to_json())
        status["rule_state"].pop("real_validated_rules")
        self.assertTrue(validate_wp11_gate_status(status))

    def test_an_inventory_candidate_eligible_while_blocked_is_refused(self):
        inventory = build_inventory(REPO_ROOT).to_json()
        inventory = dict(inventory, candidates=inventory["candidates"][:1])
        inventory["candidates"][0] = dict(inventory["candidates"][0],
                                          eligible_for_rule_creation=True)
        self.assertTrue(
            validate_legacy_rule_candidate_inventory(inventory))

    def test_an_inventory_carrying_an_attention_level_is_refused(self):
        inventory = build_inventory(REPO_ROOT).to_json()
        inventory = dict(inventory, candidates=inventory["candidates"][:1])
        inventory["candidates"][0] = dict(inventory["candidates"][0],
                                          attention_level="LOW")
        self.assertTrue(
            validate_legacy_rule_candidate_inventory(inventory))

    def test_an_inventory_claiming_it_created_rules_is_refused(self):
        inventory = build_inventory(REPO_ROOT).to_json()
        inventory = dict(inventory, candidates=inventory["candidates"][:1])
        inventory["counts"] = dict(inventory["counts"], rules_created=1)
        self.assertTrue(
            validate_legacy_rule_candidate_inventory(inventory))


if __name__ == "__main__":
    unittest.main()
