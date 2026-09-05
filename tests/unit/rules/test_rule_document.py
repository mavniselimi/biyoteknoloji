# -*- coding: utf-8 -*-
"""The rule document: what it must carry, and what it may not (WP-11, A).

A rule document is the smallest complete statement this system will execute.
Every required field is required because a document missing it would still
look like a rule while being unable to answer a question somebody will
eventually ask: which curated revision said this, which evidence supports it,
which approval covers this exact version.

The outcome tests are the sharpest ones here. A rule may say how much
attention a gene/drug pairing warrants and nothing else - not a dose, not a
drug choice, not a safety claim, not a score. Those are refused by field name
rather than by inspection, because a check that tried to recognise a
recommendation by reading it would eventually fail to recognise one.
"""

from __future__ import annotations

import copy
import datetime as _dt
import unittest

from pgx.domain.enums import AttentionLevel
from pgx.domain.errors import DomainInvariantError
from pgx.rules.errors import RuleValidationError
from pgx.rules.models import (RULE_OUTCOME_LEVELS, RULE_SCHEMA_VERSION,
                              ComputableRuleDefinition, RuleOutcome,
                              RuleProvenance)
from pgx.rules.schema import (PROVENANCE_FIELDS, RULE_FIELDS,
                              parse_rule_document, rule_document_issues)
from tests.fixtures.wp11.synthetic import (MOMENT, synthetic_provenance,
                                           synthetic_rule)


def _document():
    return copy.deepcopy(synthetic_rule().to_json())


class TestEveryRequiredFieldIsRequired(unittest.TestCase):

    def test_the_reference_document_has_no_issues(self):
        self.assertEqual(rule_document_issues(_document()), ())

    def test_each_required_rule_field_says_why_it_is_required(self):
        for field, reason in RULE_FIELDS.items():
            with self.subTest(field=field):
                self.assertGreater(len(reason), 20,
                                   "a required field with no stated reason is "
                                   "a field nobody can safely remove")

    def test_each_provenance_field_says_why_it_is_required(self):
        for field, reason in PROVENANCE_FIELDS.items():
            with self.subTest(field=field):
                self.assertGreater(len(reason), 20)

    def test_removing_any_required_field_is_an_error(self):
        for field in RULE_FIELDS:
            with self.subTest(field=field):
                payload = _document()
                payload.pop(field)
                codes = {issue["code"] for issue in
                         rule_document_issues(payload)}
                self.assertIn("RULE_DOC_MISSING_FIELD", codes)

    def test_removing_any_provenance_field_is_an_error(self):
        for field in PROVENANCE_FIELDS:
            with self.subTest(field=field):
                payload = _document()
                payload["provenance"].pop(field)
                self.assertNotEqual(rule_document_issues(payload), ())

    def test_an_unknown_field_is_an_error(self):
        payload = _document()
        payload["priority"] = 1
        codes = {issue["code"] for issue in rule_document_issues(payload)}
        self.assertIn("RULE_DOC_UNKNOWN_FIELD", codes)

    def test_a_rule_with_no_evidence_is_an_error(self):
        """``SAFETY-INV-006``: a finding must be traceable to evidence, so a
        rule that could produce one must name some."""
        payload = _document()
        payload["provenance"]["evidence_record_uuids"] = []
        self.assertNotEqual(rule_document_issues(payload), ())

    def test_a_rule_repeating_an_evidence_record_is_an_error(self):
        payload = _document()
        uuid_value = payload["provenance"]["evidence_record_uuids"][0]
        payload["provenance"]["evidence_record_uuids"] = [uuid_value,
                                                          uuid_value]
        codes = {issue["code"] for issue in rule_document_issues(payload)}
        self.assertIn("RULE_DOC_EVIDENCE_DUPLICATE", codes)

    def test_a_rule_of_another_schema_version_is_an_error(self):
        payload = _document()
        payload["rule_schema_version"] = "pgx-computable-rule/2"
        codes = {issue["code"] for issue in rule_document_issues(payload)}
        self.assertIn("RULE_DOC_SCHEMA_VERSION", codes)

    def test_every_issue_is_reported_not_only_the_first(self):
        payload = _document()
        payload.pop("created_by")
        payload.pop("rule_version")
        payload["provenance"].pop("protocol_version")
        self.assertGreaterEqual(len(rule_document_issues(payload)), 3)


