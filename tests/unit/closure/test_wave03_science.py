# -*- coding: utf-8 -*-
"""Wave 3 source grounding, curation and candidate ruleset (WP-C05..C08)."""

from __future__ import annotations

import unittest

from pgx.closure.authority import CandidateAuthorityState
from pgx.closure.candidate_curation import (CURATIONS, JOINT_CHECKS,
                                            RECOMMENDATION_MAPPING,
                                            attention_for_recommendation,
                                            joint_consistency_failures,
                                            single_axis_attention)
from pgx.closure.candidate_ruleset import (PERMITTED_CHANNELS, REFUSALS,
                                           build_candidate_ruleset)
from pgx.closure.source_grounding import (INTERFACES, LICENCE_BASES,
                                          RETRIEVAL_CLASSIFICATION,
                                          RETRIEVAL_LIMITS, RETRIEVALS,
                                          extraction_digest)
from pgx.closure.source_rows import (AMITRIPTYLINE_JOINT_ROWS, ROWS,
                                     UNREPRESENTABLE_REASONS,
                                     project_phenotype_for,
                                     unrepresentable_rows)
from pgx.domain.enums import AttentionLevel, Phenotype

FIRST_RELEASE_DRUGS = ("clopidogrel", "codeine", "omeprazole",
                       "amitriptyline")
FIRST_RELEASE_GENES = ("CYP2C19", "CYP2D6")


class SourceGroundingTest(unittest.TestCase):

    def test_one_retrieval_per_first_release_drug(self):
        self.assertEqual(sorted(r.drug for r in RETRIEVALS),
                         sorted(FIRST_RELEASE_DRUGS))

    def test_every_retrieval_carries_a_citation(self):
        for item in RETRIEVALS:
            self.assertRegex(item.pmid, r"^\d{6,9}$")
            self.assertTrue(item.doi.startswith("10."))
            self.assertTrue(item.annotation_url.endswith(item.annotation_id))
            self.assertTrue(item.guideline_url.endswith(item.guideline_id))

    def test_retrieval_is_not_described_as_a_download_or_an_api(self):
        self.assertEqual(RETRIEVAL_CLASSIFICATION,
                         "AGENT_ASSISTED_TARGETED_RETRIEVAL")
        for item in RETRIEVALS:
            self.assertEqual(item.to_json()["retrieval_classification"],
                             RETRIEVAL_CLASSIFICATION)

    def test_the_retrieval_classification_is_not_an_acquisition_mode(self):
        # It deliberately is not a member of the production vocabulary; see
        # AB-07. If somebody adds it there, this test should be revisited
        # along with the migration that widens the check constraint.
        from pgx.scientific.models import AcquisitionMode
        self.assertNotIn(RETRIEVAL_CLASSIFICATION,
                         {member.value for member in AcquisitionMode})

    def test_the_limits_are_stated_rather_than_approximated(self):
        self.assertGreaterEqual(len(RETRIEVAL_LIMITS), 5)
        joined = " ".join(RETRIEVAL_LIMITS)
        self.assertIn("no byte-level hash", joined)
        self.assertIn("no per-request timestamp", joined)

    def test_the_observed_bound_is_not_presented_as_the_instant(self):
        for item in RETRIEVALS:
            payload = item.to_json()
            self.assertIn("observed_not_later_than", payload)
            self.assertNotIn("retrieved_at", payload)

    def test_every_interface_names_a_licence_basis_that_exists(self):
        keys = {basis.basis_key for basis in LICENCE_BASES}
        for interface in INTERFACES:
            self.assertIn(interface.licence_basis_key, keys)

    def test_every_retrieval_names_an_interface_that_exists(self):
        keys = {interface.interface_key for interface in INTERFACES}
        for item in RETRIEVALS:
            self.assertIn(item.interface_key, keys)

    def test_the_cc0_basis_quotes_the_dedication(self):
        cpic = [b for b in LICENCE_BASES if b.basis_key == "cpic.cc0"][0]
        self.assertEqual(cpic.licence_identifier, "CC0-1.0")
        self.assertIn("free of restriction", cpic.statement_verbatim)
        self.assertIn("cpicpgx", cpic.evidence_url)

    def test_a_licence_basis_states_what_it_does_not_cover(self):
        for basis in LICENCE_BASES:
            self.assertTrue(basis.does_not_cover,
                            "%s claims no limits at all" % basis.basis_key)

    def test_the_clinpgx_api_is_prohibited_everywhere_it_is_mentioned(self):
        annotation = [i for i in INTERFACES
                      if i.interface_key == "clinpgx.guideline_annotation"][0]
        self.assertTrue(any("api.clinpgx.org" in item
                            for item in annotation.prohibited_here))

    def test_extraction_digest_is_stable_and_content_sensitive(self):
        first = extraction_digest([row.to_json() for row in ROWS])
        second = extraction_digest([row.to_json() for row in ROWS])
        self.assertEqual(first, second)
        mutated = [row.to_json() for row in ROWS]
        mutated[0]["classification"] = "Weak"
        self.assertNotEqual(first, extraction_digest(mutated))


