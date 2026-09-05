# -*- coding: utf-8 -*-
"""The WP-15 document set, and the claims it is allowed to make.

The failure that matters is a document asserting something nobody
established: a handoff saying a report was published, an evidence note
describing a test that does not exist, a template contract that has drifted
from the code, or a claim that a model was called when none was. Every claim
below is checked against the code, the data, or the environment it describes.
"""

from __future__ import annotations

import io
import json
import os
import re
import unittest

from pgx.application.report_cli import REFUSED_FLAGS, build_parser
from pgx.application.report_gate_status import (BLOCKER_CODES,
                                                DEFAULT_REPORT_ROOT,
                                                GATE_STATUS_FILENAME,
                                                build_report_gate_status)
from pgx.reporting.errors import REPORT_FAILURE_CODES
from pgx.reporting.gate import SCANNER_LIMITS
from pgx.reporting.legacy_regression import (NOT_PORTED,
                                             PORTED_LAYOUT_CONCEPTS,
                                             REPORT_EXPECTED_DIFFERENCES)
from pgx.reporting.structured import REPORT_SCHEMA_VERSION
from pgx.reporting.templates import (MEDICATION_QUESTIONS, SUPPORTED_LOCALES,
                                     TEMPLATE_VERSION)
from tests.unit.reporting._support import (REPORT_APPLICATION_MODULES,
                                           REPO_ROOT, WP15_REPORTING_MODULES,
                                           source)

ARCHITECTURE = os.path.join("docs", "architecture",
                            "wp15-deterministic-reporting.md")
DETERMINISM = os.path.join("docs", "evidence", "wp15-determinism.md")
CLAIM_SAFETY = os.path.join("docs", "evidence", "wp15-claim-safety.md")
MIGRATION = os.path.join("docs", "migration",
                         "wp15-legacy-report-migration.md")
HANDOFF = os.path.join("docs", "handoffs", "wp15-handoff.md")

DOCUMENTS = (ARCHITECTURE, DETERMINISM, CLAIM_SAFETY, MIGRATION, HANDOFF)

READMES = (os.path.join("data", "reports", "README.md"),
           os.path.join("data", "migration", "wp15", "README.md"),
           os.path.join("tests", "fixtures", "wp15", "README.md"))


def _text(relative):
    return source(os.path.join(REPO_ROOT, relative))


class DocumentCase(unittest.TestCase):
    """Assertions that report the missing phrase rather than the document."""

    def assertSays(self, relative, needle):
        self.assertTrue(needle in _text(relative),
                        "%s does not contain %r" % (relative, needle))

    def assertDoesNotSay(self, relative, needle):
        self.assertFalse(needle in _text(relative).lower(),
                         "%s contains %r" % (relative, needle))