class TestTheOutcomeVocabularyIsClosed(unittest.TestCase):

    def test_only_four_levels_are_authorable(self):
        self.assertEqual(
            tuple(level.value for level in RULE_OUTCOME_LEVELS),
            ("NO_ACTIVE_ATTENTION", "LOW", "MEDIUM", "HIGH"))

    def test_not_assessed_is_not_authorable(self):
        """It is what an engine reports when nothing matched. A rule
        asserting it would be a rule claiming an absence of assessment."""
        self.assertNotIn(AttentionLevel.NOT_ASSESSED, RULE_OUTCOME_LEVELS)
        with self.assertRaises(DomainInvariantError):
            RuleOutcome(attention_level=AttentionLevel.NOT_ASSESSED,
                        rationale_reference="TEST-WI-1/TEST-REV-1")

    def test_an_outcome_needs_a_rationale_reference(self):
        with self.assertRaises(DomainInvariantError):
            RuleOutcome(attention_level=AttentionLevel.LOW,
                        rationale_reference="")


class TestTheOutcomeCarriesNoClinicalInstruction(unittest.TestCase):
    """Each of these is one of the things this system must never produce. The
    refusal is by field name, checked over the whole prohibited set, so adding
    a synonym to the model is what it takes to weaken this - not a rewording.
    """

    PROHIBITED = ("dose", "dosage", "dose_adjustment", "recommendation",
                  "recommended_action", "alternative", "alternative_drug",
                  "replacement", "treatment", "safe", "is_safe", "safety",
                  "risk_score", "score", "rank", "priority", "instruction",
                  "diagnosis")

    def test_a_document_carrying_any_prohibited_outcome_field_is_refused(self):
        for field in self.PROHIBITED:
            with self.subTest(field=field):
                payload = _document()
                payload["outcome"][field] = "anything at all"
                codes = {issue["code"] for issue in
                         rule_document_issues(payload)}
                self.assertIn("RULE_DOC_OUTCOME_INVALID", codes)

    def test_the_model_refuses_them_too(self):
        for field in self.PROHIBITED:
            with self.subTest(field=field):
                with self.assertRaises(TypeError):
                    RuleOutcome(attention_level=AttentionLevel.LOW,
                                rationale_reference="TEST-WI-1/TEST-REV-1",
                                **{field: "anything at all"})

    def test_the_rule_type_defines_no_field_that_could_hold_one(self):
        fields = set(ComputableRuleDefinition.__dataclass_fields__)
        for field in self.PROHIBITED:
            with self.subTest(field=field):
                self.assertNotIn(field, fields)


class TestTheContentHashIsSemantic(unittest.TestCase):

    def test_two_identical_rules_hash_identically(self):
        first = synthetic_rule()
        second = ComputableRuleDefinition(
            rule_id=first.rule_id, family_id=first.family_id,
            rule_version=first.rule_version, condition=first.condition,
            outcome=first.outcome, provenance=first.provenance,
            created_by=first.created_by, created_at=first.created_at,
            supersedes_rule_id=first.supersedes_rule_id,
            metadata=dict(first.metadata))
        self.assertEqual(first.content_hash(), second.content_hash())

    def test_metadata_does_not_change_the_hash(self):
        """Metadata is annotation. If a comment could change a rule's
        identity, an approval could be invalidated by an editorial note."""
        first = synthetic_rule()
        second = ComputableRuleDefinition(
            rule_id=first.rule_id, family_id=first.family_id,
            rule_version=first.rule_version, condition=first.condition,
            outcome=first.outcome, provenance=first.provenance,
            created_by=first.created_by, created_at=first.created_at,
            supersedes_rule_id=first.supersedes_rule_id,
            metadata={"note": "an editorial remark"})
        self.assertEqual(first.content_hash(), second.content_hash())

    def test_changing_the_condition_changes_the_hash(self):
        from pgx.domain.enums import Phenotype
        from tests.fixtures.wp11.synthetic import synthetic_condition
        first = synthetic_rule()
        second = synthetic_rule(
            condition=synthetic_condition(phenotypes=(Phenotype.RAPID,)))
        self.assertNotEqual(first.content_hash(), second.content_hash())

    def test_changing_the_outcome_changes_the_hash(self):
        first = synthetic_rule(attention=AttentionLevel.LOW)
        second = synthetic_rule(rule_id=first.rule_id,
                                family_id=first.family_id,
                                attention=AttentionLevel.HIGH)
        self.assertNotEqual(first.content_hash(), second.content_hash())

    def test_the_envelope_hash_is_outside_the_semantic_content(self):
        """The envelope names the rule's content hash and the rule names the
        envelope's. Excluding one direction is what makes the pair computable
        at all; the binding stays mutual because the envelope still pins the
        content."""
        definition = synthetic_rule()
        self.assertNotIn("approval_envelope_hash",
                         definition.semantic_content()["provenance"])
        self.assertIn("approval_envelope_hash",
                      definition.to_json()["provenance"])

    def test_a_document_declaring_the_wrong_hash_is_refused(self):
        """The structural checks and the hash check are separate on purpose:
        ``rule_document_issues`` reports on a document it has not built, and
        the declared hash can only be compared once one has been. So this is
        raised at parse, carrying the same issue code the report would use."""
        payload = _document()
        payload["content_hash"] = "sha256:" + "0" * 64
        self.assertEqual(rule_document_issues(payload), ())
        with self.assertRaises(RuleValidationError) as caught:
            parse_rule_document(payload)
        self.assertIn("RULE_DOC_HASH_MISMATCH",
                      {issue["code"] for issue in caught.exception.issues})

    def test_parsing_refuses_a_mismatched_hash_rather_than_recomputing(self):
        """Silently re-hashing would turn a tampered file into a valid one."""
        payload = _document()
        payload["outcome"]["attention_level"] = "HIGH"
        with self.assertRaises(RuleValidationError):
            parse_rule_document(payload)

    def test_a_document_round_trips(self):
        definition = synthetic_rule()
        parsed = parse_rule_document(definition.to_json())
        self.assertEqual(parsed.to_json(), definition.to_json())
        self.assertEqual(parsed.content_hash(), definition.content_hash())


