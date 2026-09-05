# -*- coding: utf-8 -*-
"""What the real data actually permits (WP-11).

This is the file that reports the truth about this repository: no real
computable rule exists, none may be created, and the reasons are all human
rather than technical. Every count below is asserted to be zero, and the test
that matters most is the one asserting that every blocker names a person as
its owner - because a blocker owned by "the system" would be one somebody
could imagine coding around.

A future where these tests fail is a future where somebody has approved
something. That should require editing this file, deliberately, with the
approvals in hand.
"""

from __future__ import annotations

import io
import json
import unittest

from pgx.application.rule_gate_status import (BLOCKER_CODES,
                                              GATE_STATUS_VERSION,
                                              build_gate_status,
                                              build_real_build_attempt)
from pgx.rules.registry import FrozenRulesetRegistry
from tests.unit.rules._support import (BUILD_ATTEMPT_JSON,
                                       DEFAULT_REGISTRY_ROOT,
                                       GATE_STATUS_JSON, REPO_ROOT)


class TestNoRealRuleExistsOrMay(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.status = build_gate_status(REPO_ROOT).to_json()

    def test_every_real_rule_count_is_zero(self):
        for name, value in sorted(self.status["rule_state"].items()):
            with self.subTest(count=name):
                self.assertEqual(value, 0)

    def test_no_curated_interpretation_exists(self):
        self.assertEqual(self.status["curation_state"]
                         ["curated_interpretations"], 0)

    def test_no_rule_approval_envelope_is_eligible(self):
        self.assertEqual(self.status["curation_state"]
                         ["eligible_rule_approval_envelopes"], 0)

    def test_the_upstream_gates_are_all_shut(self):
        upstream = self.status["upstream_state"]
        self.assertFalse(upstream["curation_protocol_approved"])
        self.assertFalse(upstream["canonical_dataset_published"])
        self.assertFalse(upstream["evidence_build_approved_for_rules"])
        self.assertEqual(upstream["source_registry_approved"], 0)

    def test_the_assessment_says_blocked(self):
        self.assertIn("BLOCKED", self.status["assessment"])

    def test_the_default_registry_agrees(self):
        registry = FrozenRulesetRegistry(DEFAULT_REGISTRY_ROOT)
        self.assertEqual(registry.list_executable(), ())
        self.assertEqual(
            self.status["rule_state"]
            ["executable_rulesets_in_default_registry"], 0)


class TestEveryBlockerIsSomebodysDecision(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.status = build_gate_status(REPO_ROOT).to_json()

    def test_there_is_at_least_one_blocker(self):
        self.assertTrue(self.status["blockers"])

    def test_every_blocker_is_a_documented_code(self):
        for blocker in self.status["blockers"]:
            with self.subTest(code=blocker["code"]):
                self.assertIn(blocker["code"], BLOCKER_CODES)

    #: Words that would mean a blocker is waiting on software. ``code`` is
    #: absent from this list because one owner says "a named scientific expert
    #: (not code)" - the phrase is there to rule software *out*.
    MACHINE_OWNERS = ("script", "pipeline", "job", "automation", "the system",
                      "cron", "batch", "the tool", "this repository")

    def test_every_blocker_names_a_person_or_a_human_process(self):
        """The point of the whole file. If any owner here were a piece of
        software, somebody would eventually try to make the software do it."""
        for blocker in self.status["blockers"]:
            owner = blocker["owner"].lower()
            with self.subTest(code=blocker["code"]):
                self.assertTrue(owner.strip())
                for machine in self.MACHINE_OWNERS:
                    self.assertNotIn(machine, owner)

    def test_every_blocker_says_what_clearing_it_would_unblock(self):
        for blocker in self.status["blockers"]:
            with self.subTest(code=blocker["code"]):
                self.assertGreater(len(blocker["unblocks"]), 20)
                self.assertGreater(len(blocker["meaning"]), 20)
                self.assertGreater(len(blocker["detail"]), 10)

    def test_the_next_actions_are_all_human_acts(self):
        actions = self.status["next_required_human_actions"]
        self.assertTrue(actions)
        for action in actions:
            with self.subTest(action=action[:40]):
                self.assertGreater(len(action), 30)


class TestARealBuildIsRefused(unittest.TestCase):

    def test_attempting_a_real_build_reports_a_refusal_and_creates_nothing(self):
        attempt = build_real_build_attempt(REPO_ROOT)
        payload = attempt if isinstance(attempt, dict) else attempt.to_json()
        self.assertTrue(payload["blockers"])
        for key in ("rules_created", "rulesets_created", "artifacts_written"):
            if key in payload:
                with self.subTest(count=key):
                    self.assertEqual(payload[key], 0)

    def test_the_attempt_wrote_no_artifact_into_the_registry(self):
        registry = FrozenRulesetRegistry(DEFAULT_REGISTRY_ROOT)
        build_real_build_attempt(REPO_ROOT)
        self.assertEqual(registry.list_executable(), ())


class TestThePublishedReportsAreReproducible(unittest.TestCase):

    def test_the_gate_status_file_matches_a_fresh_build(self):
        with io.open(GATE_STATUS_JSON, encoding="utf-8") as handle:
            published = json.load(handle)
        rebuilt = build_gate_status(REPO_ROOT).to_json()
        self.assertEqual(published["content_hash"], rebuilt["content_hash"])
        self.assertEqual(published, rebuilt)

    def test_the_build_attempt_file_matches_a_fresh_build(self):
        with io.open(BUILD_ATTEMPT_JSON, encoding="utf-8") as handle:
            published = json.load(handle)
        attempt = build_real_build_attempt(REPO_ROOT)
        rebuilt = attempt if isinstance(attempt, dict) else attempt.to_json()
        self.assertEqual(published, rebuilt)

    def test_the_gate_status_declares_its_version(self):
        with io.open(GATE_STATUS_JSON, encoding="utf-8") as handle:
            published = json.load(handle)
        self.assertEqual(published["gate_status_version"],
                         GATE_STATUS_VERSION)

    def test_the_note_says_this_is_governance_not_failure(self):
        with io.open(GATE_STATUS_JSON, encoding="utf-8") as handle:
            published = json.load(handle)
        self.assertIn("expected governance result", published["note"])


if __name__ == "__main__":
    unittest.main()
