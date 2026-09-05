# -*- coding: utf-8 -*-
"""The WP-08 document set, and the claims it is allowed to make.

Documents drift from code more easily than code drifts from itself, so the
checks here are about the three things that would actually mislead a reader: a
document claiming something is approved when nothing is, a figure that
disagrees with what the artifacts produce, and the inherited 1,572 discrepancy
quietly disappearing.
"""

from __future__ import annotations

import io
import json
import os
import re
import unittest

from tests.unit.evidence._support import (EVIDENCE_BUILD, REPO_ROOT,
                                          RealEvidenceBuildTestCase)

DOCUMENTS = (
    os.path.join("docs", "data", "evidence-record-contract.md"),
    os.path.join("docs", "data", "evidence-provenance-chain.md"),
    os.path.join("docs", "data", "evidence-import-policy.md"),
    os.path.join("docs", "migration", "wp08-legacy-curation-extraction.md"),
    os.path.join("docs", "evidence", "wp08-trace-validation.md"),
    os.path.join("docs", "handoffs", "wp08-handoff.md"),
)

SCHEMAS = (
    os.path.join("schemas", "evidence-record.schema.json"),
    os.path.join("schemas", "evidence-build-manifest.schema.json"),
    os.path.join("schemas", "draft-curation-proposal.schema.json"),
)


def _text(relative):
    with io.open(os.path.join(REPO_ROOT, relative), encoding="utf-8") as handle:
        return handle.read()


class TestTheDocumentSetExists(unittest.TestCase):

    def test_every_wp08_document_is_present_and_not_a_stub(self):
        for relative in DOCUMENTS:
            with self.subTest(document=relative):
                path = os.path.join(REPO_ROOT, relative)
                self.assertTrue(os.path.isfile(path), relative)
                self.assertGreater(len(_text(relative)), 1500,
                                   "%s is a stub" % relative)

    def test_all_three_schemas_are_present_and_parse(self):
        for relative in SCHEMAS:
            with self.subTest(schema=relative):
                payload = json.loads(_text(relative))
                self.assertIn("$schema", payload)
                self.assertIn("description", payload)
                self.assertTrue(payload["description"].strip())


class TestNoDocumentClaimsAnApproval(unittest.TestCase):
    """The failure mode that matters: a document asserting a state nobody set."""

    #: Each pattern is guarded against its own negation. "Nothing is curated"
    #: contains "is curated", and a check that flagged it would push the
    #: documents towards saying less about what has *not* happened - which is
    #: the opposite of what these documents are for.
    NEGATIONS = r"(?<!nothing )(?<!not )(?<!never )(?<!no )"

    FORBIDDEN = (
        r"is approved", r"has been approved", r"was approved",
        r"is published", r"has been published",
        r"is curated", r"has been curated",
        r"clinically validated", r"ready for clinical use",
        r"safe to use", r"production ready",
    )

    def test_no_document_says_anything_is_approved_or_publishable(self):
        for relative in DOCUMENTS:
            body = _text(relative)
            for pattern in self.FORBIDDEN:
                with self.subTest(document=relative, pattern=pattern):
                    found = re.search(self.NEGATIONS + r"\b" + pattern + r"\b",
                                      body, re.IGNORECASE)
                    self.assertIsNone(
                        found,
                        "%s claims %r in: %s"
                        % (relative, pattern,
                           body[max(0, found.start() - 60):found.end() + 20]
                           if found else ""))

    def test_the_guard_against_negations_still_catches_a_real_claim(self):
        """Otherwise the exclusion above could silently disable the check."""
        pattern = self.NEGATIONS + r"\bis approved\b"
        self.assertIsNotNone(re.search(pattern, "this dataset is approved",
                                       re.IGNORECASE))
        self.assertIsNone(re.search(pattern, "nothing is approved",
                                    re.IGNORECASE))

    def test_the_handoff_states_what_is_blocked(self):
        body = _text(os.path.join("docs", "handoffs", "wp08-handoff.md"))
        for token in ("A11", "A24", "A25", "BLOCKED", "FAIL"):
            self.assertIn(token, body)

    def test_the_evidence_document_states_the_migration_is_not_alembic(self):
        """The DDL was rendered from the migration and run on a real server.
        Calling that Alembic evidence would overstate what was executed."""
        body = _text(os.path.join("docs", "evidence",
                                  "wp08-trace-validation.md"))
        self.assertIn("not Alembic evidence", body)


