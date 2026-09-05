# -*- coding: utf-8 -*-
"""Disagreement and absence, and the two ways they get quietly softened (WP-09).

Both failures are the same shape: a reader takes "we could not settle this" or
"we did not establish this" as "there is nothing here". ``SAFETY-INV-001`` and
``SAFETY-INV-008`` exist because that reading is the highest-consequence error
a pharmacogenomic tool can make.
"""

from __future__ import annotations

import ast
import os
import unittest

from pgx.curation.errors import CurationError
from pgx.curation.models import (ConflictAnalysis, InsufficiencyStatement,
                                 find_reassuring_language)
from pgx.curation.vocabulary import (REASSURING_TERMS, ConclusionState,
                                     ConflictState, EvidenceRelationship,
                                     ExclusionReason, InterpretationStatus)

from tests.unit.curation._support import (REPO_ROOT, insufficiency,
                                          no_conflict, rationale, record,
                                          selection, source_text,
                                          unresolved_conflict)


class TestContradictoryEvidenceIsRetained(unittest.TestCase):

    def test_contradicting_evidence_stays_in_the_record(self):
        item = record(
            conclusion_state=ConclusionState.CONFLICTING,
            evidence=(selection("uuid-1"),
                      selection("uuid-2", EvidenceRelationship.CONTRADICTS,
                                rationale="Describes the opposite direction "
                                          "of effect for the same scope.")),
            conflict=unresolved_conflict())
        uuids = [entry.evidence_record_uuid for entry in item.evidence]
        self.assertIn("uuid-2", uuids)

    def test_contradiction_with_no_conflict_recorded_is_refused(self):
        """The one shape that would let a disagreement vanish quietly."""
        with self.assertRaises(CurationError) as caught:
            record(evidence=(
                selection("uuid-1"),
                selection("uuid-2", EvidenceRelationship.CONTRADICTS,
                          rationale="Reports the opposite direction for the "
                                    "same phenotype scope.")),
                conflict=no_conflict())
        self.assertIn("NONE_IDENTIFIED", str(caught.exception))

    def test_contradictory_evidence_may_not_be_excluded_for_contradicting(self):
        """There is no exclusion reason for 'it disagreed', and the field
        dictionary says the category may not be applied by rule."""
        for member in ExclusionReason:
            with self.subTest(member=member):
                self.assertNotIn("CONTRADICT", member.value)
        from pgx.curation.fields import field_definition
        prohibited = " ".join(field_definition("evidence[].exclusion_reason")
                              .prohibited_interpretations).lower()
        self.assertIn("contradictory", prohibited)
        self.assertIn("older", prohibited)
        self.assertIn("unknown-version", prohibited)


class TestNoSourcePrecedence(unittest.TestCase):
    """WP-05 took this position for source conflicts; this is the same
    position one stage later."""

    def test_the_conflict_model_has_no_winner_field(self):
        fields = set(ConflictAnalysis.__dataclass_fields__)
        for forbidden in ("winner", "prevailing_source", "preferred_source",
                          "precedence", "rank", "authority"):
            self.assertNotIn(forbidden, fields)

    def test_no_curation_module_names_a_precedence_rule(self):
        """Read from identifiers, not prose: every module explains in its
        docstring that it has no precedence, and a substring search would
        match the explanation."""
        directory = os.path.join(REPO_ROOT, "pgx", "curation")
        forbidden = ("PRECEDENCE", "SOURCE_PRIORITY", "SOURCE_RANK",
                     "prefer_source", "outranks", "supersedes_source")
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".py"):
                continue
            tree = ast.parse(source_text(os.path.join("pgx", "curation", name)))
            names = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    names.add(node.id)
                elif isinstance(node, ast.Attribute):
                    names.add(node.attr)
                elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    names.add(node.name)
            for token in forbidden:
                with self.subTest(module=name, token=token):
                    self.assertNotIn(token, names)

    def test_no_guideline_body_is_named_in_a_decision_position(self):
        """A precedence rule hidden as a constant would have to name one."""
        directory = os.path.join(REPO_ROOT, "pgx", "curation")
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".py"):
                continue
            tree = ast.parse(source_text(os.path.join("pgx", "curation", name)))
            for node in ast.walk(tree):
                if isinstance(node, ast.Compare):
                    rendered = ast.dump(node)
                    for body in ("CPIC", "DPWG", "cpic.publications",
                                 "dpwg.knmp"):
                        with self.subTest(module=name, body=body):
                            self.assertNotIn("'%s'" % body, rendered)


