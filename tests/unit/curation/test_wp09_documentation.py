# -*- coding: utf-8 -*-
"""The WP-09 document set, and the claims it is allowed to make (WP-09).

The failure that matters here is a document asserting a state nobody set.
"""

from __future__ import annotations

import io
import json
import os
import re
import unittest

from pgx.curation.fields import FIELD_DICTIONARY
from pgx.curation.protocol import PROTOCOL_REQUIREMENTS, build_protocol_document
from pgx.curation.validation import ISSUE_CODES

from tests.unit.curation._support import REPO_ROOT, source_text

DOCUMENTS = (
    os.path.join("docs", "scientific", "curation-protocol-v1.md"),
    os.path.join("docs", "scientific", "curation-field-dictionary.md"),
    os.path.join("docs", "scientific", "curation-review-checklist.md"),
    os.path.join("docs", "scientific",
                 "conflict-and-insufficiency-guidance.md"),
    os.path.join("docs", "scientific", "inter-curator-exercise.md"),
    os.path.join("docs", "migration", "wp09-manual-hint-review.md"),
    os.path.join("docs", "evidence", "wp09-protocol-validation.md"),
    os.path.join("docs", "handoffs", "wp09-handoff.md"),
)

SCHEMAS = (
    os.path.join("schemas", "curation-protocol.schema.json"),
    os.path.join("schemas", "curation-record.schema.json"),
    os.path.join("schemas", "curation-field-dictionary.schema.json"),
    os.path.join("schemas", "inter-curator-exercise.schema.json"),
    os.path.join("schemas", "inter-curator-comparison.schema.json"),
)


class TestTheDocumentSetExists(unittest.TestCase):

    def test_every_wp09_document_is_present_and_not_a_stub(self):
        for relative in DOCUMENTS:
            with self.subTest(document=relative):
                path = os.path.join(REPO_ROOT, relative)
                self.assertTrue(os.path.isfile(path), relative)
                self.assertGreater(len(source_text(relative)), 1500,
                                   "%s is a stub" % relative)

    def test_all_five_schemas_are_present_and_parse(self):
        for relative in SCHEMAS:
            with self.subTest(schema=relative):
                payload = json.loads(source_text(relative))
                self.assertIn("$schema", payload)
                self.assertTrue(payload["description"].strip())


class TestNoDocumentClaimsApproval(unittest.TestCase):

    #: A lookbehind reaches one word. "no conclusion has been curated" puts
    #: the negation three words back, so the guard scans the preceding clause
    #: instead. Anchored at the last sentence boundary so a negation in the
    #: *previous* sentence cannot excuse a claim in this one.
    NEGATION_WORDS = ("no", "not", "nothing", "never", "cannot", "must not",
                      "may not", "without", "neither", "nobody", "none",
                      "unapproved", "awaiting", "blocked")

    FORBIDDEN = (
        r"is approved", r"has been approved", r"was approved",
        r"scientifically approved", r"expert[- ]approved",
        r"clinically validated", r"ready for clinical use",
        r"safe to use", r"production ready", r"has been curated",
    )

    def _is_negated(self, body, start):
        boundary = max(body.rfind(".", 0, start), body.rfind("\n", 0, start),
                       body.rfind("|", 0, start), body.rfind(";", 0, start))
        clause = body[boundary + 1:start].lower()
        return any(re.search(r"\b%s\b" % word, clause)
                   for word in self.NEGATION_WORDS)

    def test_no_document_says_the_protocol_is_approved(self):
        for relative in DOCUMENTS:
            body = source_text(relative)
            for pattern in self.FORBIDDEN:
                with self.subTest(document=relative, pattern=pattern):
                    for found in re.finditer(r"\b" + pattern + r"\b", body,
                                             re.IGNORECASE):
                        self.assertTrue(
                            self._is_negated(body, found.start()),
                            "%s claims %r in: %s"
                            % (relative, pattern,
                               body[max(0, found.start() - 90):
                                    found.end() + 20]))

    def test_the_negation_guard_still_catches_a_real_claim(self):
        self.assertFalse(self._is_negated("The protocol is approved.", 17))
        self.assertTrue(self._is_negated("No conclusion has been curated.", 18))
        self.assertTrue(self._is_negated("The protocol is not approved.", 21))

    def test_the_guard_does_not_span_a_sentence_boundary(self):
        """A negation in the previous sentence must not excuse this one."""
        body = "Nothing is settled. The protocol is approved."
        self.assertFalse(self._is_negated(body, body.index("is approved")))

    def test_the_protocol_document_states_it_is_awaiting_review(self):
        body = source_text(DOCUMENTS[0])
        self.assertIn("AWAITING_EXPERT_REVIEW", body)
        self.assertIn("has not been scientifically approved", body.lower())

    def test_the_handoff_names_the_three_blocked_criteria(self):
        body = source_text(os.path.join("docs", "handoffs",
                                        "wp09-handoff.md"))
        for token in ("A21", "A22", "A23", "BLOCKED"):
            self.assertIn(token, body)

    def test_the_evidence_document_records_its_limitations(self):
        body = source_text(os.path.join("docs", "evidence",
                                        "wp09-protocol-validation.md"))
        self.assertIn("No scientific expert has read this protocol", body)
        self.assertIn("1,572", body)
        self.assertIn("1,644", body)


