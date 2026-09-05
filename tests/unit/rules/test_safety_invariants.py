# -*- coding: utf-8 -*-
"""The safety invariants, re-asserted at the rule layer (WP-11).

Each invariant already has tests in the work package that introduced it. These
re-assert them where WP-11 could plausibly break them, because a rule is the
first artifact in this system that is meant to be *executed*, and an invariant
that survived every earlier stage could still be lost here.

* ``SAFETY-INV-001`` missing data is not low risk
* ``SAFETY-INV-003`` unvalidated and deprecated rules do not execute
* ``SAFETY-INV-004`` RAPID is not ULTRARAPID
* ``SAFETY-INV-006`` every finding is traceable to evidence
* ``SAFETY-INV-008`` a source conflict is not reassurance
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from pgx.domain.enums import (AttentionLevel, Phenotype, RuleStatus,
                              RulesetStatus)
from pgx.rules.conditions import RULE_PHENOTYPES
from pgx.rules.conflicts import detect_conflicts
from pgx.rules.models import RULE_OUTCOME_LEVELS
from pgx.rules.registry import FrozenRulesetRegistry
from pgx.rules.schema import rule_document_issues
from tests.fixtures.wp11.synthetic import (frozen_ruleset, synthetic_condition,
                                           synthetic_lifecycle,
                                           synthetic_provenance,
                                           synthetic_rule, synthetic_ruleset)


class TestMissingDataIsNotLowRisk(unittest.TestCase):
    """``SAFETY-INV-001``."""

    def test_no_rule_may_be_keyed_on_indeterminate(self):
        self.assertNotIn(Phenotype.INDETERMINATE, RULE_PHENOTYPES)

    def test_there_is_no_default_outcome_for_an_unmatched_axis(self):
        """A rule covers what it names. Nothing supplies a value for an axis
        no rule covers, which is what lets WP-12 report "not assessed"
        instead of inheriting a reassuring default."""
        condition = synthetic_condition(phenotypes=(Phenotype.POOR,))
        covered = {axis.phenotype for axis in condition.expand()}
        self.assertEqual(covered, {Phenotype.POOR})

    def test_no_active_attention_must_still_be_written_deliberately(self):
        """``NO_ACTIVE_ATTENTION`` is an authorable conclusion, not a
        fallback: it is in the vocabulary precisely so that "we looked and
        found nothing to flag" is distinguishable from "nobody looked"."""
        self.assertIn(AttentionLevel.NO_ACTIVE_ATTENTION, RULE_OUTCOME_LEVELS)
        self.assertNotIn(AttentionLevel.NOT_ASSESSED, RULE_OUTCOME_LEVELS)


