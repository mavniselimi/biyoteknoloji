# -*- coding: utf-8 -*-
"""Duplicates, overlaps and conflicts (WP-11, section D).

Detection only. WP-11 reports that two rules disagree; it does not decide
which of them wins. There is no priority field, no rule ordering, no
"most severe wins" and no automatic resolution anywhere in this layer, and
several tests below exist to keep it that way. A conflict between two
scientific statements is a question for the people who wrote them, and a
system that silently picked one would be concealing the disagreement rather
than surfacing it (``SAFETY-INV-008``).

Every finding is blocking. That is a deliberate refusal to grade: a
"warning-level" conflict would be a conflict somebody could ship past.
"""

from __future__ import annotations

import unittest

from pgx.domain.enums import AttentionLevel, Phenotype
from pgx.rules.conflicts import (BLOCKING_CONFLICT_KINDS, CONFLICT_KINDS,
                                 detect_conflicts)
from tests.fixtures.wp11.synthetic import (synthetic_condition,
                                           synthetic_provenance,
                                           synthetic_rule)


def _kinds(*definitions):
    return {finding.kind for finding in detect_conflicts(definitions).findings}


class TestTheConflictVocabularyIsClosedAndBlocking(unittest.TestCase):

    def test_the_eight_kinds(self):
        self.assertEqual(sorted(CONFLICT_KINDS), [
            "CONFLICTING_OUTCOME", "DATASET_BOUNDARY_CONFLICT",
            "EXACT_DUPLICATE", "IDENTITY_COLLISION",
            "PROTOCOL_BOUNDARY_CONFLICT", "REDUNDANT_OVERLAP",
            "SUPERSEDED_MEMBER_PRESENT", "VERSION_LINEAGE_ERROR"])

    def test_every_kind_is_blocking(self):
        self.assertEqual(sorted(BLOCKING_CONFLICT_KINDS),
                         sorted(CONFLICT_KINDS))

    def test_every_kind_says_what_it_means(self):
        for kind, entry in CONFLICT_KINDS.items():
            with self.subTest(kind=kind):
                self.assertGreater(len(entry["meaning"]), 40)


class TestWhatIsDetected(unittest.TestCase):

    def test_a_clean_set_reports_nothing(self):
        first = synthetic_rule()
        second = synthetic_rule(
            condition=synthetic_condition(gene="GENE:TESTGENE2"))
        report = detect_conflicts((first, second))
        self.assertTrue(report.clean)
        self.assertEqual(report.findings, ())

    def test_an_exact_duplicate_is_detected(self):
        """The same claim, under the same provenance and the same approval,
        admitted twice under two identities. Built directly rather than
        through the fixture, because the fixture re-derives an envelope per
        rule and the case being modelled is a row that was copied."""
        from pgx.rules.identifiers import RuleFamilyId
        from pgx.domain.identifiers import ComputableRuleId
        from pgx.rules.models import ComputableRuleDefinition
        first = synthetic_rule()
        second = ComputableRuleDefinition(
            rule_id=ComputableRuleId.new(), family_id=RuleFamilyId.new(),
            rule_version=1, condition=first.condition, outcome=first.outcome,
            provenance=first.provenance, created_by=first.created_by,
            created_at=first.created_at, metadata=dict(first.metadata))
        self.assertIn("EXACT_DUPLICATE", _kinds(first, second))

    def test_two_rules_disagreeing_on_one_axis_are_detected(self):
        first = synthetic_rule(attention=AttentionLevel.LOW)
        second = synthetic_rule(attention=AttentionLevel.HIGH)
        self.assertIn("CONFLICTING_OUTCOME", _kinds(first, second))

    def test_an_overlap_agreeing_on_the_outcome_is_still_reported(self):
        """Agreement is not the same as intent. Two different rules covering
        one axis means the set answers the same question twice, and which
        answer a reader sees depends on which rule they happen to read."""
        first = synthetic_rule(attention=AttentionLevel.MEDIUM)
        second = synthetic_rule(
            attention=AttentionLevel.MEDIUM,
            condition=synthetic_condition(
                operator="ONE_OF",
                phenotypes=(Phenotype.POOR, Phenotype.INTERMEDIATE)))
        self.assertIn("REDUNDANT_OVERLAP", _kinds(first, second))

    def test_one_identity_with_two_contents_is_detected(self):
        first = synthetic_rule()
        second = synthetic_rule(rule_id=first.rule_id,
                                attention=AttentionLevel.HIGH)
        self.assertIn("IDENTITY_COLLISION", _kinds(first, second))

    def test_a_rule_and_its_replacement_together_are_detected(self):
        first = synthetic_rule()
        second = synthetic_rule(family_id=first.family_id, rule_version=2,
                                supersedes=first.rule_id,
                                attention=AttentionLevel.HIGH)
        self.assertIn("SUPERSEDED_MEMBER_PRESENT", _kinds(first, second))

    def test_a_later_version_naming_no_predecessor_cannot_be_built(self):
        """The lineage invariant is enforced where the rule is constructed,
        which is earlier than conflict detection and therefore better: an
        unreconstructible lineage never reaches a ruleset to be detected in."""
        from pgx.domain.errors import DomainInvariantError
        first = synthetic_rule()
        with self.assertRaises(DomainInvariantError):
            synthetic_rule(family_id=first.family_id, rule_version=2)

    def test_a_rule_cannot_supersede_itself(self):
        from pgx.domain.errors import DomainInvariantError
        from pgx.domain.identifiers import ComputableRuleId
        rule_id = ComputableRuleId.new()
        with self.assertRaises(DomainInvariantError):
            synthetic_rule(rule_id=rule_id, rule_version=2,
                           supersedes=rule_id)

    def test_version_one_may_not_claim_a_predecessor(self):
        from pgx.domain.errors import DomainInvariantError
        first = synthetic_rule()
        with self.assertRaises(DomainInvariantError):
            synthetic_rule(rule_version=1, supersedes=first.rule_id)

    def test_a_repeated_version_within_one_family_is_detected(self):
        first = synthetic_rule()
        second = synthetic_rule(family_id=first.family_id, rule_version=1,
                                attention=AttentionLevel.HIGH)
        self.assertIn("VERSION_LINEAGE_ERROR", _kinds(first, second))

    def test_members_pinning_different_builds_are_detected(self):
        first = synthetic_rule()
        second = synthetic_rule(
            condition=synthetic_condition(gene="GENE:TESTGENE2"),
            provenance=synthetic_provenance(
                evidence_build_content_hash="sha256:" + "9" * 64))
        self.assertIn("DATASET_BOUNDARY_CONFLICT", _kinds(first, second))

    def test_members_curated_under_different_protocols_are_detected(self):
        first = synthetic_rule()
        second = synthetic_rule(
            condition=synthetic_condition(gene="GENE:TESTGENE2"),
            provenance=synthetic_provenance(
                protocol_version="test-protocol/8.8.8-synthetic"))
        self.assertIn("PROTOCOL_BOUNDARY_CONFLICT", _kinds(first, second))