class TestTheInheritedDiscrepancyIsCarriedForward(unittest.TestCase):
    """1,572 versus 1,644 must stay visible and stay unresolved.

    The tempting fixes are both wrong: changing the WP-07 deduplication key
    until it produces 1,572, or editing architecture.md until it says 1,644.
    Either would make a measurement agree with a claim by adjusting the thing
    that was not in question.
    """

    def test_the_evidence_document_carries_both_figures(self):
        body = _text(os.path.join("docs", "evidence",
                                  "wp08-trace-validation.md"))
        self.assertIn("1,572", body)
        self.assertIn("1,644", body)

    def test_it_is_reported_as_open_rather_than_resolved(self):
        body = _text(os.path.join("docs", "evidence",
                                  "wp08-trace-validation.md"))
        self.assertRegex(body, r"remains open|unresolved")
        self.assertNotRegex(body, r"1,572.{0,80}resolved\b")

    def test_the_handoff_lists_it_as_inherited_open_work(self):
        body = _text(os.path.join("docs", "handoffs", "wp08-handoff.md"))
        self.assertIn("1,572", body)
        self.assertIn("1,644", body)

    def test_architecture_md_was_not_edited_to_match(self):
        path = os.path.join(REPO_ROOT, "architecture.md")
        if not os.path.isfile(path):
            self.skipTest("architecture.md is not in this checkout")
        with io.open(path, encoding="utf-8") as handle:
            body = handle.read()
        self.assertIn("1572", body.replace(",", ""),
                      "architecture.md no longer states 1572, so the "
                      "discrepancy was edited away rather than reported")


class TestTheFiguresAgreeWithTheBuild(RealEvidenceBuildTestCase):
    """A document quoting a count the artifacts do not produce is worse than
    one quoting none, because a reader has no way to tell."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.summary = cls.manifest()["summary"]
        cls.evidence_doc = _text(os.path.join("docs", "evidence",
                                              "wp08-trace-validation.md"))
        cls.handoff = _text(os.path.join("docs", "handoffs",
                                         "wp08-handoff.md"))

    def _quoted(self, value):
        return "{:,}".format(value)

    def test_the_record_count_is_quoted_correctly(self):
        for body in (self.evidence_doc, self.handoff):
            self.assertIn(self._quoted(self.summary["record_count"]), body)

    def test_the_locator_count_is_quoted_correctly(self):
        for body in (self.evidence_doc, self.handoff):
            self.assertIn(self._quoted(self.summary["locator_count"]), body)

    def test_the_blocking_issue_count_is_quoted_correctly(self):
        for body in (self.evidence_doc, self.handoff):
            self.assertIn(self._quoted(self.summary["blocking_issue_count"]),
                          body)

    def test_the_build_content_hash_is_quoted_correctly(self):
        content_hash = self.manifest()["content_hash"]
        self.assertIn(content_hash, self.evidence_doc)
        self.assertIn(content_hash, self.handoff)

    def test_the_worked_trace_names_a_record_that_exists(self):
        """The provenance document shows one real trace. If that record left
        the build, the document is describing something that is not there."""
        body = _text(os.path.join("docs", "data",
                                  "evidence-provenance-chain.md"))
        keys = {row["natural_key"]["natural_key"]
                for row in self.rows("evidence-records.ndjson")}
        # Stops at whitespace and at the quote characters a shell example
        # wraps the key in, so a trailing "'" is not read as part of the key.
        quoted = re.findall(r"PGX-DATA-\d{8}-\d{3}\|clinpgx\.api\|[A-Z_]+\|"
                            r"[A-Za-z0-9]+\|[^\s'\"`|]+", body)
        self.assertTrue(quoted, "the provenance document shows no natural key")
        for key in set(quoted):
            with self.subTest(natural_key=key):
                self.assertIn(key, keys)

    def test_the_zero_publishable_records_claim_holds(self):
        manifest = self.manifest()
        self.assertFalse(manifest["production_eligible"])
        for body in (self.evidence_doc, self.handoff):
            self.assertIn("NOT_PUBLICATION_ELIGIBLE", body)
