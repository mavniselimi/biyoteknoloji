# -*- coding: utf-8 -*-
"""The WP-14 document set, and the claims it is allowed to make.

The failure that matters is a document asserting something nobody established:
a handoff saying an assessment ran, an evidence note describing a test that
does not exist, an attention table that has drifted from the engine, or a
claim that Alembic executed when it could not. Every claim below is checked
against the code, the data, or the environment it describes.
"""

from __future__ import annotations

import io
import json
import os
import re
import unittest

from pgx.application.assessment_cli import REFUSED_FLAGS, build_parser
from pgx.application.assessment_gate_status import (
    BLOCKER_CODES, build_assessment_gate_status)
from pgx.domain.claims import DEFAULT_CLAIM_BOUNDARY
from pgx.domain.enums import AttentionLevel, CoverageStatus
from pgx.engine.risk import ASSESSMENT_ENGINE_CONTRACT_VERSION, engine_contract
from pgx.engine.risk_errors import FAILURE_CODES
from pgx.engine.risk_legacy import EXPECTED_DIFFERENCES
from pgx.engine.risk_models import ATTENTION_AGGREGATION_TABLE, attention_table
from tests.unit.engine._support import (ASSESSMENT_APPLICATION_MODULES,
                                        REPO_ROOT, WP14_ENGINE_MODULES, source)

ARCHITECTURE = os.path.join("docs", "architecture",
                            "wp14-deterministic-assessment.md")
MIGRATION = os.path.join("docs", "migration", "wp14-assessment-regression.md")
DETERMINISM = os.path.join("docs", "evidence", "wp14-determinism.md")
INVARIANTS = os.path.join("docs", "evidence", "wp14-safety-invariants.md")
HANDOFF = os.path.join("docs", "handoffs", "wp14-handoff.md")

