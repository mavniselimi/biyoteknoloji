# -*- coding: utf-8 -*-
"""The WP-13 document set, and the claims it is allowed to make.

The failure that matters is a document asserting something nobody established:
a handoff saying a coverage claim exists, an evidence note describing a test
that does not, a truth table that has drifted from the engine, or any sentence
a reader could take as clinical. Every claim below is checked against the code
or the data it describes.
"""

from __future__ import annotations

import io
import json
import os
import re
import unittest

from pgx.application.coverage_cli import REFUSED_FLAGS, build_parser
from pgx.application.coverage_gate_status import (BLOCKER_CODES,
                                                  build_coverage_gate_status)
from pgx.domain.enums import CoverageReasonCode, CoverageStatus
from pgx.engine.coverage import (COVERAGE_ENGINE_CONTRACT_VERSION,
                                 AXIS_DECISION_TABLE,
                                 MEDICATION_DECISION_TABLE,
                                 OVERALL_DECISION_TABLE, truth_table)
from pgx.engine.coverage_legacy import EXPECTED_DIFFERENCES
from pgx.engine.coverage_manifest import COVERAGE_MANIFEST_SCHEMA_VERSION
from pgx.engine.coverage_validator import MANIFEST_ISSUE_CODES
from tests.unit.engine._support import (COVERAGE_APPLICATION_MODULES,
                                        REPO_ROOT, WP13_ENGINE_MODULES, source)

ARCHITECTURE = os.path.join("docs", "architecture", "wp13-coverage-engine.md")
MIGRATION = os.path.join("docs", "migration", "wp13-coverage-regression.md")
TRUTH_TABLE = os.path.join("docs", "evidence", "wp13-coverage-truth-table.md")
INVARIANTS = os.path.join("docs", "evidence", "wp13-safety-invariants.md")
HANDOFF = os.path.join("docs", "handoffs", "wp13-handoff.md")

DOCUMENTS = (ARCHITECTURE, MIGRATION, TRUTH_TABLE, INVARIANTS, HANDOFF)


def _text(relative):
    return source(os.path.join(REPO_ROOT, relative))


class DocumentCase(unittest.TestCase):
    """Assertions that report the missing phrase rather than the document.

    ``assertIn`` prints its container on failure, and a container here is a
    whole markdown file. A reader of a failing run should see which sentence
    is missing, not five screens of the document that lacks it.
    """

    def assertSays(self, relative, needle):
        self.assertTrue(needle in _text(relative),
                        "%s does not contain %r" % (relative, needle))

    def assertDoesNotSay(self, relative, needle):
        self.assertFalse(needle in _text(relative).lower(),
                         "%s contains %r" % (relative, needle))


class TestTheDocumentSetExists(DocumentCase):

    def test_every_document_is_present(self):
        for relative in DOCUMENTS:
            with self.subTest(document=relative):
                self.assertTrue(os.path.isfile(os.path.join(REPO_ROOT,
                                                            relative)))

    def test_every_document_carries_an_identifier_table(self):
        for relative in DOCUMENTS:
            with self.subTest(document=relative):
                self.assertSays(relative, "| Document ID |")
                self.assertSays(relative, "WP-13")

    def test_no_document_is_a_stub(self):
        for relative in DOCUMENTS:
            with self.subTest(document=relative):
                self.assertGreater(len(_text(relative).splitlines()), 60)

    def test_every_document_id_is_distinct(self):
        found = []
        for relative in DOCUMENTS:
            match = re.search(r"`(DOC-[A-Z]+-\w+)`", _text(relative))
            self.assertIsNotNone(match, relative)
            found.append(match.group(1))
        self.assertEqual(len(set(found)), len(DOCUMENTS))