class SourceRowsTest(unittest.TestCase):

    def test_rows_cover_every_first_release_axis(self):
        pairs = {(row.gene, row.drug) for row in ROWS}
        self.assertEqual(pairs, {
            ("CYP2C19", "clopidogrel"),
            ("CYP2C19", "omeprazole"),
            ("CYP2C19", "amitriptyline"),
            ("CYP2D6", "codeine"),
            ("CYP2D6", "amitriptyline"),
        })

    def test_clopidogrel_rows_are_restricted_to_acs_and_pci(self):
        for row in ROWS:
            if row.drug == "clopidogrel":
                self.assertEqual(row.context, "ACS and/or PCI")

    def test_no_cyp2d6_rapid_row_exists(self):
        for row in ROWS:
            if row.gene == "CYP2D6":
                self.assertNotIn("rapid metabolizer",
                                 row.source_phenotype.lower().replace(
                                     "ultrarapid metabolizer", ""))

    def test_unrepresentable_rows_are_recorded_not_dropped(self):
        rows = unrepresentable_rows()
        self.assertGreaterEqual(len(rows), 7)
        for row in rows:
            self.assertIn(row.source_phenotype, UNREPRESENTABLE_REASONS)
            self.assertIn("unrepresentable_reason", row.to_json())

    def test_likely_phenotypes_never_map_to_a_determinate_member(self):
        for row in ROWS:
            if "likely" in row.source_phenotype.lower():
                self.assertIsNone(row.project_phenotype)

    def test_an_unclassified_label_raises_rather_than_defaulting(self):
        with self.assertRaises(KeyError):
            project_phenotype_for("CYP2C19 brisk metabolizer")

    def test_an_unlisted_likely_label_raises(self):
        with self.assertRaises(KeyError):
            project_phenotype_for("CYP2D6 likely normal metabolizer")

    def test_the_joint_table_is_complete(self):
        self.assertEqual(len(AMITRIPTYLINE_JOINT_ROWS), 16)
        pairs = set()
        for cell in AMITRIPTYLINE_JOINT_ROWS:
            for member in cell.cyp2c19_members():
                pairs.add((member, cell.cyp2d6_member()))
        self.assertEqual(len(pairs), 20)

    def test_the_joint_table_never_aliases_rapid_to_ultrarapid(self):
        merged = [c for c in AMITRIPTYLINE_JOINT_ROWS
                  if "Ultrarapid or Rapid" in c.cyp2c19_source_phenotype]
        self.assertEqual(len(merged), 4)
        for cell in merged:
            self.assertEqual(set(cell.cyp2c19_members()),
                             {Phenotype.ULTRARAPID, Phenotype.RAPID})


class CurationTest(unittest.TestCase):

    def test_every_curation_is_source_grounded_and_pending(self):
        for item in CURATIONS:
            self.assertIs(
                item.authority_state,
                CandidateAuthorityState.SOURCE_GROUNDED_INTERNAL_DECISION)
            self.assertIs(
                item.review_state,
                CandidateAuthorityState.PENDING_EXTERNAL_EXPERT_REVIEW)

    def test_the_curator_is_named_as_a_process_not_a_person(self):
        for item in CURATIONS:
            self.assertIn("no human curator", item.curated_by)

    def test_every_curation_carries_its_own_rationale(self):
        for item in CURATIONS:
            self.assertGreater(len(item.rationale), 30)

    def test_an_unmapped_recommendation_raises(self):
        with self.assertRaises(KeyError):
            attention_for_recommendation("Give it a go.")

    def test_no_active_attention_is_only_used_where_nothing_is_asked(self):
        for text, (level, _reason) in RECOMMENDATION_MAPPING.items():
            if level is AttentionLevel.NO_ACTIVE_ATTENTION:
                lowered = text.lower()
                for hedge in ("consider", "monitor", "avoid", "if no "
                              "response", "alternative"):
                    self.assertNotIn(
                        hedge, lowered,
                        "%r carries a qualifier and cannot be "
                        "NO_ACTIVE_ATTENTION" % text)

    def test_every_avoidance_is_high(self):
        for text, (level, _reason) in RECOMMENDATION_MAPPING.items():
            if text.lower().startswith("avoid"):
                self.assertIs(level, AttentionLevel.HIGH, text)

    def test_the_joint_table_check_covers_all_twenty_combinations(self):
        self.assertEqual(len(JOINT_CHECKS), 20)
        seen = {(c.cyp2c19_phenotype, c.cyp2d6_phenotype)
                for c in JOINT_CHECKS}
        self.assertEqual(len(seen), 20)

    def test_no_combination_understates_the_joint_guideline(self):
        failures = joint_consistency_failures()
        self.assertEqual(
            failures, (),
            "combining the single-gene amitriptyline rules would understate "
            "the guideline's joint table at: %s"
            % ", ".join("%s+%s" % (c.cyp2c19_phenotype.value,
                                   c.cyp2d6_phenotype.value)
                        for c in failures))

    def test_the_understatement_detector_can_actually_fire(self):
        # A detector that never fires proves nothing about the table above.
        from pgx.closure.candidate_curation import JointCheck
        from pgx.engine.risk_models import ATTENTION_PRECEDENCE
        order = list(ATTENTION_PRECEDENCE)
        rigged = JointCheck(
            cyp2c19_phenotype=Phenotype.NORMAL,
            cyp2d6_phenotype=Phenotype.NORMAL,
            joint_recommendation="Avoid amitriptyline use.",
            joint_level=AttentionLevel.HIGH,
            combined_level=AttentionLevel.LOW,
            understates=order.index(AttentionLevel.LOW) >
            order.index(AttentionLevel.HIGH))
        self.assertTrue(rigged.understates)

    def test_single_axis_attention_returns_none_for_an_uncurated_axis(self):
        self.assertIsNone(single_axis_attention("CYP2D6", "clopidogrel",
                                                Phenotype.POOR))


