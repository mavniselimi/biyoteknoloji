# -*- coding: utf-8 -*-
"""What a curation record must contain, and what it may never contain (WP-09).

Each test changes one thing about an otherwise valid record, so a failure
names the rule that fired rather than the fixture.
"""

from __future__ import annotations

import unittest

from pgx.application.curation_schema import validate_curation_record
from pgx.curation.errors import (CurationError, EvidenceSelectionError,
                                 RationaleError, RoleSeparationError,
                                 VocabularyError)
from pgx.curation.models import (PROHIBITED_CURATION_FIELDS,
                                 CurationQuestion, EvidenceSelection,
                                 SourceReportedValues,
                                 find_prohibited_curation_fields)
from pgx.curation.vocabulary import (ConclusionState, ConflictState,
                                     CurationRole, EffectDimension,
                                     EvidenceRelationship, ExclusionReason,
                                     InterpretationStatus)
from pgx.domain.enums import Phenotype

from tests.unit.curation._support import (AUTHOR, REVIEWER, insufficiency,
                                          no_conflict, question, rationale,
                                          record, selection, signature,
                                          unresolved_conflict)


class TestEvidenceIsRequired(unittest.TestCase):

    def test_a_conclusion_with_no_evidence_is_refused(self):
        with self.assertRaises(EvidenceSelectionError):
            record(evidence=())

    def test_the_same_record_cannot_be_cited_twice(self):
        with self.assertRaises(EvidenceSelectionError):
            record(evidence=(selection("uuid-1"), selection("uuid-1")))

    def test_a_conclusion_whose_evidence_is_all_excluded_is_refused(self):
        """Excluding everything is a finding of INSUFFICIENT, recorded as one -
        not a supported conclusion resting on nothing."""
        with self.assertRaises(EvidenceSelectionError):
            record(evidence=(selection(
                "uuid-1", EvidenceRelationship.EXCLUDED,
                ExclusionReason.WRONG_POPULATION,
                "The cited population is paediatric and this question is "
                "scoped to adults."),))

    def test_a_valid_record_lists_its_inclusions_and_exclusions(self):
        item = record(evidence=(
            selection("uuid-1"),
            selection("uuid-2", EvidenceRelationship.EXCLUDED,
                      ExclusionReason.WRONG_PHENOTYPE_SCOPE,
                      "Addresses ultrarapid metabolisers, outside the poor "
                      "metaboliser scope of this question.")))
        self.assertEqual(item.included_evidence_uuids(), ("uuid-1",))
        self.assertEqual(item.excluded_evidence_uuids(), ("uuid-2",))


class TestExclusionsAreReasoned(unittest.TestCase):

    def test_an_exclusion_without_a_controlled_reason_is_refused(self):
        with self.assertRaises(EvidenceSelectionError):
            EvidenceSelection(
                evidence_record_uuid="uuid-2", natural_key="nk",
                relationship=EvidenceRelationship.EXCLUDED,
                rationale="Not relevant to the question as it is scoped.",
                source_version_status="KNOWN",
                provider_source_key="clinpgx.api")

    def test_a_reason_on_a_non_exclusion_is_refused(self):
        with self.assertRaises(EvidenceSelectionError):
            EvidenceSelection(
                evidence_record_uuid="uuid-3", natural_key="nk",
                relationship=EvidenceRelationship.SUPPORTS,
                exclusion_reason=ExclusionReason.OUT_OF_SCOPE,
                rationale="Directly addresses the activation dimension.",
                source_version_status="KNOWN",
                provider_source_key="clinpgx.api")

    def test_every_selection_carries_a_written_rationale(self):
        """Inclusions too. 'Why is this in' is as much a scientific statement
        as 'why is this out'."""
        with self.assertRaises((RationaleError, CurationError)):
            EvidenceSelection(
                evidence_record_uuid="uuid-4", natural_key="nk",
                relationship=EvidenceRelationship.SUPPORTS, rationale="ok",
                source_version_status="KNOWN",
                provider_source_key="clinpgx.api")

    def test_a_placeholder_selection_rationale_is_refused(self):
        for text in ("copied from legacy seed values for this pair",
                     "MANUAL_EFFECT_HINTS says so for this gene and drug",
                     "the score is high enough to include this record",
                     "the AI selected it as the most relevant record",
                     "this is clinically known to everyone in the field"):
            with self.subTest(text=text):
                with self.assertRaises(RationaleError):
                    selection(rationale=text)

    def test_every_controlled_exclusion_reason_is_usable(self):
        for reason in ExclusionReason:
            with self.subTest(reason=reason):
                item = selection(
                    "uuid-x", EvidenceRelationship.EXCLUDED, reason,
                    "Excluded after review for the stated controlled reason, "
                    "with the scope difference described here.")
                self.assertFalse(item.is_included)