class TestTheDocumentsDescribeTheCodeThatExists(DocumentCase):

    def test_the_architecture_note_names_the_contract_versions(self):
        for version in (COVERAGE_ENGINE_CONTRACT_VERSION,
                        COVERAGE_MANIFEST_SCHEMA_VERSION):
            with self.subTest(version=version):
                self.assertSays(ARCHITECTURE, version)

    def test_the_architecture_note_lists_every_wp13_module(self):
        for name in WP13_ENGINE_MODULES + COVERAGE_APPLICATION_MODULES:
            with self.subTest(module=name):
                self.assertSays(ARCHITECTURE, name)

    def test_the_architecture_note_lists_every_status(self):
        for status in CoverageStatus:
            with self.subTest(status=status.value):
                self.assertSays(ARCHITECTURE, status.value)

    def test_the_architecture_note_lists_every_reason_code(self):
        for code in CoverageReasonCode:
            with self.subTest(code=code.value):
                self.assertSays(ARCHITECTURE, code.value)

    def test_the_architecture_note_counts_the_commands_and_flags(self):
        commands = set()
        for action in build_parser()._actions:
            if getattr(action, "choices", None):
                commands.update(action.choices)
        self.assertSays(ARCHITECTURE, "%d read-only commands" % len(commands))
        self.assertSays(ARCHITECTURE,
                        "%d refused flags" % len(REFUSED_FLAGS))

    def test_the_architecture_note_counts_the_issue_codes(self):
        self.assertSays(ARCHITECTURE, "%d ways a manifest can be untrue"
                        % len(MANIFEST_ISSUE_CODES))

    def test_the_truth_table_document_matches_the_engine(self):
        """Generated from the tables themselves. If they drift, this fails."""
        for level, table in (("axis", AXIS_DECISION_TABLE),
                             ("medication", MEDICATION_DECISION_TABLE),
                             ("overall", OVERALL_DECISION_TABLE)):
            for row in table:
                with self.subTest(level=level, case=row["case"]):
                    self.assertSays(TRUTH_TABLE, "`%s`" % row["case"])
                    self.assertSays(TRUTH_TABLE, row["when"])
                    for code in row["reasons"]:
                        self.assertSays(TRUTH_TABLE, "`%s`" % code.value)

    def test_the_truth_table_document_names_the_contract_version(self):
        self.assertSays(TRUTH_TABLE,
                        truth_table()["coverage_engine_contract_version"])

    def test_the_evidence_note_names_the_invariants_it_claims(self):
        for invariant in ("SAFETY-INV-001", "SAFETY-INV-003",
                          "SAFETY-INV-004", "SAFETY-INV-005",
                          "SAFETY-INV-006", "SAFETY-INV-008"):
            with self.subTest(invariant=invariant):
                self.assertSays(INVARIANTS, invariant)

    def test_every_test_path_named_in_a_document_exists(self):
        for relative in DOCUMENTS:
            for match in re.findall(r"tests/[\w/]+\.py", _text(relative)):
                with self.subTest(document=relative, path=match):
                    self.assertTrue(
                        os.path.isfile(os.path.join(REPO_ROOT, match)),
                        "%s does not exist" % match)

    def test_every_source_path_named_in_a_document_exists(self):
        for relative in DOCUMENTS:
            for match in re.findall(r"`(pgx/[\w/]+\.py)`", _text(relative)):
                with self.subTest(document=relative, path=match):
                    self.assertTrue(
                        os.path.isfile(os.path.join(REPO_ROOT, match)))

    def test_every_data_artifact_named_in_a_document_exists(self):
        for relative in DOCUMENTS:
            for match in re.findall(r"`(data/[\w/\-.]+\.json)`",
                                    _text(relative)):
                with self.subTest(document=relative, path=match):
                    self.assertTrue(
                        os.path.isfile(os.path.join(REPO_ROOT, match)))

    def test_the_migration_note_lists_every_allowlist_entry(self):
        for entry in EXPECTED_DIFFERENCES:
            with self.subTest(entry=entry.difference_id):
                self.assertSays(MIGRATION, entry.difference_id)
                self.assertSays(MIGRATION, entry.legacy_bug_id)

    def test_the_migration_note_quotes_the_report_hash_on_disk(self):
        path = os.path.join(REPO_ROOT, "data", "migration", "wp13",
                            "coverage-regression-report.json")
        with io.open(path, encoding="utf-8") as handle:
            document = json.load(handle)
        self.assertSays(MIGRATION, document["content_hash"])

    def test_the_handoff_lists_every_blocker_the_gate_reports(self):
        status = build_coverage_gate_status(REPO_ROOT).to_json()
        text = _text(HANDOFF).lower()
        self.assertEqual({item["code"] for item in status["blockers"]},
                         set(BLOCKER_CODES))
        for marker in ("awaiting_expert_review", "building", "quarantined",
                       "no frozen ruleset", "scientific role"):
            with self.subTest(marker=marker):
                self.assertTrue(marker in text,
                                "the handoff does not mention %r" % marker)

    def test_the_handoff_counts_match_the_gate_status(self):
        status = build_coverage_gate_status(REPO_ROOT).to_json()
        for name, value in status["coverage_state"].items():
            with self.subTest(count=name):
                self.assertEqual(value, 0)
        self.assertSays(HANDOFF, "| Real approved coverage manifests | 0 |")
        self.assertSays(HANDOFF, "| Real coverage executions | 0 |")