class TestUnvalidatedRulesDoNotExecute(unittest.TestCase):
    """``SAFETY-INV-003``."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "rulesets")
        os.makedirs(self.root)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_only_a_validated_rule_is_executable(self):
        definition = synthetic_rule()
        for status in RuleStatus:
            with self.subTest(status=status.value):
                self.assertEqual(
                    synthetic_lifecycle(definition,
                                        status=status).is_executable,
                    status is RuleStatus.VALIDATED)

    def test_only_a_frozen_ruleset_is_executable(self):
        for status in RulesetStatus:
            with self.subTest(status=status.value):
                self.assertEqual(
                    synthetic_ruleset((), status=status).is_executable,
                    status is RulesetStatus.FROZEN)

    def test_the_registry_reaches_nothing_unpublished(self):
        """There is no ruleset directory, so there is nothing to serve - and
        no method that could serve an unpublished one if there were."""
        registry = FrozenRulesetRegistry(self.root)
        self.assertEqual(registry.list_executable(), ())

    def test_a_deprecated_rule_stops_executing(self):
        definition = synthetic_rule()
        record = synthetic_lifecycle(definition,
                                     status=RuleStatus.DEPRECATED)
        self.assertFalse(record.is_executable)


class TestRapidIsNotUltrarapid(unittest.TestCase):
    """``SAFETY-INV-004``."""

    def test_the_two_are_separate_members(self):
        self.assertIn(Phenotype.RAPID, RULE_PHENOTYPES)
        self.assertIn(Phenotype.ULTRARAPID, RULE_PHENOTYPES)
        self.assertIsNot(Phenotype.RAPID, Phenotype.ULTRARAPID)

    def test_neither_expands_into_the_other(self):
        for phenotype, other in ((Phenotype.RAPID, Phenotype.ULTRARAPID),
                                 (Phenotype.ULTRARAPID, Phenotype.RAPID)):
            condition = synthetic_condition(phenotypes=(phenotype,))
            with self.subTest(phenotype=phenotype.value):
                self.assertNotIn(
                    other, {axis.phenotype for axis in condition.expand()})

    def test_they_cannot_be_ordered_relative_to_one_another(self):
        """Ordering would invite "at least as fast as", which is a scientific
        claim the vocabulary does not make."""
        with self.assertRaises(TypeError):
            sorted([Phenotype.RAPID, Phenotype.ULTRARAPID])


class TestEveryRuleIsTraceableToEvidence(unittest.TestCase):
    """``SAFETY-INV-006``."""

    def test_a_rule_with_no_evidence_is_refused(self):
        with self.assertRaises(Exception):
            synthetic_provenance(evidence_record_uuids=())

    def test_a_rule_document_with_no_evidence_is_refused(self):
        document = synthetic_rule().to_json()
        document["provenance"]["evidence_record_uuids"] = []
        self.assertTrue(rule_document_issues(document))

    def test_every_rule_names_the_exact_revision_it_encodes(self):
        provenance = synthetic_rule().provenance
        self.assertTrue(provenance.curation_revision_id)
        self.assertTrue(provenance.curation_revision_hash.startswith(
            "sha256:"))

    def test_a_frozen_artifact_carries_the_evidence_references_with_it(self):
        import io
        import json
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        destination = os.path.join(tmp, "PGX-RULESET-29991231-001")
        frozen_ruleset(destination, count=1)
        with io.open(os.path.join(destination, "rules.ndjson"),
                     encoding="utf-8") as handle:
            for line in handle:
                document = json.loads(line)
                with self.subTest(rule=document["rule_id"]):
                    self.assertTrue(
                        document["provenance"]["evidence_record_uuids"])


class TestASourceConflictIsNotReassurance(unittest.TestCase):
    """``SAFETY-INV-008``."""

    def test_two_rules_disagreeing_produce_a_blocking_finding(self):
        low = synthetic_rule(attention=AttentionLevel.LOW)
        high = synthetic_rule(attention=AttentionLevel.HIGH)
        report = detect_conflicts((low, high))
        self.assertFalse(report.clean)
        self.assertTrue(all(finding.blocking for finding in report.findings))

    def test_nothing_averages_or_downgrades_a_disagreement(self):
        low = synthetic_rule(attention=AttentionLevel.LOW)
        high = synthetic_rule(attention=AttentionLevel.HIGH)
        finding = detect_conflicts((low, high)).findings[0]
        payload = finding.to_json()
        for absent in ("average", "median", "consensus", "merged",
                       "resolution", "downgraded", "compromise", "winner"):
            with self.subTest(field=absent):
                self.assertNotIn(absent, payload)
        # Both levels are reported; neither is presented as the answer.
        self.assertIn("LOW", payload["detail"])
        self.assertIn("HIGH", payload["detail"])
        self.assertIn("nothing here chooses between them", payload["detail"])

    def test_a_conflicted_set_cannot_be_built_into_a_ruleset(self):
        """The conflict is blocking at build time, so a disagreement cannot
        be shipped and reported later."""
        from pgx.rules.builder import build_ruleset
        from tests.fixtures.wp11.synthetic import synthetic_build_inputs
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        low = synthetic_rule(attention=AttentionLevel.LOW)
        high = synthetic_rule(attention=AttentionLevel.HIGH)
        inputs = synthetic_build_inputs(
            (low, high),
            ruleset=synthetic_ruleset((low, high),
                                      status=RulesetStatus.VALIDATED))
        result = build_ruleset(inputs,
                               destination=os.path.join(tmp, "artifact"),
                               built_by="TEST-rule-builder-1")
        self.assertFalse(result.succeeded)
        self.assertFalse(os.path.exists(os.path.join(tmp, "artifact")))


if __name__ == "__main__":
    unittest.main()
