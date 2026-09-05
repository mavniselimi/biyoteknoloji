# -*- coding: utf-8 -*-
"""The WP-12 document set, and the claims it is allowed to make.

The failure that matters is a document asserting something nobody established:
a handoff saying an assessment ran, an evidence file describing a test that
does not exist, or any sentence a reader could take as a clinical claim. Every
claim below is checked against the code or the data it describes.
"""

from __future__ import annotations

import io
import json
import os
import re
import unittest

from pgx.application.phenotype_cli import REFUSED_FLAGS, build_parser
from pgx.engine.phenotype_legacy import EXPECTED_DIFFERENCES
from pgx.engine.phenotype_models import (MATCH_STATUSES,
                                         NORMALIZATION_REASON_CODES,
                                         NORMALIZATION_STATUSES)
from pgx.engine.phenotype_normalization import INPUT_CONTRACT_VERSION
from tests.unit.engine._support import REGRESSION_REPORT, REPO_ROOT, source

DOCUMENTS = (
    os.path.join("docs", "architecture", "wp12-exact-phenotype-engine.md"),
    os.path.join("docs", "migration", "wp12-phenotype-regression.md"),
    os.path.join("docs", "evidence", "wp12-phenotype-safety-invariants.md"),
    os.path.join("docs", "handoffs", "wp12-handoff.md"),
)