class CandidateRulesetTest(unittest.TestCase):

    def setUp(self):
        self.ruleset = build_candidate_ruleset()

    def test_the_ruleset_is_the_size_the_scope_calls_for(self):
        self.assertGreaterEqual(len(self.ruleset.rules), 20)
        self.assertLessEqual(len(self.ruleset.rules), 25)

    def test_it_is_not_a_computable_rule_definition(self):
        from pgx.rules.models import ComputableRuleDefinition
        for rule in self.ruleset.rules:
            self.assertNotIsInstance(rule, ComputableRuleDefinition)

    def test_production_is_not_a_permitted_channel(self):
        self.assertEqual(PERMITTED_CHANNELS, ("DEMO", "VALIDATION"))
        self.assertEqual(self.ruleset.permitted_channels, PERMITTED_CHANNELS)
        self.assertNotIn("PRODUCTION", self.ruleset.permitted_channels)

    def test_the_ruleset_is_pending_external_review(self):
        self.assertIs(self.ruleset.review_state,
                      CandidateAuthorityState.PENDING_EXTERNAL_EXPERT_REVIEW)

    def test_no_rule_is_keyed_on_indeterminate(self):
        for rule in self.ruleset.rules:
            self.assertNotIn(Phenotype.INDETERMINATE,
                             rule.condition.phenotype.values)

    def test_cyp2d6_rapid_is_refused_for_every_cyp2d6_drug(self):
        for _gene, drug in (("CYP2D6", "codeine"),
                            ("CYP2D6", "amitriptyline")):
            matches = [r for r in REFUSALS
                       if r.gene == "CYP2D6" and r.drug == drug
                       and r.project_phenotype == Phenotype.RAPID.value]
            self.assertEqual(len(matches), 1, drug)
            self.assertEqual(matches[0].reason_code, "AXIS_ABSENT_FROM_SOURCE")

    def test_no_cyp2d6_rule_answers_rapid(self):
        for rule in self.ruleset.rules:
            if rule.condition.gene_canonical_key == "GENE:CYP2D6":
                self.assertNotIn(Phenotype.RAPID,
                                 rule.condition.phenotype.values)

    def test_every_phenotype_is_ruled_or_refused(self):
        ruled = {(c.gene, c.drug, c.phenotype.value) for c in CURATIONS}
        refused = {(r.gene, r.drug, r.project_phenotype) for r in REFUSALS}
        for gene, drug in {(c.gene, c.drug) for c in CURATIONS}:
            for member in Phenotype:
                triple = (gene, drug, member.value)
                self.assertTrue(triple in ruled or triple in refused,
                                "%s / %s / %s has no answer and no refusal"
                                % triple)

    def test_every_refusal_states_a_reason(self):
        for item in REFUSALS:
            self.assertGreater(len(item.reason), 40, item.to_json())
            self.assertIn(item.reason_code, {
                "PHENOTYPE_NOT_REPRESENTABLE",
                "SOURCE_STATES_NO_RECOMMENDATION",
                "AXIS_ABSENT_FROM_SOURCE",
                "SOURCE_ROW_ABSENT",
            })

    def test_the_content_hash_is_deterministic(self):
        self.assertEqual(build_candidate_ruleset().content_hash(),
                         self.ruleset.content_hash())

    def test_the_content_hash_moves_when_a_rule_changes(self):
        import dataclasses
        from pgx.rules.models import RuleOutcome
        rules = list(self.ruleset.rules)
        rules[0] = dataclasses.replace(
            rules[0],
            outcome=RuleOutcome(attention_level=AttentionLevel.LOW,
                                rationale_reference="x"))
        mutated = dataclasses.replace(self.ruleset, rules=tuple(rules))
        self.assertNotEqual(mutated.content_hash(),
                            self.ruleset.content_hash())

    def test_every_rule_traces_to_a_retrieval(self):
        keys = {item.retrieval_key for item in RETRIEVALS}
        for rule in self.ruleset.rules:
            self.assertIn(rule.retrieval_key, keys)

    def test_every_rule_quotes_the_source_recommendation(self):
        texts = {row.recommendation_verbatim for row in ROWS}
        for rule in self.ruleset.rules:
            self.assertIn(rule.source_recommendation, texts)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