class TestTheDocumentsAgreeWithTheCode(unittest.TestCase):

    def test_the_protocol_content_hash_is_quoted_correctly(self):
        expected = build_protocol_document().content_hash()
        for relative in (DOCUMENTS[0],
                         os.path.join("docs", "evidence",
                                      "wp09-protocol-validation.md"),
                         os.path.join("docs", "handoffs",
                                      "wp09-handoff.md")):
            with self.subTest(document=relative):
                self.assertIn(expected, source_text(relative))

    def test_every_requirement_id_appears_in_the_protocol_document(self):
        body = source_text(DOCUMENTS[0])
        for item in PROTOCOL_REQUIREMENTS:
            with self.subTest(requirement=item.requirement_id):
                self.assertIn(item.requirement_id, body)

    def test_every_requirement_id_appears_in_the_checklist(self):
        body = source_text(os.path.join("docs", "scientific",
                                        "curation-review-checklist.md"))
        for item in PROTOCOL_REQUIREMENTS:
            with self.subTest(requirement=item.requirement_id):
                self.assertIn(item.requirement_id, body)

    def test_every_field_appears_in_the_field_dictionary_document(self):
        body = source_text(os.path.join("docs", "scientific",
                                        "curation-field-dictionary.md"))
        for item in FIELD_DICTIONARY:
            with self.subTest(field=item.name):
                self.assertIn("`%s`" % item.name, body)

    def test_every_cited_validation_code_is_one_the_validator_emits(self):
        body = source_text(DOCUMENTS[0])
        cited = set(re.findall(r"`(CUR_[A-Z0-9_]+)`", body))
        self.assertTrue(cited)
        self.assertEqual(cited - set(ISSUE_CODES), set())

    def test_the_proposal_count_is_quoted_correctly(self):
        for relative in (os.path.join("docs", "migration",
                                      "wp09-manual-hint-review.md"),
                         os.path.join("docs", "evidence",
                                      "wp09-protocol-validation.md"),
                         os.path.join("docs", "handoffs",
                                      "wp09-handoff.md")):
            with self.subTest(document=relative):
                self.assertIn("1,559", source_text(relative))

    def test_the_exercise_document_quotes_the_real_packet_hash(self):
        from pgx.curation.exercises import build_exercise_packet
        from tests.unit.curation._support import EVIDENCE_BUILD, PROPOSALS
        if not os.path.isdir(EVIDENCE_BUILD):
            self.skipTest("no sealed evidence build")
        packet = build_exercise_packet(EVIDENCE_BUILD, PROPOSALS)
        body = source_text(os.path.join("docs", "scientific",
                                        "inter-curator-exercise.md"))
        self.assertIn(packet.content_hash(), body)
        self.assertIn("AWAITING_HUMAN_CURATORS", body)

    def test_the_handoff_records_the_draft_raw_naming_delta(self):
        body = source_text(os.path.join("docs", "handoffs",
                                        "wp09-handoff.md"))
        self.assertIn("`RAW`", body)
        self.assertIn("`DRAFT`", body)
        self.assertIn("migration", body.lower())