class TestRationaleContract(unittest.TestCase):

    def test_curated_without_a_rationale_is_refused(self):
        with self.assertRaises(RationaleError):
            record(status=InterpretationStatus.CURATED, rationale_obj=None)

    def test_a_missing_part_is_named(self):
        with self.assertRaises(RationaleError) as caught:
            rationale(source_to_conclusion="")
        self.assertIn("source_to_conclusion", caught.exception.missing)

    def test_a_blank_part_is_refused(self):
        with self.assertRaises(RationaleError):
            rationale(conflict_assessment="   ")

    def test_placeholder_parts_are_refused(self):
        for text in ("copied from legacy, nothing further to add here",
                     "MANUAL_EFFECT_HINTS says so and that is sufficient",
                     "the score is high so the association is real",
                     "the AI selected it after reviewing the annotations",
                     "this is clinically known and needs no citation",
                     "see above for the reasoning behind this conclusion",
                     "TBD", "n/a", "----"):
            with self.subTest(text=text):
                with self.assertRaises(RationaleError):
                    rationale(source_to_conclusion=text)

    def test_a_rationale_that_restates_the_conclusion_is_circular(self):
        conclusion = ("CYP2C19 poor metabolisers show reduced clopidogrel "
                      "activation according to the cited annotation.")
        with self.assertRaises(RationaleError) as caught:
            record(conclusion_text=conclusion,
                   rationale_obj=rationale(source_to_conclusion=conclusion))
        self.assertIn("restates the conclusion", str(caught.exception))
        self.assertIn("source_to_conclusion: circular",
                      caught.exception.rejected)

    def test_a_rationale_that_adds_reasoning_is_accepted(self):
        item = record()
        self.assertFalse(
            item.rationale.is_circular_against(item.conclusion_text))

    def test_an_unknown_part_is_refused(self):
        with self.assertRaises(RationaleError):
            rationale(invented_part="something")


class TestSourceAndConclusionStaySeparate(unittest.TestCase):

    def test_source_reported_values_are_held_apart(self):
        item = record(source_reported=(SourceReportedValues(
            evidence_record_uuid="uuid-1",
            source_fields={"significance": "yes", "score": 3.75}),))
        payload = item.to_json()
        self.assertEqual(payload["source_reported"][0]["source_fields"]
                         ["significance"], "yes")
        # And the curator's conclusion is a different key entirely.
        self.assertNotIn("significance", payload)
        self.assertNotIn("score", payload)

    def test_the_record_carries_no_source_significance_field_of_its_own(self):
        payload = record().to_json()
        for name in ("significance", "score", "polarity", "isAssociated"):
            self.assertNotIn(name, payload)

    def test_a_legacy_project_value_cannot_be_smuggled_in(self):
        """Unlike an evidence record, where the source payload is sacrosanct,
        a curation record is this project's object throughout - so a legacy
        risk level copied into it would be this project asserting it again."""
        with self.assertRaises(CurationError):
            record(source_reported=(SourceReportedValues(
                evidence_record_uuid="uuid-1",
                source_fields={"demo_risk_level": "high"}),))


class TestSourceSignificanceIsNotAConclusion(unittest.TestCase):

    def test_the_rationale_must_explain_rather_than_cite_the_flag(self):
        """A rationale whose only content is the source's flag adds nothing
        the flag did not already say."""
        conclusion = "The association is supported."
        with self.assertRaises(RationaleError):
            record(conclusion_text=conclusion + " " * 0 +
                   " The evidence supports the association as stated.",
                   rationale_obj=rationale(
                       source_to_conclusion="The evidence supports the "
                                            "association as stated."))

    def test_the_field_dictionary_prohibits_the_direct_mapping(self):
        from pgx.curation.fields import field_definition
        prohibited = " ".join(
            field_definition("source_reported").prohibited_interpretations)
        self.assertIn("significance", prohibited.lower())
        self.assertIn("score", prohibited.lower())


class TestCurationGranularity(unittest.TestCase):

    def test_a_question_names_gene_drug_and_effect_dimension(self):
        item = question()
        self.assertTrue(item.gene_canonical_key.startswith("GENE:"))
        self.assertTrue(item.drug_canonical_key.startswith("DRUG:"))
        self.assertIsInstance(item.effect_dimension, EffectDimension)

    def test_a_bare_entity_name_is_refused(self):
        with self.assertRaises(CurationError):
            question(gene="CYP2C19")

    def test_two_questions_over_one_pair_are_different_questions(self):
        """This is what stops a pair-level conclusion applying to every
        annotation sharing that pair."""
        activation = question(effect=EffectDimension.ACTIVATION)
        exposure = question(effect=EffectDimension.EXPOSURE)
        self.assertNotEqual(activation.content_identity(),
                            exposure.content_identity())

    def test_a_phenotype_scope_may_not_repeat(self):
        with self.assertRaises(CurationError):
            question(phenotypes=(Phenotype.POOR, Phenotype.POOR))

    def test_an_empty_scope_is_permitted_and_is_not_a_wildcard(self):
        item = question(phenotypes=())
        self.assertEqual(item.phenotype_scope, ())
        from pgx.curation.fields import field_definition
        self.assertIn("wildcard", " ".join(
            field_definition("question.phenotype_scope")
            .prohibited_interpretations).lower())