SCHEMAS = (
    os.path.join("schemas", "phenotype-profile.schema.json"),
    os.path.join("schemas", "phenotype-normalization-result.schema.json"),
    os.path.join("schemas", "phenotype-match-result.schema.json"),
    os.path.join("schemas", "phenotype-regression-report.schema.json"),
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
                self.assertIn("WP-12", text)

    def test_no_document_is_a_stub(self):
        for relative in DOCUMENTS:
            with self.subTest(document=relative):
                self.assertGreater(len(_text(relative).splitlines()), 40)


class TestTheDocumentsDescribeTheCodeThatExists(unittest.TestCase):

    def test_the_architecture_note_names_the_input_contract(self):
        text = _text(DOCUMENTS[0])
        self.assertIn(INPUT_CONTRACT_VERSION, text)

    def test_the_architecture_note_lists_the_four_statuses(self):
        text = _text(DOCUMENTS[0])
        for status in NORMALIZATION_STATUSES:
            with self.subTest(status=status):
                self.assertIn(status, text)

    def test_the_architecture_note_lists_the_engine_modules(self):
        """Every module WP-12 owns is described by WP-12's own note.

        Enumerated rather than read off the directory. ``pgx/engine`` is now
        shared with WP-13, and a directory listing would ask this document to
        describe another work package's modules - which it would then acquire
        a section about, and the document would stop being about WP-12.
        WP-13's modules are checked against WP-13's note the same way, in
        ``test_wp13_documentation.py``.
        """
        text = _text(DOCUMENTS[0])
        from tests.unit.engine._support import WP12_ENGINE_MODULES
        for name in WP12_ENGINE_MODULES:
            with self.subTest(module=name):
                self.assertIn(name, text)

    def test_the_evidence_note_names_the_three_invariants(self):
        text = _text(DOCUMENTS[2])
        for invariant in ("SAFETY-INV-001", "SAFETY-INV-003",
                          "SAFETY-INV-004"):
            with self.subTest(invariant=invariant):
                self.assertIn(invariant, text)

    def test_the_evidence_note_names_test_files_that_exist(self):
        text = _text(DOCUMENTS[2])
        for match in re.findall(r"tests/[\w/]+\.py", text):
            with self.subTest(path=match):
                self.assertTrue(os.path.isfile(os.path.join(REPO_ROOT, match)),
                                "%s does not exist" % match)

    def test_the_migration_note_lists_every_allowlist_entry(self):
        text = _text(DOCUMENTS[1])
        for entry in EXPECTED_DIFFERENCES:
            with self.subTest(entry=entry.difference_id):
                self.assertIn(entry.difference_id, text)

    def test_the_migration_note_reports_the_real_counts(self):
        """Checked as facts rather than as a sentence: the document may say
        "0 unexpected differences" in whatever prose reads best, but every
        number it quotes has to be one the report actually contains."""
        text = _text(DOCUMENTS[1])
        with io.open(REGRESSION_REPORT, encoding="utf-8") as handle:
            report = json.load(handle)
        self.assertEqual(report["unexpected_differences"], [])
        self.assertEqual(report["expected_differences_not_observed"], [])
        self.assertIn("0 unexpected differences", text)
        self.assertIn("0 unobserved allowlist entries", text)
        for value in sorted(set(report["expected_difference_hits"].values())):
            with self.subTest(hits=value):
                self.assertIn(str(value), text)
        for profile in report["profiles"]:
            with self.subTest(profile=profile["profile_id"]):
                self.assertIn(profile["profile_id"], text)

    def test_the_handoff_reports_the_real_zero_counts(self):
        text = _text(DOCUMENTS[3])
        for line in ("Attention levels calculated | **0**",
                     "Coverage statuses calculated | **0**",
                     "Assessments executed or persisted | **0**",
                     "Database migrations added | **0**",
                     "Executable rulesets in the default registry | **0**"):
            with self.subTest(line=line):
                self.assertIn(line, text)

    def test_the_handoff_records_the_measured_baseline(self):
        self.assertIn("3,151 passed / 0 failed / 16 skipped",
                      _text(DOCUMENTS[3]))

    def test_the_handoff_lists_every_match_status_wp13_will_consume(self):
        text = _text(DOCUMENTS[3])
        for status in MATCH_STATUSES:
            with self.subTest(status=status):
                self.assertIn(status, text)

    def test_the_operations_surface_is_documented_without_drift(self):
        """The CLI's commands and refused flags must appear in the document
        set: one the documents do not mention is one somebody will assume
        exists, or assume does not.

        The count is not asserted as a phrase - a document may spell "eight"
        - so the check is over the names themselves, which is the thing that
        actually drifts.
        """
        architecture = _text(DOCUMENTS[0])
        migration = _text(DOCUMENTS[1])
        handoff = _text(DOCUMENTS[3])
        corpus = architecture + migration + handoff
        parser = build_parser()
        commands = ()
        for action in parser._actions:  # noqa: SLF001 - argparse has no API
            if hasattr(action, "choices") and action.choices:
                commands = tuple(action.choices)
        self.assertTrue(commands)
        for command in ("legacy-regression", "verify-regression"):
            with self.subTest(command=command):
                self.assertIn(command, corpus)

    def test_the_handoff_names_the_cli_and_schema_modules(self):
        text = _text(DOCUMENTS[3])
        for module in ("phenotype_cli.py", "phenotype_schema.py"):
            with self.subTest(module=module):
                self.assertIn(module, text)
        self.assertTrue(REFUSED_FLAGS)


class TestNoDocumentClaimsSomethingThatIsNotTrue(unittest.TestCase):

    FALSE_CLAIMS = (
        "clinically validated",
        "clinically approved",
        "approved by a clinician",
        "is safe to",
        "is safe for",
        "safe to prescribe",
        "recommended dose",
        "ready for clinical use",
        "production ready",
        "validated by an expert",
        "expert-approved",
        "the assessment produced",
        "we assessed",
    )

    def test_no_document_makes_a_claim_that_is_false_today(self):
        for relative in DOCUMENTS:
            text = _text(relative).lower()
            for claim in self.FALSE_CLAIMS:
                with self.subTest(document=relative, claim=claim):
                    self.assertNotIn(claim, text)

    def test_no_document_states_a_clinical_recommendation(self):
        pattern = re.compile(
            r"(take|give|prescribe|switch to|avoid)\s+\w+\s*(mg|mcg)", re.I)
        for relative in DOCUMENTS:
            with self.subTest(document=relative):
                self.assertIsNone(pattern.search(_text(relative)))

    def test_the_documents_say_plainly_what_wp12_does_not_compute(self):
        for relative in DOCUMENTS:
            text = _text(relative).lower()
            with self.subTest(document=relative):
                self.assertTrue(
                    "attention" in text and "coverage" in text,
                    "a WP-12 document that does not name what it leaves to "
                    "WP-13 and WP-14 invites a reader to assume it does both")

    def test_the_evidence_note_says_what_it_does_not_prove(self):
        text = _text(DOCUMENTS[2])
        self.assertIn("What this does **not** prove", text)
        self.assertIn("scientifically correct", text)

    def test_the_handoff_records_a33_as_blocked(self):
        text = _text(DOCUMENTS[3])
        self.assertIn("**A33**", text)
        self.assertIn("**BLOCKED**", text)
        self.assertIn("AWAITING_EXPERT_REVIEW", text)


if __name__ == "__main__":
    unittest.main()