class TestTheDocumentSetExists(DocumentCase):

    def test_every_document_is_present(self):
        for relative in DOCUMENTS + READMES:
            with self.subTest(document=relative):
                self.assertTrue(os.path.isfile(os.path.join(REPO_ROOT,
                                                            relative)))

    def test_every_document_carries_an_identifier_table(self):
        for relative in DOCUMENTS:
            with self.subTest(document=relative):
                self.assertSays(relative, "| Document ID |")
                self.assertSays(relative, "WP-15")

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
        for version in (REPORT_SCHEMA_VERSION, TEMPLATE_VERSION,
                        "pgx-canonical-assessment-result/1",
                        "pgx-report-renderer/1",
                        "pgx-report-artifact-manifest/1",
                        "pgx-report-fact-ledger/1"):
            with self.subTest(version=version):
                self.assertSays(ARCHITECTURE, version)

    def test_the_architecture_note_lists_every_module(self):
        for name in WP15_REPORTING_MODULES + REPORT_APPLICATION_MODULES:
            if name == "__init__.py":
                continue
            with self.subTest(module=name):
                self.assertSays(ARCHITECTURE, name)

    def test_the_architecture_note_counts_the_commands_and_flags(self):
        commands = set()
        for action in build_parser()._actions:
            if getattr(action, "choices", None):
                commands.update(action.choices)
        self.assertSays(ARCHITECTURE,
                        "%d read-mostly commands" % len(commands))
        self.assertSays(ARCHITECTURE, "%d refused flags" % len(REFUSED_FLAGS))

    def test_the_architecture_note_counts_the_failure_codes(self):
        self.assertSays(ARCHITECTURE,
                        "%d stable codes" % len(REPORT_FAILURE_CODES))

    def test_the_architecture_note_lists_the_eight_questions(self):
        self.assertSays(ARCHITECTURE, "eight")
        for identifier, _text in MEDICATION_QUESTIONS:
            with self.subTest(question=identifier):
                self.assertSays(ARCHITECTURE, "`%s`" % identifier)

    def test_the_architecture_note_lists_every_attention_and_coverage_code(
            self):
        from pgx.reporting.templates import ATTENTION_LABELS, COVERAGE_LABELS
        for code in list(ATTENTION_LABELS) + list(COVERAGE_LABELS):
            with self.subTest(code=code):
                self.assertSays(ARCHITECTURE, "`%s`" % code)

    def test_the_determinism_note_lists_every_digest(self):
        for name in ("output_hash", "report_hash", "rendered_checksum"):
            with self.subTest(digest=name):
                self.assertSays(DETERMINISM, name)

    def test_the_claim_safety_note_lists_every_scanner_limit(self):
        text = _text(CLAIM_SAFETY).lower()
        for limit in SCANNER_LIMITS:
            fragment = limit.split(":")[0].split(",")[0].strip().lower()
            with self.subTest(limit=fragment):
                self.assertIn(fragment[:40], text)

    def test_the_claim_safety_note_names_every_prohibited_category(self):
        from pgx.domain.claims import ProhibitedClaimCategory
        for category in ProhibitedClaimCategory:
            with self.subTest(category=category.value):
                self.assertSays(CLAIM_SAFETY, category.value)

    def test_the_migration_note_lists_every_ported_and_unported_concept(self):
        for name, _description in PORTED_LAYOUT_CONCEPTS:
            with self.subTest(concept=name):
                self.assertSays(MIGRATION, "`%s`" % name)
        for name, _reason in NOT_PORTED:
            with self.subTest(concept=name):
                self.assertSays(MIGRATION, "`%s`" % name)

    def test_the_migration_note_lists_every_expected_difference(self):
        for entry in REPORT_EXPECTED_DIFFERENCES:
            with self.subTest(difference=entry.difference_id):
                self.assertSays(MIGRATION, "`%s`" % entry.difference_id)
                self.assertSays(MIGRATION, "`%s`" % entry.legacy_bug_id)

    def test_the_handoff_lists_every_blocker(self):
        for code in BLOCKER_CODES:
            with self.subTest(blocker=code):
                self.assertSays(HANDOFF, "`%s`" % code)

    def test_the_handoff_names_every_supported_locale(self):
        for locale in SUPPORTED_LOCALES:
            with self.subTest(locale=locale):
                self.assertSays(HANDOFF, "`%s`" % locale)

    def test_the_test_count_claimed_by_the_handoff_is_not_inflated(self):
        """A number in a handoff is a claim like any other."""
        import unittest as _unittest
        match = re.search(r"WP-15 contributes ([\d,]+) of", _text(HANDOFF))
        self.assertIsNotNone(match)
        claimed = int(match.group(1).replace(",", ""))
        loader = _unittest.TestLoader()
        counted = 0
        for module in (
                "tests.unit.reporting.test_canonical_result",
                "tests.unit.reporting.test_structured_report",
                "tests.unit.reporting.test_fact_preservation",
                "tests.unit.reporting.test_safe_status_rendering",
                "tests.unit.reporting.test_determinism",
                "tests.unit.reporting.test_injection",
                "tests.unit.reporting.test_artifacts",
                "tests.unit.reporting.test_wp15_boundaries",
                "tests.unit.reporting.test_wp15_documentation",
                "tests.unit.reporting.test_legacy_report_regression",
                "tests.unit.application.test_report_cli",
                "tests.unit.application.test_assessment_preflight",
                "tests.adversarial.test_report_claims",
                "tests.contract.test_wp15_schemas",
                "tests.integration.reporting.test_report_end_to_end"):
            counted += loader.loadTestsFromName(module).countTestCases()
        self.assertEqual(claimed, counted)


