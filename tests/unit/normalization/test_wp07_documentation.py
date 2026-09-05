# -*- coding: utf-8 -*-
"""The WP-07 document set, and the claims it is allowed to make.

Documents drift from code more easily than code drifts from itself, so the
checks here are about the two things that would actually mislead a reader: a
document that claims something is approved when nothing is, and a figure that
disagrees with what the artifacts produce.
"""

from __future__ import annotations

import io
import json
import os
import unittest

from tests.unit.normalization._snapshot import REPO_ROOT

DOCUMENTS = (
    os.path.join("docs", "data", "canonicalization-policy.md"),
    os.path.join("docs", "data", "resolution-policy.md"),
    os.path.join("docs", "data", "deduplication-policy.md"),
    os.path.join("docs", "data", "data-quality-contract.md"),
    os.path.join("docs", "migration", "wp07-legacy-differences.md"),
    os.path.join("docs", "evidence", "wp07-dq-validation.md"),
    os.path.join("docs", "handoffs", "wp07-handoff.md"),
)

SCHEMAS = (
    os.path.join("schemas", "canonical-dataset-manifest.schema.json"),
    os.path.join("schemas", "data-quality-report.schema.json"),
)


def _text(relative: str) -> str:
    with io.open(os.path.join(REPO_ROOT, relative), encoding="utf-8") as handle:
        return handle.read()


class TestTheDocumentSetExists(unittest.TestCase):

    def test_every_wp07_document_is_present_and_not_a_stub(self):
        for relative in DOCUMENTS:
            with self.subTest(document=relative):
                path = os.path.join(REPO_ROOT, relative)
                self.assertTrue(os.path.isfile(path), relative)
                self.assertGreater(len(_text(relative)), 1500,
                                   "%s is a stub" % relative)

    def test_both_schemas_are_present_and_parse(self):
        for relative in SCHEMAS:
            with self.subTest(schema=relative):
                payload = json.loads(_text(relative))
                self.assertIn("$schema", payload)
                self.assertIn("description", payload)


class TestNoDocumentClaimsAnApproval(unittest.TestCase):
    """The failure mode that matters: a document asserting a state nobody set."""

    FORBIDDEN_CLAIMS = (
        "the dataset is quality checked",
        "the dataset has been approved",
        "approved by a reviewer",
        "is now published",
        "release is active",
        "scientifically validated",
        "clinically validated",
        "ready for clinical use",
    )

    def test_no_document_asserts_an_approval_that_does_not_exist(self):
        for relative in DOCUMENTS:
            text = _text(relative).casefold()
            for claim in self.FORBIDDEN_CLAIMS:
                with self.subTest(document=relative, claim=claim):
                    self.assertNotIn(claim, text)

    def test_the_handoff_names_the_two_items_that_are_not_met(self):
        text = _text(os.path.join("docs", "handoffs", "wp07-handoff.md"))
        self.assertIn("A11", text)
        self.assertIn("A24", text)
        self.assertIn("FAIL", text)
        self.assertIn("BLOCKED", text)

    def test_the_evidence_document_does_not_claim_alembic_was_run(self):
        text = _text(os.path.join("docs", "evidence", "wp07-dq-validation.md"))
        self.assertIn("This is not Alembic evidence", text)


