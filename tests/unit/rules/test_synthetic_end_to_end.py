# -*- coding: utf-8 -*-
"""One synthetic rule, from draft to an engine-readable ruleset (WP-11).

This is the proof that the machinery works. Every value in it is invented -
``GENE:TESTGENE1``, ``DRUG:testdrug-alpha``, actors whose names begin
``TEST-``, a dataset dated 2999 - and the fixtures say so in four ways at
once: SYNTHETIC, TEST ONLY, NOT CLINICAL DATA, NOT FOR REAL ASSESSMENT.

Read this file as a demonstration that the state machine, the builder, the
artifact format and the registry compose correctly. Do not read it as a
demonstration that anything here is true about any medicine. Every gate this
walk passes through was opened by a fixture, and the same walk on real data
stops at the first one - which is what ``test_real_gate_status`` asserts.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest

from pgx.domain.enums import RuleStatus, RulesetStatus
from pgx.rules.registry import FrozenRulesetRegistry
from pgx.rules.serialization import verify_checksums
from tests.fixtures.wp11.synthetic import (SYNTHETIC_DRUG, SYNTHETIC_GENE,
                                           SYNTHETIC_MARKERS, TEST_AUTHOR,
                                           TEST_BUILDER, TEST_VALIDATOR,
                                           frozen_ruleset)
from tests.unit.rules._support import DEFAULT_REGISTRY_ROOT, REPO_ROOT


class TestTheWholeWalk(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.root = os.path.join(cls.tmp, "rulesets")
        os.makedirs(cls.root)
        cls.destination = os.path.join(cls.root, "PGX-RULESET-29991231-001")
        (cls.service, cls.store, cls.definitions,
         cls.result) = frozen_ruleset(cls.destination, count=2)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_it_ends_frozen(self):
        self.assertEqual(self.result.ruleset.status, RulesetStatus.FROZEN)

    def test_every_member_rule_reached_validated(self):
        lifecycles = self.store.snapshot()["lifecycles"]
        for definition in self.definitions:
            record = lifecycles[definition.rule_id.to_json()]
            with self.subTest(rule=definition.rule_id.to_json()):
                self.assertEqual(record.status, RuleStatus.VALIDATED)

    def test_the_artifact_verifies(self):
        self.assertEqual(sorted(verify_checksums(self.destination)),
                         ["approval-list.json", "build-log.json",
                          "manifest.json", "rules.ndjson"])

    def test_the_registry_serves_it(self):
        registry = FrozenRulesetRegistry(self.root)
        self.assertEqual(registry.list_executable(),
                         ("PGX-RULESET-29991231-001",))
        loaded = registry.load("PGX-RULESET-29991231-001")
        self.assertEqual(loaded.member_count, 2)

    def test_the_served_rules_are_the_rules_that_were_validated(self):
        loaded = FrozenRulesetRegistry(self.root).load(
            "PGX-RULESET-29991231-001")
        self.assertEqual(
            {definition.content_hash() for definition in loaded.rules()},
            {definition.content_hash() for definition in self.definitions})

    def test_every_separated_act_was_performed_by_a_different_actor(self):
        with io.open(os.path.join(self.destination, "approval-list.json"),
                     encoding="utf-8") as handle:
            approvals = json.load(handle)
        for entry in approvals["entries"]:
            with self.subTest(rule=entry["rule_id"]):
                self.assertNotEqual(entry["created_by"], entry["reviewed_by"])
                self.assertNotEqual(entry["created_by"], entry["approved_by"])
                self.assertNotEqual(entry["created_by"], entry["validated_by"])

    def test_the_audit_trail_records_the_whole_walk(self):
        actions = [event["action"] for event in self.store.snapshot()["audit"]]
        self.assertEqual(actions, [
            "RULE_DRAFTED", "RULE_CURATED", "RULE_VALIDATED",
            "RULE_DRAFTED", "RULE_CURATED", "RULE_VALIDATED",
            "RULESET_CREATED", "RULESET_MEMBER_ADDED", "RULESET_MEMBER_ADDED",
            "RULESET_VALIDATED", "RULESET_FROZEN"])

    def test_every_audit_event_names_an_actor(self):
        for event in self.store.snapshot()["audit"]:
            with self.subTest(action=event["action"]):
                self.assertTrue(event["actor"].startswith("TEST-"))


class TestTheFixturesAnnounceThemselves(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.destination = os.path.join(self.tmp, "PGX-RULESET-29991231-001")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        frozen_ruleset(self.destination, count=1)

    def test_every_rule_carries_all_four_markers(self):
        with io.open(os.path.join(self.destination, "rules.ndjson"),
                     encoding="utf-8") as handle:
            for line in handle:
                document = json.loads(line)
                with self.subTest(rule=document["rule_id"]):
                    markers = document["metadata"]["markers"]
                    self.assertEqual(tuple(markers), SYNTHETIC_MARKERS)

    def test_the_fixture_module_says_what_it_is_in_its_first_line(self):
        from tests.unit.rules._support import source
        path = os.path.join(REPO_ROOT, "tests", "fixtures", "wp11",
                            "synthetic.py")
        first = source(path).splitlines()[1]
        self.assertIn("SYNTHETIC", first)
        self.assertIn("TEST ONLY", first)
        self.assertIn("NOT CLINICAL DATA", first)

    def test_the_synthetic_entities_are_not_real_ones(self):
        """A fixture naming CYP2C19 and clopidogrel would read as a claim
        about them, and screenshots of tests outlive their context."""
        self.assertEqual(SYNTHETIC_GENE, "GENE:TESTGENE1")
        self.assertEqual(SYNTHETIC_DRUG, "DRUG:testdrug-alpha")
        canonical = os.path.join(REPO_ROOT, "data", "canonical")
        if not os.path.isdir(canonical):
            return
        for root, _dirs, files in os.walk(canonical):
            for name in files:
                if not name.endswith((".json", ".ndjson")):
                    continue
                with io.open(os.path.join(root, name),
                             encoding="utf-8") as handle:
                    text = handle.read()
                with self.subTest(file=name):
                    self.assertNotIn("TESTGENE1", text)
                    self.assertNotIn("testdrug-alpha", text)

    def test_the_actors_are_all_test_prefixed(self):
        for actor in (TEST_AUTHOR, TEST_VALIDATOR, TEST_BUILDER):
            with self.subTest(actor=actor):
                self.assertTrue(actor.startswith("TEST-"))


class TestTheFixturesAreNowhereNearProduction(unittest.TestCase):

    def test_no_test_writes_an_artifact_into_the_production_root(self):
        """A fixture published into the production registry root would be
        served to an engine as if somebody had approved it.

        The needles are assembled from parts rather than written out, because
        a test containing the literal it forbids finds itself and fails for
        the wrong reason - which is exactly what happened when this was
        written the obvious way.
        """
        from tests.unit.rules._support import source
        import glob
        prefix = "PGX-RULE" + "SET"
        needles = ('"data", "rule' + 'sets", "%s' % prefix,
                   "data/rule" + "sets/%s" % prefix)
        for path in glob.glob(os.path.join(REPO_ROOT, "tests", "**", "*.py"),
                              recursive=True):
            text = source(path)
            with self.subTest(module=os.path.relpath(path, REPO_ROOT)):
                for needle in needles:
                    self.assertNotIn(needle, text)

    def test_the_production_registry_is_still_empty_after_all_of_this(self):
        self.assertEqual(
            FrozenRulesetRegistry(DEFAULT_REGISTRY_ROOT).list_executable(), ())

    def test_the_fixture_dataset_is_dated_in_the_far_future(self):
        """``PGX-DATA-29991231-001`` cannot collide with a real dataset id,
        and reads as obviously invented in any log line it appears in."""
        from tests.fixtures.wp11.synthetic import SYNTHETIC_DATASET
        self.assertEqual(SYNTHETIC_DATASET.to_json(), "PGX-DATA-29991231-001")


if __name__ == "__main__":
    unittest.main()