DOCUMENTS = (ARCHITECTURE, MIGRATION, DETERMINISM, INVARIANTS, HANDOFF)


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
        for relative in DOCUMENTS:
            with self.subTest(document=relative):
                self.assertTrue(os.path.isfile(os.path.join(REPO_ROOT,
                                                            relative)))

    def test_every_document_carries_an_identifier_table(self):
        for relative in DOCUMENTS:
            with self.subTest(document=relative):
                self.assertSays(relative, "| Document ID |")
                self.assertSays(relative, "WP-14")

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
        for version in (ASSESSMENT_ENGINE_CONTRACT_VERSION,
                        "pgx-assessment-input/1"):
            with self.subTest(version=version):
                self.assertSays(ARCHITECTURE, version)

    def test_the_architecture_note_lists_every_wp14_module(self):
        for name in WP14_ENGINE_MODULES + ASSESSMENT_APPLICATION_MODULES:
            with self.subTest(module=name):
                self.assertSays(ARCHITECTURE, name)

    def test_the_architecture_note_lists_every_attention_level(self):
        for level in AttentionLevel:
            with self.subTest(level=level.value):
                self.assertSays(ARCHITECTURE, level.value)

    def test_the_architecture_note_lists_every_coverage_status(self):
        for status in CoverageStatus:
            with self.subTest(status=status.value):
                self.assertSays(ARCHITECTURE, status.value)

    def test_the_architecture_note_counts_the_commands_and_flags(self):
        commands = set()
        for action in build_parser()._actions:
            if getattr(action, "choices", None):
                commands.update(action.choices)
        self.assertSays(ARCHITECTURE, "%d read-only commands" % len(commands))
        self.assertSays(ARCHITECTURE, "%d refused flags" % len(REFUSED_FLAGS))

    def test_the_architecture_note_counts_the_failure_codes(self):
        self.assertSays(ARCHITECTURE,
                        "%d stable codes" % len(FAILURE_CODES))

    def test_the_architecture_note_counts_the_refused_input_fields(self):
        from pgx.application.assessment_models import REFUSED_INPUT_FIELDS
        self.assertSays(ARCHITECTURE,
                        "%d field names are refused" % len(
                            REFUSED_INPUT_FIELDS))

    def test_the_architecture_note_lists_every_refused_input_field(self):
        from pgx.application.assessment_models import REFUSED_INPUT_FIELDS
        for field in REFUSED_INPUT_FIELDS:
            with self.subTest(field=field):
                self.assertSays(ARCHITECTURE, "`%s`" % field)

    def test_the_determinism_note_matches_the_attention_table(self):
        """Generated from the table itself. If they drift, this fails."""
        for row in ATTENTION_AGGREGATION_TABLE:
            with self.subTest(case=row["case"]):
                self.assertSays(DETERMINISM, "`%s`" % row["case"])
                self.assertSays(DETERMINISM, row["when"])

    def test_the_determinism_note_matches_the_precedence(self):
        for level in attention_table()["precedence"]:
            with self.subTest(level=level):
                self.assertSays(DETERMINISM, "`%s`" % level)
        self.assertSays(DETERMINISM, "**Excluded from every maximum:** "
                                     "`NOT_ASSESSED`")

    def test_the_determinism_note_lists_every_finding_gate_check(self):
        for check in engine_contract()["finding_gate"]["checks"]:
            with self.subTest(check=check[:40]):
                self.assertSays(DETERMINISM, check)

    def test_the_determinism_note_lists_every_hash_exclusion(self):
        for excluded in engine_contract()["excluded_from_output_hash"]:
            with self.subTest(excluded=excluded):
                self.assertSays(DETERMINISM, "`%s`" % excluded)

    def test_the_evidence_note_names_the_invariants_it_claims(self):
        for invariant in ("SAFETY-INV-001", "SAFETY-INV-003",
                          "SAFETY-INV-004", "SAFETY-INV-005",
                          "SAFETY-INV-006", "SAFETY-INV-007",
                          "SAFETY-INV-008"):
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
            for match in re.findall(r"`((?:pgx|migrations)/[\w/]+\.py)`",
                                    _text(relative)):
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
            with self.subTest(entry=entry.legacy_bug_id):
                self.assertSays(MIGRATION, entry.legacy_bug_id)

    def test_the_migration_note_quotes_the_report_hash_on_disk(self):
        path = os.path.join(REPO_ROOT, "data", "migration", "wp14",
                            "assessment-regression-report.json")
        with io.open(path, encoding="utf-8") as handle:
            document = json.load(handle)
        self.assertSays(MIGRATION, document["content_hash"])

    def test_the_migration_note_reports_the_real_counts_honestly(self):
        for row in ("| Approved comparable real cases | 0 |",
                    "| Real V2 assessments executed | 0 |",
                    "| Real findings persisted | 0 |"):
            with self.subTest(row=row):
                self.assertSays(MIGRATION, row)

    def test_the_migration_note_quotes_the_csv_scan_result(self):
        from pgx.engine.risk_legacy import (
            _v2_calculation_modules, build_assessment_regression_report)
        report = build_assessment_regression_report(REPO_ROOT)
        case = [item for item in report["cases"]
                if item["case_id"] == "BEHAVIOUR-mutable-csv"][0]
        self.assertIn("0 of its %d modules" % len(_v2_calculation_modules()),
                      case["v2_explanation"])
        self.assertSays(MIGRATION,
                        "**0 of %d**" % len(_v2_calculation_modules()))

    def test_the_handoff_lists_every_blocker_the_gate_reports(self):
        status = build_assessment_gate_status(REPO_ROOT).to_json()
        self.assertEqual({item["code"] for item in status["blockers"]},
                         set(BLOCKER_CODES))
        text = _text(HANDOFF).lower()
        for marker in ("claim boundary is draft", "no release is active",
                       "no frozen ruleset", "no approved coverage manifest",
                       "awaiting_expert_review", "building", "quarantined",
                       "scientific role"):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_the_handoff_counts_match_the_gate_status(self):
        status = build_assessment_gate_status(REPO_ROOT).to_json()
        for name, value in status["assessment_state"].items():
            with self.subTest(count=name):
                self.assertEqual(value, 0)
        for row in ("| Real completed assessments | 0 |",
                    "| Real findings | 0 |",
                    "| Real executable release contexts | 0 |"):
            with self.subTest(row=row):
                self.assertSays(HANDOFF, row)

    def test_the_test_count_claimed_by_the_handoff_is_not_inflated(self):
        """A number in a handoff is a claim like any other."""
        import unittest as _unittest
        match = re.search(r"WP-14 contributes ([\d,]+) of", _text(HANDOFF))
        self.assertIsNotNone(match)
        claimed = int(match.group(1).replace(",", ""))
        loader = _unittest.TestLoader()
        counted = 0
        for module in (
                "tests.unit.application.test_assessment_input",
                "tests.unit.application.test_release_pinning",
                "tests.unit.application.test_assessment_determinism",
                "tests.unit.application.test_assessment_cli",
                "tests.unit.engine.test_risk_execution",
                "tests.unit.engine.test_risk_legacy_regression",
                "tests.unit.engine.test_wp14_boundaries",
                "tests.unit.engine.test_wp14_documentation",
                "tests.unit.infrastructure.test_assessment_persistence",
                "tests.safety.test_assessment_safety",
                "tests.contract.test_wp14_schemas",
                "tests.integration.engine.test_assessment_end_to_end"):
            counted += loader.loadTestsFromName(module).countTestCases()
        self.assertEqual(claimed, counted)