class TestDocumentedFiguresMatchTheCode(unittest.TestCase):

    def test_the_observed_collision_count_is_stated_consistently(self):
        """1,644 observed and 1,572 documented, everywhere the pair appears."""
        for relative in (os.path.join("docs", "data",
                                      "deduplication-policy.md"),
                         os.path.join("docs", "migration",
                                      "wp07-legacy-differences.md"),
                         os.path.join("docs", "handoffs", "wp07-handoff.md")):
            text = _text(relative)
            with self.subTest(document=relative):
                self.assertIn("1,644", text)
                self.assertIn("1,572", text)

    #: Words that mark a mention of 1,572 as a claim being *reported*, rather
    #: than a measurement being asserted.
    QUALIFIERS = ("not", "none", "documented", "claim", "fail", "expectation",
                  "reproducible", "correct", "records", "1,644")

    def test_every_mention_of_1572_is_qualified_as_a_documented_claim(self):
        """1,572 is what a document says; 1,644 is what the artifacts yield.

        Checked per paragraph rather than per sentence: splitting on ``.``
        breaks on ``architecture.md`` and produces fragments that read as
        unqualified when the surrounding prose is not. A paragraph is the
        smallest unit a reader actually takes a claim from.
        """
        offences = []
        for relative in DOCUMENTS:
            for paragraph in _text(relative).split("\n\n"):
                if "1,572" not in paragraph and "1572" not in paragraph:
                    continue
                # A block quotation reproduces what another document says.
                # Quoting the claim verbatim is the honest thing to do, and it
                # would be wrong to require this project's qualifiers inside
                # someone else's sentence.
                if all(line.strip().startswith(">")
                       for line in paragraph.strip().splitlines()):
                    continue
                folded = paragraph.casefold()
                if not any(word in folded for word in self.QUALIFIERS):
                    offences.append(
                        "%s: %s" % (relative,
                                    " ".join(paragraph.split())[:90]))
        self.assertEqual(offences, [],
                         "unqualified mentions of 1,572: %s"
                         % "; ".join(offences))

    def test_the_rule_versions_named_in_the_docs_match_the_modules(self):
        from pgx.normalization.allocation import ALLOCATION_FORMAT_VERSION
        from pgx.normalization.artifacts import ARTIFACT_ROLE_MAP_VERSION
        from pgx.normalization.build import CANONICAL_BUILD_LAYOUT_VERSION
        from pgx.normalization.dedup import DEDUP_KEY_VERSION
        from pgx.normalization.extract import EXTRACTION_RULE_VERSION
        from pgx.normalization.legacy_diff import LEGACY_DIFF_VERSION
        from pgx.normalization.normalize import NORMALIZATION_RULE_VERSION
        from pgx.normalization.quality import DQ_REPORT_VERSION
        from pgx.normalization.resolver import RESOLVER_POLICY_VERSION

        handoff = _text(os.path.join("docs", "handoffs", "wp07-handoff.md"))
        for version in (ALLOCATION_FORMAT_VERSION, ARTIFACT_ROLE_MAP_VERSION,
                        CANONICAL_BUILD_LAYOUT_VERSION, DEDUP_KEY_VERSION,
                        EXTRACTION_RULE_VERSION, LEGACY_DIFF_VERSION,
                        NORMALIZATION_RULE_VERSION, DQ_REPORT_VERSION,
                        RESOLVER_POLICY_VERSION):
            with self.subTest(version=version):
                self.assertIn(version, handoff)

    def test_the_data_quality_contract_lists_every_code(self):
        """A code that exists and is undocumented is a finding nobody can read.

        Reported as a set difference rather than one failing subtest per code,
        so the message names what is missing instead of printing the document.
        """
        from pgx.normalization.quality import DataQualityIssueCode
        text = _text(os.path.join("docs", "data", "data-quality-contract.md"))
        missing = sorted(code.value for code in DataQualityIssueCode
                         if code.value not in text)
        self.assertEqual(missing, [],
                         "undocumented data quality codes: %s"
                         % ", ".join(missing))

    def test_the_readme_describes_the_canonicalization_cli(self):
        text = _text("README.md")
        self.assertIn("pgx-normalize", text)
        self.assertIn("quality-check", text)


class TestTheSchemasSayWhatTheContractSays(unittest.TestCase):

    def test_the_manifest_schema_pins_the_lifecycle_state(self):
        payload = json.loads(_text(SCHEMAS[0]))
        self.assertEqual(
            payload["properties"]["dataset_lifecycle_state"]["const"],
            "BUILDING")

    def test_the_report_schema_requires_every_stream_to_balance(self):
        payload = json.loads(_text(SCHEMAS[1]))
        item = payload["properties"]["reconciliations"]["items"]
        self.assertTrue(item["properties"]["balances"]["const"])
        self.assertEqual(item["properties"]["shortfall"]["const"], 0)

    def test_both_schemas_disclaim_coverage_language(self):
        for relative in SCHEMAS:
            payload = json.loads(_text(relative))
            with self.subTest(schema=relative):
                self.assertIn("not", payload["description"].casefold())

    def test_the_manifest_schema_forbids_unknown_top_level_fields(self):
        payload = json.loads(_text(SCHEMAS[0]))
        self.assertIs(payload["additionalProperties"], False)


if __name__ == "__main__":
    unittest.main()