class TestNoDocumentOverclaims(DocumentCase):

    #: Phrases that would assert something nobody established.
    #:
    #: Deliberately not "is preferred" or "is suitable": SAFETY-INV-005 is
    #: named "no candidate is preferred, ranked or scored" in the safety
    #: contract, and a check that failed on the invariant's own name would
    #: push the invariant out of the evidence note rather than the claim. The
    #: dangerous shape here is an assertion about a medicine, and the phrases
    #: below are the ones that make one.
    FORBIDDEN_PHRASES = ("is safe", "safe to", "safe for",
                         "clinically validated", "clinically approved",
                         "recommended dose", "should be prescribed",
                         "contraindicated", "treatment recommendation",
                         "ready for clinical", "production ready",
                         "fit for clinical use", "is validated for")

    def test_no_document_makes_a_clinical_claim(self):
        for relative in DOCUMENTS:
            for phrase in self.FORBIDDEN_PHRASES:
                with self.subTest(document=relative, phrase=phrase):
                    self.assertDoesNotSay(relative, phrase)

    #: Words that make a claim of existence into a denial of one. Checked in
    #: the run-up to the phrase rather than by picking needles that a denial
    #: happens not to contain: "no real coverage claim exists" contains "real
    #: coverage claim exists", and a needle chosen to dodge that is a needle
    #: that stops matching the moment somebody rewords the sentence.
    NEGATIONS = ("no ", "not ", "none", "never", "cannot", "can not", "n't",
                 "without", "nothing", "nobody", "until", "before")

    def assertOnlyDenied(self, relative, pattern):
        """Every occurrence of ``pattern`` is inside a denial."""
        text = _text(relative).lower().replace("\n", " ")
        for match in re.finditer(pattern, text):
            start = max(0, match.start() - 60)
            run_up = text[start:match.start()]
            with self.subTest(document=relative,
                              context=text[start:match.end()][-90:]):
                self.assertTrue(
                    any(word in run_up for word in self.NEGATIONS),
                    "%s asserts %r" % (relative,
                                       text[start:match.end()][-90:]))

    def test_no_document_claims_a_real_coverage_claim_exists(self):
        for relative in DOCUMENTS:
            self.assertOnlyDenied(relative,
                                  r"coverage (?:manifest|claim) exists")
            self.assertOnlyDenied(relative, r"coverage (?:is|has been) "
                                            r"approved")

    def test_no_document_claims_the_protocol_was_approved(self):
        for relative in DOCUMENTS:
            self.assertOnlyDenied(relative,
                                  r"protocol (?:is|has been|was) approved")
            with self.subTest(document=relative):
                self.assertDoesNotSay(relative, "expert review is complete")

    def test_the_denial_check_would_catch_an_affirmative_claim(self):
        """The check above passes trivially if its pattern matches nothing.

        This asserts it does not: the documents really do discuss coverage
        manifests existing, and really do only deny it.
        """
        found = 0
        for relative in DOCUMENTS:
            found += len(re.findall(r"coverage (?:manifest|claim) exists",
                                    _text(relative).lower()))
        self.assertGreater(found, 0)

    def test_the_handoff_marks_a38_blocked(self):
        for needle in ("A38", "BLOCKED", "AWAITING_EXPERT_REVIEW"):
            self.assertSays(HANDOFF, needle)

    def test_the_handoff_does_not_report_earlier_blocked_items_as_met(self):
        for item in ("A33", "A30", "A26"):
            with self.subTest(item=item):
                self.assertSays(HANDOFF, item)

    def test_every_document_that_mentions_attention_denies_computing_it(self):
        for relative in DOCUMENTS:
            lines = _text(relative).lower().splitlines()
            for index, line in enumerate(lines):
                if "attention" not in line:
                    continue
                window = " ".join(lines[max(0, index - 3):index + 3])
                with self.subTest(document=relative, line=index + 1):
                    self.assertTrue(
                        any(marker in window
                            for marker in ("not", "no ", "none", "never",
                                           "wp-14", "separat", "nowhere",
                                           "must not", "does not")),
                        "%s:%d %r" % (relative, index + 1, line.strip()))

    def test_the_test_count_claimed_by_the_handoff_is_not_inflated(self):
        """A number in a handoff is a claim like any other. This checks the
        WP-13 contribution against the files that make it up, so the figure
        cannot quietly become aspirational."""
        text = _text(HANDOFF)
        match = re.search(r"WP-13 contributes ([\d,]+) of", text)
        self.assertIsNotNone(match)
        claimed = int(match.group(1).replace(",", ""))
        import unittest as _unittest
        loader = _unittest.TestLoader()
        counted = 0
        for module in ("tests.unit.engine.test_coverage_manifest",
                       "tests.unit.engine.test_coverage_axis",
                       "tests.unit.engine.test_coverage_aggregation",
                       "tests.unit.engine.test_coverage_legacy_regression",
                       "tests.unit.engine.test_wp13_boundaries",
                       "tests.unit.engine.test_wp13_documentation",
                       "tests.unit.application.test_coverage_cli",
                       "tests.safety.test_coverage_safety",
                       "tests.contract.test_wp13_schemas",
                       "tests.integration.engine.test_coverage_end_to_end"):
            counted += loader.loadTestsFromName(module).countTestCases()
        self.assertEqual(claimed, counted)


if __name__ == "__main__":
    unittest.main()
