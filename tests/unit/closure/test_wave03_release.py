# -*- coding: utf-8 -*-
"""Wave 3 candidate release, catalogue and evaluator (WP-C09, WP-C10)."""

from __future__ import annotations

import json
import os
import unittest

from pgx.closure.candidate_cases import (CATALOGUE_LIMITATIONS,
                                         build_catalogue)
from pgx.closure.candidate_release import evaluate, not_weaker_than
from pgx.closure.candidate_ruleset import build_candidate_ruleset
from pgx.domain.enums import AttentionLevel, Phenotype
from pgx.validation.separation import audit_partition
from pgx.validation.vocabulary import ValidationCaseRole

REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
RELEASE = os.path.join(REPO, "data", "closure", "wave-03-candidate-release")


class CatalogueTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.cases = build_catalogue()
        cls.audit = audit_partition([case.metadata for case in cls.cases])

    def test_the_catalogue_meets_the_first_release_targets(self):
        self.assertGreaterEqual(len(self.cases), 50)
        self.assertGreaterEqual(self.audit.internal_holdout_count, 20)
        self.assertGreaterEqual(self.audit.expert_holdout_count, 10)

    def test_the_separation_audit_is_clean(self):
        self.assertEqual(
            self.audit.issues, (),
            "; ".join("%s %s" % (i.code, i.detail)
                      for i in self.audit.issues))

    def test_a_development_case_cannot_be_relabelled_as_a_holdout(self):
        # Stronger than the audit: the type refuses the combination at
        # construction, so the rigged case cannot be built to be audited.
        import dataclasses

        from pgx.validation.errors import VisibilityError
        first = self.cases[0].metadata
        self.assertIs(first.role, ValidationCaseRole.DEVELOPMENT)
        with self.assertRaises(VisibilityError):
            dataclasses.replace(first,
                                role=ValidationCaseRole.INTERNAL_HOLDOUT)

    def test_the_audit_is_capable_of_reporting_an_issue(self):
        # A clean audit above proves nothing unless the auditor can fail. Two
        # holdout cases sharing one content fingerprint is a real defect the
        # type permits and the audit must catch.
        import dataclasses
        holdout = [c.metadata for c in self.cases
                   if c.metadata.role is ValidationCaseRole.INTERNAL_HOLDOUT]
        duplicate = dataclasses.replace(
            holdout[0],
            case_id=type(holdout[0].case_id)(holdout[0].case_id.value + "-X"))
        rigged = audit_partition([holdout[0], duplicate])
        self.assertNotEqual(rigged.issues, ())
        self.assertIn("CONTENT_DUPLICATE_WITHIN_PARTITION",
                      {issue.code for issue in rigged.issues})

    def test_holdout_cases_are_not_derived_from_development(self):
        for case in self.cases:
            if case.metadata.role is ValidationCaseRole.DEVELOPMENT:
                continue
            self.assertFalse(
                case.metadata.provenance.derived_from_development,
                case.metadata.case_id.value)

    def test_every_case_carries_a_citation(self):
        for case in self.cases:
            self.assertTrue(case.metadata.provenance.citation)

    def test_the_case_author_is_named_as_a_process(self):
        for case in self.cases:
            self.assertIn("NOT A HUMAN",
                          case.metadata.provenance.author or "")

    def test_no_case_carries_patient_data(self):
        permitted = {"gene", "drug", "phenotype", "context", "CYP2C19",
                     "CYP2D6", "source_phenotype", "project_phenotype"}
        for case in self.cases:
            self.assertLessEqual(set(case.content), permitted,
                                 case.metadata.case_id.value)

    def test_the_catalogue_states_that_it_is_not_independent(self):
        joined = " ".join(CATALOGUE_LIMITATIONS)
        self.assertIn("no partition here is independent", joined)
        self.assertIn("external expert should bring their own cases", joined)

    def test_the_catalogue_is_deterministic(self):
        again = build_catalogue()
        self.assertEqual(
            [c.metadata.content_fingerprint for c in again],
            [c.metadata.content_fingerprint for c in self.cases])

    def test_no_case_id_is_shaped_like_a_governed_ruleset_id(self):
        for case in self.cases:
            self.assertIsNone(case.metadata.compatibility.ruleset_public_id)
            self.assertIsNone(case.metadata.compatibility.release_public_id)


class EvaluatorTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.ruleset = build_candidate_ruleset()

    def test_a_covered_axis_answers(self):
        result = evaluate(self.ruleset, drug="clopidogrel",
                          phenotypes={"CYP2C19": Phenotype.POOR})
        self.assertEqual(result.outcome, "ATTENTION")
        self.assertIs(result.attention_level, AttentionLevel.HIGH)

    def test_cyp2d6_rapid_refuses_rather_than_reassuring(self):
        for drug in ("codeine", "amitriptyline"):
            result = evaluate(self.ruleset, drug=drug,
                              phenotypes={"CYP2D6": Phenotype.RAPID})
            self.assertEqual(result.outcome, "REFUSED", drug)
            self.assertIsNone(result.attention_level, drug)

    def test_indeterminate_refuses(self):
        result = evaluate(self.ruleset, drug="omeprazole",
                          phenotypes={"CYP2C19": Phenotype.INDETERMINATE})
        self.assertEqual(result.outcome, "REFUSED")

    def test_one_uncovered_axis_refuses_the_whole_input(self):
        result = evaluate(
            self.ruleset, drug="amitriptyline",
            phenotypes={"CYP2C19": Phenotype.NORMAL,
                        "CYP2D6": Phenotype.RAPID})
        self.assertEqual(result.outcome, "REFUSED")
        self.assertEqual(result.axes_without_a_rule,
                         ("CYP2D6|amitriptyline|RAPID",))
        self.assertIsNone(result.attention_level)

    def test_a_refusal_is_never_reported_as_no_active_attention(self):
        result = evaluate(self.ruleset, drug="codeine",
                          phenotypes={"CYP2D6": Phenotype.RAPID})
        self.assertNotEqual(result.to_json()["attention_level"],
                            AttentionLevel.NO_ACTIVE_ATTENTION.value)

    def test_an_unknown_drug_refuses(self):
        result = evaluate(self.ruleset, drug="warfarin",
                          phenotypes={"CYP2C19": Phenotype.POOR})
        self.assertEqual(result.outcome, "REFUSED")

    def test_two_axes_take_the_precedence_maximum(self):
        result = evaluate(
            self.ruleset, drug="amitriptyline",
            phenotypes={"CYP2C19": Phenotype.NORMAL,
                        "CYP2D6": Phenotype.INTERMEDIATE})
        self.assertIs(result.attention_level, AttentionLevel.MEDIUM)
        self.assertEqual(len(result.matched_rule_keys), 2)

    def test_not_weaker_than_orders_by_precedence(self):
        self.assertTrue(not_weaker_than(AttentionLevel.HIGH,
                                        AttentionLevel.MEDIUM))
        self.assertTrue(not_weaker_than(AttentionLevel.MEDIUM,
                                        AttentionLevel.MEDIUM))
        self.assertFalse(not_weaker_than(AttentionLevel.LOW,
                                         AttentionLevel.HIGH))
        self.assertFalse(not_weaker_than(AttentionLevel.NO_ACTIVE_ATTENTION,
                                         AttentionLevel.LOW))


class CommittedReleaseTest(unittest.TestCase):
    """The artifacts on disk, read as a reviewer would read them."""

    @classmethod
    def setUpClass(cls):
        path = os.path.join(RELEASE, "manifest.json")
        if not os.path.exists(path):
            raise unittest.SkipTest("no candidate release has been built")
        with open(path, encoding="utf-8") as handle:
            cls.manifest = json.load(handle)

    def test_the_release_says_it_is_not_governed(self):
        self.assertFalse(self.manifest["is_governed_release"])
        self.assertEqual(self.manifest["permitted_channels"],
                         ["DEMO", "VALIDATION"])
        self.assertEqual(self.manifest["review_state"],
                         "PENDING_EXTERNAL_EXPERT_REVIEW")

    def test_the_release_pins_the_ruleset_that_is_in_the_code(self):
        self.assertEqual(self.manifest["summary"]["ruleset_content_hash"],
                         build_candidate_ruleset().content_hash())

    def test_no_expert_payload_was_read(self):
        self.assertEqual(self.manifest["summary"]["expert_payloads_read"], 0)
        with open(os.path.join(RELEASE, "access-ledger.json"),
                  encoding="utf-8") as handle:
            ledger = json.load(handle)
        events = ledger["events"] if isinstance(ledger, dict) else ledger
        for event in events:
            if event["case_role"] == "EXPERT_HOLDOUT":
                self.assertEqual(event["action"], "LIST_METADATA",
                                 event["case_id"])

    def test_the_access_chain_is_intact(self):
        self.assertTrue(self.manifest["summary"]["ledger_chain_ok"])

    def test_every_artifact_digest_still_matches(self):
        import hashlib
        for item in self.manifest["artifacts"]:
            path = os.path.join(RELEASE, item["relative_path"])
            with open(path, "rb") as handle:
                raw = handle.read()
            self.assertEqual("sha256:" + hashlib.sha256(raw).hexdigest(),
                             item["sha256"], item["relative_path"])

    def test_the_evaluation_passed_without_failures(self):
        summary = self.manifest["summary"]
        self.assertEqual(summary["failed_count"], 0)
        self.assertEqual(summary["separation_issue_count"], 0)
        self.assertEqual(summary["evaluated_count"],
                         summary["development_count"]
                         + summary["internal_holdout_count"])

    def test_the_manifest_says_what_the_evaluation_does_not_prove(self):
        joined = " ".join(self.manifest["summary"]["catalogue_limitations"])
        self.assertIn("is independent of the build it tests", joined)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class RebuildDeterminismTest(unittest.TestCase):
    """The committed artifacts are the ones this code produces.

    Worth a test rather than a convention: the first version of both build
    scripts stamped a wall-clock instant into the manifest, which made every
    rebuild differ from the committed bytes and made "is this artifact
    current" unanswerable. The instants were removed rather than tolerated,
    following the same rule ``ComputableRuleDefinition.semantic_content``
    already applies - when something was made is recorded by git, not by the
    thing itself.
    """

    def test_no_wave03_artifact_stamps_a_wall_clock_instant(self):
        for root in ("wave-03-candidate-evidence", "wave-03-candidate-release"):
            path = os.path.join(REPO, "data", "closure", root, "manifest.json")
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
            for field in ("sealed_at", "built_at", "generated_at"):
                self.assertNotIn(field, payload, "%s/%s" % (root, field))

    def test_the_access_ledger_uses_a_fixed_clock(self):
        path = os.path.join(RELEASE, "access-ledger.json")
        if not os.path.exists(path):
            self.skipTest("no candidate release has been built")
        with open(path, encoding="utf-8") as handle:
            ledger = json.load(handle)
        events = ledger["events"] if isinstance(ledger, dict) else ledger
        self.assertTrue(events)
        instants = {event["occurred_at"] for event in events}
        self.assertEqual(
            len(instants), 1,
            "the ledger's value is the order of accesses and the hash chain "
            "over them; differing instants only make the artifact differ from "
            "itself on every rebuild")