class TestNoDocumentOverclaims(DocumentCase):

    #: Phrases that would assert something nobody established. Deliberately
    #: not "is preferred" or "is suitable": SAFETY-INV-005 is named "no
    #: candidate is preferred, ranked or scored" in the safety contract, and a
    #: check failing on the invariant's own name would push the invariant out
    #: of the evidence note rather than the claim.
    FORBIDDEN_PHRASES = ("is safe", "safe to", "safe for",
                         "clinically validated", "clinically approved",
                         "recommended dose", "should be prescribed",
                         "contraindicated", "treatment recommendation",
                         "ready for clinical", "production ready",
                         "fit for clinical use", "is validated for")

    #: Words that make a claim of existence into a denial of one.
    NEGATIONS = ("no ", "not ", "none", "never", "cannot", "can not", "n't",
                 "without", "nothing", "nobody", "until", "before", "zero",
                 "refus", "blocked")

    def assertOnlyDenied(self, relative, pattern):
        text = _text(relative).lower().replace("\n", " ")
        for match in re.finditer(pattern, text):
            start = max(0, match.start() - 70)
            run_up = text[start:match.start()]
            with self.subTest(document=relative,
                              context=text[start:match.end()][-90:]):
                self.assertTrue(
                    any(word in run_up for word in self.NEGATIONS),
                    "%s asserts %r" % (relative,
                                       text[start:match.end()][-90:]))

    def test_no_document_makes_a_clinical_claim(self):
        for relative in DOCUMENTS:
            for phrase in self.FORBIDDEN_PHRASES:
                with self.subTest(document=relative, phrase=phrase):
                    self.assertDoesNotSay(relative, phrase)

    def test_no_document_claims_a_real_assessment_was_executed(self):
        for relative in DOCUMENTS:
            self.assertOnlyDenied(
                relative, r"(?:real )?assessment (?:was|has been) executed")
            self.assertOnlyDenied(relative, r"finding (?:was|has been) "
                                            r"persisted")

    def test_no_document_claims_the_claim_boundary_was_approved(self):
        for relative in DOCUMENTS:
            self.assertOnlyDenied(
                relative, r"claim boundary (?:is|has been|was) approved")

    def test_no_document_claims_alembic_or_postgresql_ran(self):
        """The environment cannot install SQLAlchemy, Alembic or a driver, so
        migration 0009 was not run. A document saying otherwise would be
        claiming evidence that does not exist.

        Checked as denials rather than as banned words: the handoff has to
        *say* "Alembic ran" in order to say it did not, and a flat ban would
        push the disclaimer out of the document rather than the claim.
        """
        for relative in DOCUMENTS:
            for pattern in (r"migration was applied", r"alembic upgrade head",
                            r"the migration ran", r"alembic ran",
                            r"trigger fired", r"verified against postgresql",
                            r"executed against a live database"):
                self.assertOnlyDenied(relative, pattern)

    def test_the_handoff_says_postgresql_was_not_available(self):
        text = _text(HANDOFF)
        self.assertIn("PostgreSQL was not available", text)
        self.assertIn("was **not run**", text)
        self.assertIn("No claim is made here that", text)

    def test_the_handoff_marks_a43_blocked(self):
        for needle in ("A43", "BLOCKED", "DRAFT / AWAITING HUMAN AND "
                                         "SCIENTIFIC REVIEW"):
            self.assertSays(HANDOFF, needle)

    def test_the_handoff_does_not_report_earlier_blocked_items_as_met(self):
        for item in ("A38", "A33", "A30", "A26"):
            with self.subTest(item=item):
                self.assertSays(HANDOFF, item)

    def test_the_handoff_states_the_scientific_code_limitation(self):
        """The reconciliation must reach WP-15 as a limitation, not as a
        detail somebody has to notice."""
        text = _text(HANDOFF)
        self.assertIn("render the absence as absence", text)
        self.assertIn("must not substitute prose of", text)
        self.assertIn("must not derive a code from the attention level", text)

    def test_the_shipped_boundary_is_still_draft(self):
        self.assertFalse(DEFAULT_CLAIM_BOUNDARY.is_approved)

    def test_no_document_says_wp15_was_started(self):
        for relative in DOCUMENTS:
            for phrase in ("wp-15 is complete", "wp-15 was implemented",
                           "reporting is implemented", "renderer is complete"):
                with self.subTest(document=relative, phrase=phrase):
                    self.assertDoesNotSay(relative, phrase)


if __name__ == "__main__":
    unittest.main()
