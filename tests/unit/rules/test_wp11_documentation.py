# -*- coding: utf-8 -*-
"""The WP-11 document set, and the claims it is allowed to make.

The failure that matters here is a document asserting a state nobody set: a
handoff saying a rule exists, an evidence file describing a run that did not
happen, or any sentence a reader could take as a clinical claim. Every claim
below is checked against the code or the data it describes.

The test that matters most is the last one. These documents are the part of
the work somebody reads without running anything, so a sentence promising more
than the system does is more dangerous here than a bug.
"""

from __future__ import annotations

import io
import json
import os
import re
import unittest

from pgx.application.rule_gate_status import BLOCKER_CODES, build_gate_status
from pgx.rules.conditions import PHENOTYPE_OPERATORS
from pgx.rules.conflicts import CONFLICT_KINDS
from pgx.rules.models import (RULE_OUTCOME_LEVELS, allowed_rule_transitions,
                              allowed_ruleset_transitions)
from pgx.rules.validator import ISSUE_CODES
from tests.unit.rules._support import GATE_STATUS_JSON, REPO_ROOT, source

DOCUMENTS = (
    os.path.join("docs", "architecture", "wp11-rules-and-rulesets.md"),
    os.path.join("docs", "data", "computable-rule-contract.md"),
    os.path.join("docs", "scientific", "rule-authoring-and-approval.md"),
    os.path.join("docs", "operations", "rule-registry-operations.md"),
    os.path.join("docs", "migration", "wp11-legacy-rule-candidates.md"),
    os.path.join("docs", "evidence", "wp11-schema-validation.md"),
    os.path.join("docs", "risk-management", "wp11-execution-governance.md"),
    os.path.join("docs", "handoffs", "wp11-handoff.md"),
)

SCHEMAS = (
    os.path.join("schemas", "computable-rule.schema.json"),
    os.path.join("schemas", "ruleset-manifest.schema.json"),
    os.path.join("schemas", "ruleset-build-log.schema.json"),
    os.path.join("schemas", "ruleset-approval-list.schema.json"),
    os.path.join("schemas", "wp11-gate-status.schema.json"),
    os.path.join("schemas", "legacy-rule-candidate-inventory.schema.json"),
)


def _text(relative):
    return source(os.path.join(REPO_ROOT, relative))


class TestTheDocumentSetExists(unittest.TestCase):

    def test_every_document_is_present(self):
        for relative in DOCUMENTS:
            with self.subTest(document=relative):
                self.assertTrue(os.path.isfile(os.path.join(REPO_ROOT,
                                                            relative)))

    def test_every_schema_is_present(self):
        for relative in SCHEMAS:
            with self.subTest(schema=relative):
                self.assertTrue(os.path.isfile(os.path.join(REPO_ROOT,
                                                            relative)))

    def test_every_document_carries_an_identifier_table(self):
        for relative in DOCUMENTS:
            text = _text(relative)
            with self.subTest(document=relative):
                self.assertIn("| Document ID |", text)
                self.assertIn("WP-11", text)

    def test_no_document_is_a_stub(self):
        for relative in DOCUMENTS:
            with self.subTest(document=relative):
                self.assertGreater(len(_text(relative).splitlines()), 40)