class TestUnresolvedConflictBlocksRules(unittest.TestCase):

    def test_an_unresolved_material_conflict_blocks_rule_construction(self):
        self.assertTrue(unresolved_conflict().blocks_rule_construction)

    def test_adjudication_required_blocks_too(self):
        analysis = ConflictAnalysis(
            state=ConflictState.ADJUDICATION_REQUIRED,
            conflicting_evidence_uuids=("uuid-1", "uuid-2"),
            disputed_field="effect direction", material=True,
            curator_analysis="Two annotations disagree and neither is "
                             "superseded; a named adjudicator is required.")
        self.assertTrue(analysis.blocks_rule_construction)

    def test_a_present_immaterial_conflict_does_not_block(self):
        analysis = ConflictAnalysis(
            state=ConflictState.PRESENT,
            conflicting_evidence_uuids=("uuid-1", "uuid-2"),
            disputed_field="wording of the mechanism description",
            material=False,
            curator_analysis="The two records describe the same mechanism in "
                             "different words; the difference is editorial.")
        self.assertFalse(analysis.blocks_rule_construction)

    def test_a_blocking_conflict_cannot_back_a_supported_conclusion(self):
        with self.assertRaises(CurationError) as caught:
            record(conclusion_state=ConclusionState.SUPPORTED,
                   evidence=(selection("uuid-1"), selection("uuid-2")),
                   conflict=unresolved_conflict())
        self.assertIn("adjudicator", str(caught.exception))

    def test_a_record_with_a_blocking_conflict_is_not_rule_eligible(self):
        item = record(conclusion_state=ConclusionState.CONFLICTING,
                      evidence=(selection("uuid-1"), selection("uuid-2")),
                      conflict=unresolved_conflict())
        self.assertFalse(item.is_rule_eligible)

    def test_a_conflict_naming_one_record_is_not_a_conflict(self):
        with self.assertRaises(CurationError):
            ConflictAnalysis(state=ConflictState.PRESENT,
                             conflicting_evidence_uuids=("uuid-1",),
                             disputed_field="x", material=True,
                             curator_analysis="Only one record is named here.")

    def test_none_identified_may_not_name_conflicting_records(self):
        with self.assertRaises(CurationError):
            ConflictAnalysis(state=ConflictState.NONE_IDENTIFIED,
                             conflicting_evidence_uuids=("uuid-1", "uuid-2"))

    def test_a_recorded_conflict_states_materiality(self):
        with self.assertRaises(CurationError):
            ConflictAnalysis(state=ConflictState.PRESENT,
                             conflicting_evidence_uuids=("uuid-1", "uuid-2"),
                             disputed_field="effect direction",
                             curator_analysis="The two records disagree on "
                                              "the direction of the effect.")


class TestInsufficientIsNotLowRisk(unittest.TestCase):
    """SAFETY-INV-001."""

    def test_an_insufficient_conclusion_requires_a_statement(self):
        with self.assertRaises(CurationError):
            record(conclusion_state=ConclusionState.INSUFFICIENT,
                   insufficiency_obj=None)

    def test_reassuring_conclusion_text_is_refused(self):
        for phrase in ("so this combination is low risk",
                       "there is no risk to the patient here",
                       "this appears safe for the stated scope",
                       "the evidence rules out an interaction"):
            with self.subTest(phrase=phrase):
                with self.assertRaises(CurationError) as caught:
                    record(conclusion_state=ConclusionState.INSUFFICIENT,
                           insufficiency_obj=insufficiency(),
                           conclusion_text="No evidence addresses this scope, "
                                           + phrase)
                self.assertIn("reassurance", str(caught.exception))

    def test_reassuring_language_in_the_statement_itself_is_refused(self):
        with self.assertRaises(CurationError):
            insufficiency(why_no_stronger_conclusion=
                          "Nothing was found, so the combination is safe for "
                          "the population in question.")

    def test_an_insufficient_conclusion_still_lists_what_was_reviewed(self):
        with self.assertRaises(CurationError):
            insufficiency(evidence_reviewed_uuids=())

    def test_a_well_formed_insufficient_conclusion_is_accepted(self):
        item = record(conclusion_state=ConclusionState.INSUFFICIENT,
                      insufficiency_obj=insufficiency(),
                      conclusion_text="No reviewed record addresses the "
                                      "intermediate metaboliser scope, so no "
                                      "conclusion is supported for it.")
        self.assertFalse(item.is_rule_eligible)
        self.assertIsNotNone(item.insufficiency)

    def test_insufficiency_on_a_non_insufficient_conclusion_is_refused(self):
        with self.assertRaises(CurationError):
            record(conclusion_state=ConclusionState.SUPPORTED,
                   insufficiency_obj=insufficiency())

    def test_the_reassuring_term_list_covers_the_obvious_phrasings(self):
        for term in ("low risk", "no risk", "safe", "no effect",
                     "negative evidence", "rules out"):
            self.assertIn(term, REASSURING_TERMS)

    def test_find_reassuring_language_ignores_case_and_spacing(self):
        self.assertEqual(find_reassuring_language("This  is   LOW  RISK."),
                         ("low risk",))


class TestConflictingIsNotReassurance(unittest.TestCase):
    """SAFETY-INV-008: sources disagreeing is not evidence of absence."""

    def test_a_conflicting_conclusion_may_not_read_as_reassurance(self):
        with self.assertRaises(CurationError) as caught:
            record(conclusion_state=ConclusionState.CONFLICTING,
                   evidence=(selection("uuid-1"), selection("uuid-2")),
                   conflict=unresolved_conflict(),
                   conclusion_text="The sources disagree, so there is no risk "
                                   "either way for this combination.")
        self.assertIn("reassurance", str(caught.exception))

    def test_a_conflicting_conclusion_requires_a_recorded_conflict(self):
        with self.assertRaises(CurationError):
            record(conclusion_state=ConclusionState.CONFLICTING,
                   conflict=no_conflict())