class TestTimestampsAreExplicitInstants(unittest.TestCase):

    def test_a_naive_timestamp_is_refused(self):
        payload = _document()
        payload["created_at"] = "2099-01-01T12:00:00"
        codes = {issue["code"] for issue in rule_document_issues(payload)}
        self.assertTrue({"RULE_DOC_TIMESTAMP_NAIVE",
                         "RULE_DOC_TIMESTAMP_INVALID"} & codes)

    def test_the_model_refuses_a_naive_instant(self):
        with self.assertRaises(Exception):
            ComputableRuleDefinition(
                rule_id=synthetic_rule().rule_id,
                family_id=synthetic_rule().family_id,
                rule_version=1,
                condition=synthetic_rule().condition,
                outcome=synthetic_rule().outcome,
                provenance=synthetic_provenance(),
                created_by="TEST-rule-author-1",
                created_at=_dt.datetime(2099, 1, 1, 12, 0))


class TestProvenanceIsPinnedTwice(unittest.TestCase):
    """Identity alone lets the upstream document change underneath the rule;
    a hash alone does not say which document to look for."""

    PAIRS = (("curation_revision_id", "curation_revision_hash"),
             ("protocol_version", "protocol_content_hash"),
             ("canonical_build_key", "canonical_build_content_hash"),
             ("evidence_build_key", "evidence_build_content_hash"),
             ("source_policy_version", "source_policy_content_hash"))

    def test_every_upstream_pin_names_both_an_identity_and_a_hash(self):
        for identity, digest in self.PAIRS:
            with self.subTest(pin=identity):
                self.assertIn(identity, PROVENANCE_FIELDS)
                self.assertIn(digest, PROVENANCE_FIELDS)

    def test_a_non_digest_where_a_digest_belongs_is_refused(self):
        for _identity, digest in self.PAIRS:
            with self.subTest(field=digest):
                with self.assertRaises(DomainInvariantError):
                    synthetic_provenance(**{digest: "not-a-digest"})

    def test_provenance_is_immutable(self):
        provenance = synthetic_provenance()
        with self.assertRaises(Exception):
            provenance.protocol_version = "something else"


class TestARuleIsImmutableOnceBuilt(unittest.TestCase):

    def test_fields_cannot_be_reassigned(self):
        definition = synthetic_rule()
        for field in ("rule_version", "condition", "outcome", "created_by"):
            with self.subTest(field=field):
                with self.assertRaises(Exception):
                    setattr(definition, field, None)

    def test_the_metadata_view_cannot_be_mutated(self):
        definition = synthetic_rule()
        with self.assertRaises(Exception):
            definition.metadata["synthetic"] = False

    def test_the_schema_version_is_pinned(self):
        self.assertEqual(synthetic_rule().rule_schema_version,
                         RULE_SCHEMA_VERSION)
        self.assertEqual(synthetic_rule().created_at, MOMENT)


if __name__ == "__main__":
    unittest.main()