class TestTheDocumentsDescribeTheCodeThatExists(unittest.TestCase):

    def test_the_contract_names_the_two_real_operators(self):
        text = _text(os.path.join("docs", "data",
                                  "computable-rule-contract.md"))
        for operator in PHENOTYPE_OPERATORS:
            with self.subTest(operator=operator):
                self.assertIn(operator, text)

    def test_the_contract_names_the_four_authorable_levels(self):
        text = _text(os.path.join("docs", "data",
                                  "computable-rule-contract.md"))
        for level in RULE_OUTCOME_LEVELS:
            with self.subTest(level=level.value):
                self.assertIn(level.value, text)
        self.assertIn("NOT_ASSESSED", text)
        self.assertIn("not** one of them", text)

    def test_the_architecture_note_states_both_lifecycles_correctly(self):
        text = _text(os.path.join("docs", "architecture",
                                  "wp11-rules-and-rulesets.md"))
        for status in allowed_rule_transitions():
            with self.subTest(status=status.value):
                self.assertIn(status.value, text)
        for status in allowed_ruleset_transitions():
            with self.subTest(status=status.value):
                self.assertIn(status.value, text)

    def test_the_architecture_note_reports_the_real_issue_code_count(self):
        text = _text(os.path.join("docs", "architecture",
                                  "wp11-rules-and-rulesets.md"))
        self.assertIn("%d issue codes" % len(ISSUE_CODES), text)

    def test_the_architecture_note_reports_the_real_conflict_count(self):
        text = _text(os.path.join("docs", "architecture",
                                  "wp11-rules-and-rulesets.md"))
        self.assertIn("Eight kinds", text)
        self.assertEqual(len(CONFLICT_KINDS), 8)

    def test_the_operations_note_lists_every_command_that_exists(self):
        from pgx.application.rules_cli import build_parser
        text = _text(os.path.join("docs", "operations",
                                  "rule-registry-operations.md"))
        parser = build_parser()
        commands = ()
        for action in parser._actions:  # noqa: SLF001 - argparse has no API
            if hasattr(action, "choices") and action.choices:
                commands = tuple(sorted(action.choices))
        self.assertTrue(commands)
        for command in commands:
            with self.subTest(command=command):
                self.assertIn(command, text)

    def test_the_operations_note_lists_every_refused_flag(self):
        from pgx.application.rules_cli import REFUSED_FLAGS
        text = _text(os.path.join("docs", "operations",
                                  "rule-registry-operations.md"))
        for flag in REFUSED_FLAGS:
            with self.subTest(flag=flag):
                self.assertIn(flag, text)

    def test_the_migration_note_matches_the_real_inventory(self):
        text = _text(os.path.join("docs", "migration",
                                  "wp11-legacy-rule-candidates.md"))
        with io.open(os.path.join(REPO_ROOT, "data", "migration", "wp11",
                                  "legacy-rule-candidate-inventory.json"),
                     encoding="utf-8") as handle:
            counts = json.load(handle)["counts"]
        self.assertIn("{:,}".format(counts["candidates"]), text)
        self.assertIn("{:,}".format(counts["linked"]), text)
        for code, total in counts["by_blocker_code"].items():
            with self.subTest(code=code):
                self.assertIn(code, text)
                self.assertIn("{:,}".format(total), text)

    def test_the_handoff_reports_the_real_zero_counts(self):
        text = _text(os.path.join("docs", "handoffs", "wp11-handoff.md"))
        with io.open(GATE_STATUS_JSON, encoding="utf-8") as handle:
            state = json.load(handle)["rule_state"]
        for name, value in state.items():
            with self.subTest(count=name):
                self.assertEqual(value, 0,
                                 "the handoff says zero; the data must agree")
        self.assertIn("Real validated rules | **0**", text)
        self.assertIn("Real frozen rulesets | **0**", text)

    def test_the_risk_note_covers_every_gate_blocker_family(self):
        text = _text(os.path.join("docs", "risk-management",
                                  "wp11-execution-governance.md"))
        self.assertIn("WP-23", text)
        self.assertTrue(BLOCKER_CODES)
        self.assertTrue(build_gate_status(REPO_ROOT).to_json()["blockers"])


class TestNoDocumentClaimsSomethingThatIsNotTrue(unittest.TestCase):

    #: Sentences that would be false today. Matched case-insensitively as
    #: whole phrases, because each one is a specific claim rather than a word
    #: that happens to be forbidden.
    FALSE_CLAIMS = (
        "clinically validated",
        "clinically approved",
        "approved by a clinician",
        "has been approved by",
        "is safe to",
        "is safe for",
        "safe to prescribe",
        "recommended dose",
        "ready for clinical use",
        "ready for production use",
        "production ready",
        "fit for clinical",
        "validated by an expert",
        "expert-approved",
        "rules are in production",
    )

    def test_no_document_makes_a_claim_that_is_false_today(self):
        for relative in DOCUMENTS:
            text = _text(relative).lower()
            for claim in self.FALSE_CLAIMS:
                with self.subTest(document=relative, claim=claim):
                    self.assertNotIn(claim, text)

    def test_no_document_states_a_clinical_recommendation(self):
        """The documents describe a system that must not recommend anything.
        They must not recommend anything either."""
        pattern = re.compile(
            r"(take|give|prescribe|switch to|avoid)\s+\w+\s*(mg|mcg)", re.I)
        for relative in DOCUMENTS:
            with self.subTest(document=relative):
                self.assertIsNone(pattern.search(_text(relative)))

    def test_the_documents_say_plainly_that_nothing_is_approved(self):
        for relative in (os.path.join("docs", "handoffs", "wp11-handoff.md"),
                         os.path.join("docs", "scientific",
                                      "rule-authoring-and-approval.md")):
            text = _text(relative)
            with self.subTest(document=relative):
                self.assertTrue(
                    "No rule has been authored" in text
                    or "No real rule exists" in text,
                    "a WP-11 document that does not say this is misleading "
                    "by omission")

    def test_the_evidence_note_does_not_claim_alembic_ran(self):
        text = _text(os.path.join("docs", "evidence",
                                  "wp11-schema-validation.md"))
        self.assertIn("This is not Alembic", text)
        self.assertIn("remains **BLOCKED**", text)

    def test_the_evidence_note_says_what_it_does_not_prove(self):
        text = _text(os.path.join("docs", "evidence",
                                  "wp11-schema-validation.md"))
        self.assertIn("What this does **not** prove", text)
        self.assertIn("scientifically correct", text)

    def test_no_document_calls_the_axis_list_coverage(self):
        """"Coverage" is the specific word this project must not use for an
        inventory of what exists."""
        for relative in DOCUMENTS:
            text = _text(relative)
            for line in text.splitlines():
                lowered = line.lower()
                if "structural_axes" not in lowered:
                    continue
                with self.subTest(document=relative, line=line[:60]):
                    self.assertNotIn("coverage of", lowered)


if __name__ == "__main__":
    unittest.main()