class TestTheGateStatusIsHonest(DocumentCase):

    def setUp(self):
        self.status = build_report_gate_status(REPO_ROOT).to_json()

    def test_it_reports_zero_real_reports(self):
        self.assertEqual(self.status["real_report_count"], 0)
        self.assertEqual(self.status["real_assessment_count"], 0)
        self.assertEqual(self.status["published_artifact_count"], 0)

    def test_it_says_publication_is_blocked(self):
        self.assertFalse(self.status["may_publish_real_reports"])
        self.assertEqual(self.status["blocker_count"], len(BLOCKER_CODES))

    def test_it_says_everything_so_far_is_synthetic(self):
        self.assertTrue(self.status["synthetic_only"])

    def test_it_says_no_model_is_implemented(self):
        self.assertFalse(self.status["llm_enabled"])
        self.assertFalse(self.status["llm_provider_implemented"])

    def test_the_stored_copy_matches_a_regeneration(self):
        path = os.path.join(REPO_ROOT, DEFAULT_REPORT_ROOT,
                            GATE_STATUS_FILENAME)
        self.assertTrue(os.path.isfile(path))
        with io.open(path, encoding="utf-8") as handle:
            stored = json.load(handle)
        self.assertEqual(stored, self.status)

    def test_the_report_directory_holds_no_report(self):
        root = os.path.join(REPO_ROOT, DEFAULT_REPORT_ROOT)
        published = [name for name in os.listdir(root)
                     if name.startswith("report-")]
        self.assertEqual(published, [])


class TestNoDocumentOverclaims(DocumentCase):

    #: Phrases that would assert something nobody established.
    FORBIDDEN_PHRASES = ("is safe", "safe to", "safe for",
                         "clinically validated", "clinically approved",
                         "recommended dose", "should be prescribed",
                         "treatment recommendation", "ready for clinical",
                         "production ready", "fit for clinical use",
                         "is validated for", "a report was published",
                         "gemini was called")

    #: Words that make a claim of existence into a denial of one.
    NEGATIONS = ("no ", "not ", "none", "never", "cannot", "can not", "n't",
                 "without", "nothing", "nobody", "until", "before", "zero",
                 "refus", "blocked", "must not", "may not", "prohibit",
                 "forbid", "would", "legacy", "unblock")

    def assertOnlyDenied(self, relative, pattern):
        text = _text(relative).lower()
        start = 0
        while True:
            index = text.find(pattern, start)
            if index < 0:
                return
            run_up = text[max(0, index - 180):index]
            self.assertTrue(
                any(marker in run_up for marker in self.NEGATIONS),
                "%s asserts %r at offset %d" % (relative, pattern, index))
            start = index + len(pattern)

    def test_no_document_claims_clinical_readiness(self):
        for relative in DOCUMENTS + READMES:
            for phrase in self.FORBIDDEN_PHRASES:
                with self.subTest(document=relative, phrase=phrase):
                    self.assertOnlyDenied(relative, phrase)

    def test_no_document_claims_a_model_was_called(self):
        for relative in DOCUMENTS:
            with self.subTest(document=relative):
                self.assertOnlyDenied(relative, "model was called")

    def test_no_document_claims_a_real_assessment_exists(self):
        for relative in DOCUMENTS:
            with self.subTest(document=relative):
                self.assertOnlyDenied(relative, "real assessment")

    def test_the_evidence_notes_say_everything_is_synthetic(self):
        self.assertSays(DETERMINISM, "synthetic")
        self.assertSays(HANDOFF, "synthetic")

    def test_the_handoff_says_postgresql_did_not_run(self):
        self.assertSays(HANDOFF, "PostgreSQL")
        self.assertSays(HANDOFF, "not run")


if __name__ == "__main__":
    unittest.main()
