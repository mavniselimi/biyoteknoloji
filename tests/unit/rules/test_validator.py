# -*- coding: utf-8 -*-
"""The five validation layers (WP-11, sections A-E of the issue codes).

Layer A asks whether the document is well formed. Layer B asks whether the
things it names exist. Layer C asks whether this actor may make this
transition now. Layer D asks whether the curated conclusion behind it is one a
rule may encode at all. Layer E asks whether a set of rules can be a ruleset.

The layers are separate because the answers are owned by different people. A
malformed document is the author's problem; a conclusion that is not
SUPPORTED is a curator's; an actor without the role is an identity question
nobody in this repository can answer yet.

``ValidationContext`` is pure: the caller supplies every fact. The validator
therefore cannot reach a database, and cannot decide anything about the real
world by accident.
"""

from __future__ import annotations

import unittest

from pgx.curation.vocabulary import (Applicability, ConclusionState,
                                     ConflictState, CurationRole)
from pgx.domain.enums import CurationStatus, RuleStatus
from pgx.rules.lifecycle import (ELIGIBLE_APPLICABILITY,
                                 ELIGIBLE_CONCLUSION_STATES,
                                 RULE_VALIDATION_ROLES,
                                 ineligible_conclusion_reason)
from pgx.rules.validator import (ISSUE_CODES, SEVERITIES, ValidationContext,
                                 validate_rule, validate_ruleset_members)
from tests.fixtures.wp11.synthetic import (TEST_AUTHOR, TEST_VALIDATOR,
                                           synthetic_condition,
                                           synthetic_context,
                                           synthetic_lifecycle,
                                           synthetic_provenance,
                                           synthetic_rule)


def _report(definition=None, **overrides):
    definition = definition or synthetic_rule()
    return validate_rule(definition, synthetic_context(definition,
                                                       **overrides))


class TestTheIssueCatalogue(unittest.TestCase):

    def test_every_code_declares_a_layer_and_a_meaning(self):
        for code, entry in ISSUE_CODES.items():
            with self.subTest(code=code):
                self.assertIn(entry["layer"], ("A", "B", "C", "D", "E"))
                self.assertGreater(len(entry["meaning"]), 15)

    def test_all_five_layers_are_populated(self):
        layers = {entry["layer"] for entry in ISSUE_CODES.values()}
        self.assertEqual(layers, {"A", "B", "C", "D", "E"})

    def test_the_severities_are_closed(self):
        self.assertEqual(SEVERITIES, ("ERROR", "WARNING", "INFO"))

    def test_no_code_is_declared_twice(self):
        self.assertEqual(len(ISSUE_CODES), len(set(ISSUE_CODES)))


class TestAWellFormedRuleInAWorldThatWouldAcceptIt(unittest.TestCase):

    def test_the_reference_rule_validates(self):
        report = _report()
        self.assertTrue(report.passed, report.codes)

    def test_the_report_hashes_its_own_result(self):
        report = _report()
        self.assertTrue(report.result_hash().startswith("sha256:"))

    def test_two_identical_validations_hash_identically(self):
        definition = synthetic_rule()
        first = validate_rule(definition, synthetic_context(definition))
        second = validate_rule(definition, synthetic_context(definition))
        self.assertEqual(first.result_hash(), second.result_hash())


class TestLayerBReferencesMustExist(unittest.TestCase):

    def test_an_unknown_gene_is_reported(self):
        self.assertIn("RULE_REF_GENE_UNKNOWN",
                      _report(known_gene_keys=frozenset()).codes)

    def test_an_unknown_drug_is_reported(self):
        self.assertIn("RULE_REF_DRUG_UNKNOWN",
                      _report(known_drug_keys=frozenset()).codes)

    def test_an_unknown_dataset_is_reported(self):
        self.assertIn("RULE_REF_DATASET_UNKNOWN",
                      _report(known_dataset_public_ids=frozenset()).codes)

    def test_a_citation_that_does_not_resolve_is_reported(self):
        self.assertIn("RULE_REF_EVIDENCE_MISSING",
                      _report(known_evidence_uuids=frozenset()).codes)

    def test_a_rule_pinning_a_different_evidence_build_is_reported(self):
        """Its citations were resolved against a different set of bytes, so
        "this uuid exists" was answered by a build that is no longer in
        force."""
        self.assertIn(
            "RULE_REF_EVIDENCE_OUT_OF_BUILD",
            _report(evidence_build_content_hash="sha256:" + "e" * 64).codes)

    def test_a_revision_hash_that_does_not_match_is_reported(self):
        self.assertIn(
            "RULE_REF_REVISION_HASH_MISMATCH",
            _report(curation_revision_hash="sha256:" + "0" * 64).codes)

    def test_an_empty_catalogue_reports_everything_as_unknown(self):
        """Fail closed. A caller who supplies no catalogue has not proved the
        entities exist; it has proved nothing, and "nothing is known to
        exist" is not the same as "everything is fine"."""
        codes = _report(known_gene_keys=frozenset(),
                        known_drug_keys=frozenset(),
                        known_dataset_public_ids=frozenset(),
                        known_evidence_uuids=frozenset()).codes
        for expected in ("RULE_REF_GENE_UNKNOWN", "RULE_REF_DRUG_UNKNOWN",
                         "RULE_REF_DATASET_UNKNOWN",
                         "RULE_REF_EVIDENCE_MISSING"):
            with self.subTest(code=expected):
                self.assertIn(expected, codes)

    def test_a_missing_approval_envelope_is_reported(self):
        self.assertIn("RULE_REF_ENVELOPE_MISSING",
                      _report(approval_envelope=None).codes)