class TestRapidAndUltrarapidStayDistinct(unittest.TestCase):
    """SAFETY-INV-004. The existing enum is reused unchanged."""

    def test_they_are_separate_members(self):
        self.assertNotEqual(Phenotype.RAPID, Phenotype.ULTRARAPID)

    def test_covering_both_requires_listing_both(self):
        rapid_only = question(phenotypes=(Phenotype.RAPID,))
        both = question(phenotypes=(Phenotype.RAPID, Phenotype.ULTRARAPID))
        self.assertNotIn(Phenotype.ULTRARAPID, rapid_only.phenotype_scope)
        self.assertEqual(len(both.phenotype_scope), 2)

    def test_a_record_scoped_to_rapid_does_not_carry_ultrarapid(self):
        item = record(phenotypes=(Phenotype.RAPID,))
        self.assertEqual(item.normalized_phenotypes, (Phenotype.RAPID,))

    def test_no_curation_module_aliases_the_two(self):
        from tests.unit.curation._support import source_text
        import os
        directory = os.path.join("pgx", "curation")
        for name in sorted(os.listdir(os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__))))),
                "pgx", "curation"))):
            if not name.endswith(".py"):
                continue
            body = source_text(os.path.join(directory, name))
            for alias in ("RAPID = ULTRARAPID", "ULTRARAPID = RAPID",
                          "RAPID_GROUP", "rapid_or_ultrarapid"):
                with self.subTest(module=name, alias=alias):
                    self.assertNotIn(alias, body)


class TestNoNumericJudgement(unittest.TestCase):

    def test_numeric_score_names_are_prohibited(self):
        for name in ("confidence", "confidence_score", "certainty_score",
                     "evidence_score", "quality_score", "safety_score",
                     "severity_score", "strength_score", "weight", "rank"):
            with self.subTest(name=name):
                self.assertIn(name, PROHIBITED_CURATION_FIELDS)

    def test_a_record_carrying_a_confidence_score_is_refused(self):
        with self.assertRaises(CurationError):
            record(source_reported=(SourceReportedValues(
                evidence_record_uuid="uuid-1",
                source_fields={"confidence_score": 0.9}),))

    def test_a_nested_score_is_found(self):
        found = find_prohibited_curation_fields(
            {"outer": [{"inner": {"safety_score": 3}}]})
        self.assertEqual(found, ("outer[0].inner.safety_score",))

    def test_no_vocabulary_member_is_numeric(self):
        from pgx.curation.vocabulary import vocabulary_registry
        for name, members in vocabulary_registry().items():
            for member in members:
                with self.subTest(vocabulary=name, member=member):
                    self.assertFalse(member.replace("_", "").isdigit())

    def test_conclusion_states_cannot_be_ordered(self):
        with self.assertRaises(VocabularyError):
            ConclusionState.INSUFFICIENT < ConclusionState.SUPPORTED


class TestNoExecutableOrPrescriptiveFields(unittest.TestCase):

    def test_rule_and_treatment_names_are_prohibited(self):
        for name in ("condition", "matcher_condition", "rule_condition",
                     "dose", "dosage", "recommendation", "contraindication",
                     "alternative_drug", "avoid"):
            with self.subTest(name=name):
                self.assertIn(name, PROHIBITED_CURATION_FIELDS)

    def test_a_record_carrying_a_dose_is_refused(self):
        with self.assertRaises(CurationError):
            record(source_reported=(SourceReportedValues(
                evidence_record_uuid="uuid-1",
                source_fields={"dose": "75mg"}),))

    def test_a_record_carrying_a_rule_condition_is_refused(self):
        with self.assertRaises(CurationError):
            record(source_reported=(SourceReportedValues(
                evidence_record_uuid="uuid-1",
                source_fields={"rule_condition": {"phenotype": "POOR"}}),))

    def test_the_effect_vocabulary_names_no_action(self):
        for member in EffectDimension:
            with self.subTest(member=member):
                for forbidden in ("AVOID", "REDUCE", "INCREASE_DOSE",
                                  "PREFER", "CONTRAINDICATED", "SAFE"):
                    self.assertNotEqual(member.value, forbidden)


class TestTheRecordValidatesAgainstItsPublishedSchema(unittest.TestCase):

    def test_a_valid_record_validates(self):
        self.assertEqual(validate_curation_record(record().to_json()), ())

    def test_a_smuggled_risk_level_fails_the_schema(self):
        payload = record().to_json()
        payload["risk_level"] = "HIGH"
        self.assertTrue(validate_curation_record(payload))

    def test_a_record_with_no_evidence_fails_the_schema(self):
        payload = record().to_json()
        payload["evidence"] = []
        self.assertTrue(validate_curation_record(payload))