class TestDetectionDoesNotResolve(unittest.TestCase):
    """The whole point of this section. Reporting a disagreement is a
    service; picking a winner is a scientific judgement."""

    def test_a_finding_carries_no_winner_no_priority_and_no_severity_order(self):
        first = synthetic_rule(attention=AttentionLevel.LOW)
        second = synthetic_rule(attention=AttentionLevel.HIGH)
        finding = detect_conflicts((first, second)).findings[0]
        payload = finding.to_json()
        for absent in ("winner", "resolution", "resolved", "priority",
                       "precedence", "order", "rank", "severity", "wins",
                       "chosen", "selected", "override"):
            with self.subTest(field=absent):
                self.assertNotIn(absent, payload)

    def test_a_finding_names_every_rule_involved_not_a_survivor(self):
        first = synthetic_rule(attention=AttentionLevel.LOW)
        second = synthetic_rule(attention=AttentionLevel.HIGH)
        finding = detect_conflicts((first, second)).findings[0]
        self.assertEqual(set(finding.rule_ids),
                         {first.rule_id.to_json(), second.rule_id.to_json()})

    def test_the_higher_attention_level_does_not_win(self):
        """"Most severe wins" is a resolution policy nobody approved. Both
        orders produce the same finding, and neither drops a rule."""
        low = synthetic_rule(attention=AttentionLevel.LOW)
        high = synthetic_rule(attention=AttentionLevel.HIGH)
        forward = detect_conflicts((low, high))
        backward = detect_conflicts((high, low))
        self.assertEqual(forward.to_json(), backward.to_json())
        self.assertFalse(forward.clean)

    def test_the_module_defines_no_resolution_helper(self):
        import pgx.rules.conflicts as module
        for name in dir(module):
            with self.subTest(name=name):
                lowered = name.lower()
                self.assertFalse(lowered.startswith("resolve"))
                self.assertNotIn("winner", lowered)
                self.assertNotIn("precedence", lowered)


class TestReportsAreDeterministic(unittest.TestCase):

    def test_input_order_does_not_change_the_report(self):
        rules = (synthetic_rule(attention=AttentionLevel.LOW),
                 synthetic_rule(attention=AttentionLevel.HIGH),
                 synthetic_rule(
                     condition=synthetic_condition(gene="GENE:TESTGENE2")))
        forward = detect_conflicts(rules).to_json()
        backward = detect_conflicts(tuple(reversed(rules))).to_json()
        self.assertEqual(forward, backward)

    def test_findings_are_sorted(self):
        rules = (synthetic_rule(attention=AttentionLevel.LOW),
                 synthetic_rule(attention=AttentionLevel.HIGH))
        findings = detect_conflicts(rules).findings
        self.assertEqual(list(findings),
                         sorted(findings, key=lambda item: item.sort_key()))

    def test_a_single_rule_conflicts_with_nothing(self):
        self.assertTrue(detect_conflicts((synthetic_rule(),)).clean)

    def test_an_empty_set_conflicts_with_nothing(self):
        self.assertTrue(detect_conflicts(()).clean)


if __name__ == "__main__":
    unittest.main()