class TestLayerCWhoMayActAndWhen(unittest.TestCase):

    def test_only_two_roles_may_validate_a_rule(self):
        self.assertEqual(
            {role.value for role in RULE_VALIDATION_ROLES},
            {"INDEPENDENT_SCIENTIFIC_REVIEWER", "ADJUDICATOR"})

    def test_an_actor_without_a_validation_role_is_reported(self):
        codes = _report(
            actor_roles=frozenset({CurationRole.SCIENTIFIC_CURATOR})).codes
        self.assertIn("RULE_LC_ACTOR_ROLE", codes)

    def test_the_author_validating_their_own_rule_is_reported(self):
        definition = synthetic_rule()
        report = validate_rule(
            definition,
            synthetic_context(definition, actor_id=definition.created_by))
        self.assertIn("RULE_LC_SEPARATION", report.codes)

    def test_an_interpretation_that_is_not_curated_is_reported(self):
        codes = _report(interpretation_status=CurationStatus.RAW).codes
        self.assertIn("RULE_LC_CURATION_NOT_CURATED", codes)

    def test_an_illegal_transition_is_reported(self):
        definition = synthetic_rule()
        report = validate_rule(
            definition, synthetic_context(definition),
            target_status=RuleStatus.VALIDATED,
            lifecycle=synthetic_lifecycle(definition,
                                          status=RuleStatus.DEPRECATED))
        self.assertIn("RULE_LC_ILLEGAL_TRANSITION", report.codes)


class TestLayerDWhichConclusionsMayBecomeRules(unittest.TestCase):

    def test_only_a_supported_conclusion_is_eligible(self):
        self.assertEqual({state.value for state in ELIGIBLE_CONCLUSION_STATES},
                         {"SUPPORTED"})

    def test_only_an_applicable_interpretation_is_eligible(self):
        self.assertEqual({value.value for value in ELIGIBLE_APPLICABILITY},
                         {"APPLICABLE"})

    def test_every_conclusion_other_than_supported_is_reported(self):
        """SUPPORTED is the only state a rule may encode. The others each
        mean something a rule cannot say: the evidence conflicts, it is
        insufficient, it is not interpretable, it is out of scope, or it does
        not apply."""
        for state in ConclusionState:
            if state in ELIGIBLE_CONCLUSION_STATES:
                continue
            with self.subTest(state=state.value):
                self.assertIn("RULE_ELIG_CONCLUSION_STATE",
                              _report(conclusion_state=state).codes)

    def test_an_interpretation_that_does_not_apply_is_reported(self):
        for value in Applicability:
            if value in ELIGIBLE_APPLICABILITY:
                continue
            with self.subTest(applicability=value.value):
                self.assertIn("RULE_ELIG_APPLICABILITY",
                              _report(applicability=value).codes)

    def test_an_unresolved_conflict_is_reported(self):
        codes = _report(conflict_state=ConflictState.UNRESOLVED,
                        conflict_material=True).codes
        self.assertIn("RULE_ELIG_CONFLICT_OPEN", codes)

    def test_a_quarantined_evidence_build_is_reported(self):
        codes = _report(evidence_build_approved_for_rules=False).codes
        self.assertIn("RULE_ELIG_EVIDENCE_NOT_APPROVED", codes)

    def test_a_source_policy_that_does_not_permit_rules_is_reported(self):
        codes = _report(source_policy_permits_rules=False).codes
        self.assertIn("RULE_ELIG_SOURCE_POLICY", codes)

    def test_a_protocol_mismatch_is_reported(self):
        codes = _report(protocol_version="some-other-protocol/1").codes
        self.assertIn("RULE_ELIG_PROTOCOL_MISMATCH", codes)

    def test_every_ineligible_conclusion_explains_itself(self):
        """Reasons, plural: a conclusion can be ineligible for more than one
        thing at once, and reporting only the first would send an author
        round the loop once per problem."""
        for state in ConclusionState:
            reasons = ineligible_conclusion_reason(
                state, Applicability.APPLICABLE, ConflictState.NONE_IDENTIFIED)
            with self.subTest(state=state.value):
                if state in ELIGIBLE_CONCLUSION_STATES:
                    self.assertEqual(reasons, ())
                else:
                    self.assertTrue(reasons)
                    for reason in reasons:
                        self.assertGreater(len(reason), 20)

    def test_several_problems_at_once_produce_several_reasons(self):
        reasons = ineligible_conclusion_reason(
            ConclusionState.INSUFFICIENT, Applicability.NOT_APPLICABLE,
            ConflictState.UNRESOLVED, conflict_material=True)
        self.assertGreaterEqual(len(reasons), 3)


class TestLayerEWhatMayBeARuleset(unittest.TestCase):

    def test_an_empty_set_is_reported(self):
        report = validate_ruleset_members((), {})
        self.assertIn("RULESET_EMPTY", report.codes)

    def test_a_member_that_is_not_validated_is_reported(self):
        definition = synthetic_rule()
        report = validate_ruleset_members(
            (definition,),
            {definition.rule_id.to_json():
                synthetic_lifecycle(definition, status=RuleStatus.CURATED,
                                    version=1)})
        self.assertIn("RULESET_MEMBER_NOT_VALIDATED", report.codes)

    def test_a_deprecated_member_is_reported(self):
        definition = synthetic_rule()
        report = validate_ruleset_members(
            (definition,),
            {definition.rule_id.to_json():
                synthetic_lifecycle(definition,
                                    status=RuleStatus.DEPRECATED, version=3)})
        self.assertIn("RULESET_MEMBER_DEPRECATED", report.codes)

    def test_a_member_whose_content_moved_since_pinning_is_reported(self):
        definition = synthetic_rule()
        report = validate_ruleset_members(
            (definition,),
            {definition.rule_id.to_json(): synthetic_lifecycle(definition)},
            pinned_hashes={definition.rule_id.to_json():
                           "sha256:" + "0" * 64})
        self.assertIn("RULESET_MEMBER_HASH_MISMATCH", report.codes)

    def test_a_duplicated_member_is_reported(self):
        definition = synthetic_rule()
        report = validate_ruleset_members(
            (definition, definition),
            {definition.rule_id.to_json(): synthetic_lifecycle(definition)})
        self.assertIn("RULESET_MEMBER_DUPLICATE", report.codes)

    def test_members_from_different_builds_are_reported(self):
        first = synthetic_rule()
        second = synthetic_rule(
            condition=synthetic_condition(gene="GENE:TESTGENE2"),
            provenance=synthetic_provenance(
                evidence_build_content_hash="sha256:" + "9" * 64))
        report = validate_ruleset_members(
            (first, second),
            {first.rule_id.to_json(): synthetic_lifecycle(first),
             second.rule_id.to_json(): synthetic_lifecycle(second)})
        self.assertIn("RULESET_BOUNDARY_INCOMPATIBLE", report.codes)

    def test_a_conflicting_pair_is_reported(self):
        from pgx.domain.enums import AttentionLevel
        first = synthetic_rule(attention=AttentionLevel.LOW)
        second = synthetic_rule(attention=AttentionLevel.HIGH)
        report = validate_ruleset_members(
            (first, second),
            {first.rule_id.to_json(): synthetic_lifecycle(first),
             second.rule_id.to_json(): synthetic_lifecycle(second)})
        self.assertIn("RULESET_CONFLICT_UNRESOLVED", report.codes)


class TestTheValidatorIsPure(unittest.TestCase):
    """Every fact comes from the context. That is what makes it testable, and
    what stops it deciding something about the real world by reaching for
    it."""

    def test_the_context_is_a_frozen_value(self):
        definition = synthetic_rule()
        context = synthetic_context(definition)
        with self.assertRaises(Exception):
            context.interpretation_status = CurationStatus.CURATED

    def test_the_validator_module_opens_no_file_and_no_connection(self):
        import os
        from tests.unit.rules._support import RULES_DIR, imports_of
        imported = imports_of(os.path.join(RULES_DIR, "validator.py"))
        for forbidden in ("io", "os", "pathlib", "sqlalchemy", "requests",
                          "socket"):
            with self.subTest(module=forbidden):
                self.assertNotIn(forbidden, imported)

    def test_every_issue_is_reported_not_only_the_first(self):
        report = _report(known_gene_keys=frozenset(),
                         known_drug_keys=frozenset(),
                         conclusion_state=ConclusionState.INSUFFICIENT,
                         evidence_build_approved_for_rules=False)
        self.assertGreaterEqual(len(report.codes), 4)

    def test_issues_are_sorted_deterministically(self):
        report = _report(known_gene_keys=frozenset(),
                         known_drug_keys=frozenset())
        self.assertEqual(list(report.issues),
                         sorted(report.issues, key=lambda item: item.sort_key()))


if __name__ == "__main__":
    unittest.main()
