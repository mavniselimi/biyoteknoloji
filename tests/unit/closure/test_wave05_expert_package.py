# -*- coding: utf-8 -*-
"""Wave 5 B2/B3/B4 - the external expert evaluation package.

The package's whole value is that it contains no expert judgment. These tests
assert that by looking for one, in each of the four places one could get in:
the sealed catalogue, the worksheet, the response template, and the prose.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import io
import json
import os
import re
import unittest

from pgx.application.candidate_release import load_active_candidate_release
from pgx.closure.wave04_catalogue import build_catalogue
from pgx.closure.wave05_expert_package import (HUMAN_REQUIRED, QUESTION_IDS,
                                               package_manifest,
                                               reviewer_response_template,
                                               reviewer_worksheet,
                                               seal_report)
from pgx.validation.vocabulary import ValidationCaseRole

REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
PACKAGE = os.path.join(REPO, "data", "expert-package")
DOCS = os.path.join(REPO, "docs", "expert-package")
CATALOGUE = os.path.join(REPO, "data", "closure", "wave-04-catalogue",
                         "expert-reserved.json")
PINNED = _dt.datetime(2026, 9, 6, 12, 0, 0, tzinfo=_dt.timezone.utc)


def _read(*parts):
    with io.open(os.path.join(*parts), encoding="utf-8") as handle:
        return json.load(handle)


class TestTheReservedCasesCarryNoAnswer(unittest.TestCase):
    """B3. Four places an expected answer could hide; none of them has one."""

    @classmethod
    def setUpClass(cls):
        cls.committed = _read(CATALOGUE)
        cls.seal = _read(PACKAGE, "expert-reserved-seal.json")
        cls.worksheet = _read(PACKAGE, "expert-reserved-worksheet.json")

    def test_the_sealed_catalogue_records_no_expected_answer(self):
        self.assertEqual(len(self.committed), 12)
        for case in self.committed:
            with self.subTest(case=case["metadata"]["case_id"]):
                self.assertIsNone(case["expected"])

    def test_every_reserved_case_carries_a_question_instead(self):
        for case in self.committed:
            with self.subTest(case=case["metadata"]["case_id"]):
                self.assertTrue(case["question"].strip())

    def test_the_worksheet_has_no_field_an_answer_could_occupy(self):
        """Not "the field is empty" - the field does not exist."""
        for case in self.worksheet["cases"]:
            with self.subTest(case=case["case_id"]):
                self.assertNotIn("expected", case)
                self.assertNotIn("expected_answer", case)
                self.assertEqual(
                    sorted(case), ["case_id", "product_question", "request",
                                   "reviewer_answer", "title"])

    def test_every_worksheet_answer_is_human_required(self):
        for case in self.worksheet["cases"]:
            for field, value in sorted(case["reviewer_answer"].items()):
                with self.subTest(case=case["case_id"], field=field):
                    self.assertEqual(value, HUMAN_REQUIRED)

    def test_the_seal_says_so_and_measured_it(self):
        self.assertTrue(self.seal["expected_is_null_for_every_case"])
        self.assertTrue(self.seal["question_present_for_every_case"])
        self.assertFalse(self.seal["evaluated_against_the_build"])
        self.assertEqual(self.seal["reserved_case_count"], 12)

    def test_the_committed_artifact_still_hashes_to_what_the_seal_records(self):
        with io.open(CATALOGUE, "rb") as handle:
            measured = "sha256:" + hashlib.sha256(handle.read()).hexdigest()
        self.assertEqual(self.seal["catalogue_sha256"], measured)


class TestTheAccessPolicyRefusedThisProcess(unittest.TestCase):
    """B3. The refusal is the evidence, and it is on a hash-chained ledger."""

    @classmethod
    def setUpClass(cls):
        cls.seal = _read(PACKAGE, "expert-reserved-seal.json")
        cls.events = cls.seal["access_ledger"]["events"]

    def test_no_payload_read_was_allowed(self):
        self.assertEqual(self.seal["payload_reads_allowed"], 0)

    def test_all_twelve_payload_reads_were_refused_under_one_code(self):
        reads = [e for e in self.events if e["action"] == "READ_PAYLOAD"]
        self.assertEqual(len(reads), 12)
        self.assertEqual({e["allowed"] for e in reads}, {False})
        self.assertEqual({e["reason_code"] for e in reads},
                         {"EXPERT_HOLDOUT_REQUIRES_PERMITTED_WORKFLOW"})

    def test_the_audit_of_each_case_was_recorded_too(self):
        audits = [e for e in self.events if e["action"] == "AUDIT_PARTITION"]
        self.assertEqual(len(audits), 12)
        self.assertEqual({e["allowed"] for e in audits}, {True})

    def test_the_ledger_chain_is_intact(self):
        self.assertTrue(self.seal["access_chain_intact"])
        self.assertIsNone(self.seal["access_chain_first_broken_index"])

    def test_no_event_claims_an_authenticated_actor(self):
        for event in self.events:
            with self.subTest(event=event["case_id"]):
                self.assertFalse(event["actor_authenticated"])


class TestTheSealIsRegeneratedNotTrusted(unittest.TestCase):
    """Rebuild the seal from the canonical builder and compare."""

    def test_a_fresh_seal_matches_the_committed_one(self):
        pinned = load_active_candidate_release(REPO)
        cases = build_catalogue(pinned.release_public_id,
                                pinned.manifest["manifest_hash"],
                                pinned.ruleset)
        fresh = seal_report(
            cases, catalogue_path=CATALOGUE,
            catalogue_relative="data/closure/wave-04-catalogue/"
                               "expert-reserved.json",
            actor="pgx-closure-wave05", clock=lambda: PINNED)
        self.assertEqual(fresh, _read(PACKAGE, "expert-reserved-seal.json"))

    def test_the_builder_refuses_a_reserved_case_with_an_answer(self):
        """The guard that makes the whole boundary enforceable."""
        pinned = load_active_candidate_release(REPO)
        cases = build_catalogue(pinned.release_public_id,
                                pinned.manifest["manifest_hash"],
                                pinned.ruleset)
        reserved = [c for c in cases
                    if c.metadata.role is ValidationCaseRole.EXPERT_HOLDOUT]
        self.assertEqual(len(reserved), 12)
        for case in reserved:
            with self.subTest(case=case.metadata.case_id.value):
                self.assertIsNone(case.expected)


class TestTheWorksheetIsRegenerated(unittest.TestCase):

    def test_a_fresh_worksheet_matches_the_committed_one(self):
        pinned = load_active_candidate_release(REPO)
        cases = build_catalogue(pinned.release_public_id,
                                pinned.manifest["manifest_hash"],
                                pinned.ruleset)
        seal = _read(PACKAGE, "expert-reserved-seal.json")
        fresh = reviewer_worksheet(
            cases, release_public_id=pinned.release_public_id,
            release_manifest_hash=pinned.manifest["manifest_hash"],
            catalogue_sha256=seal["catalogue_sha256"])
        self.assertEqual(fresh,
                         _read(PACKAGE, "expert-reserved-worksheet.json"))

    def test_the_request_crosses_verbatim(self):
        worksheet = _read(PACKAGE, "expert-reserved-worksheet.json")
        committed = {case["metadata"]["case_id"]: case
                     for case in _read(CATALOGUE)}
        for entry in worksheet["cases"]:
            with self.subTest(case=entry["case_id"]):
                self.assertEqual(entry["request"],
                                 committed[entry["case_id"]]["request"])
                self.assertEqual(entry["product_question"],
                                 committed[entry["case_id"]]["question"])


class TestTheResponseTemplateIsATemplate(unittest.TestCase):
    """B4. It must be unusable as a completed review."""

    @classmethod
    def setUpClass(cls):
        cls.template = _read(PACKAGE, "reviewer-response-template.json")

    def test_it_says_it_is_not_a_response(self):
        self.assertEqual(self.template["state"], "TEMPLATE_NOT_A_RESPONSE")

    def test_every_identity_and_signature_field_is_human_required(self):
        for field in ("name", "professional_qualification", "affiliation",
                      "contact"):
            with self.subTest(field=field):
                self.assertEqual(self.template["reviewer"][field],
                                 HUMAN_REQUIRED)
        for field in ("signed_name", "signature_method", "date"):
            with self.subTest(field=field):
                self.assertEqual(self.template["signature"][field],
                                 HUMAN_REQUIRED)

    def test_identity_verification_is_not_overclaimed(self):
        self.assertEqual(self.template["reviewer"]["identity_verification"],
                         "NONE_PERFORMED")

    def test_it_asks_all_twelve_criticism_areas(self):
        asked = [entry["question_id"] for entry in
                 self.template["questionnaire"]]
        self.assertEqual(asked, [qid for qid, _ in QUESTION_IDS])

    def test_no_question_carries_a_pre_filled_answer(self):
        for entry in self.template["questionnaire"]:
            with self.subTest(question=entry["question_id"]):
                self.assertEqual(entry["answer"], HUMAN_REQUIRED)

    def test_it_names_what_completing_it_does_not_do(self):
        self.assertIn("not approval for clinical use",
                      self.template["not_an_approval"])

    def test_a_fresh_template_matches_the_committed_one(self):
        manifest = _read(PACKAGE, "package-manifest.json")
        frozen = _read(REPO, "data", "closure",
                       "wave-05-frozen-candidate-version.json")
        fresh = reviewer_response_template(
            release_public_id=frozen["release_public_id"],
            frozen_combined_hash=frozen["combined_hash"],
            package_manifest_hash=manifest["pre_template_manifest_hash"])
        self.assertEqual(fresh, self.template)


class TestThePackageManifest(unittest.TestCase):
    """B2. Every listed file exists and hashes to what is recorded."""

    @classmethod
    def setUpClass(cls):
        cls.manifest = _read(PACKAGE, "package-manifest.json")

    def test_nothing_is_missing(self):
        self.assertEqual(self.manifest["missing_files"], [])

    def test_all_sixteen_sections_and_the_index_are_present(self):
        listed = {row["path"] for row in self.manifest["files"]}
        self.assertIn("docs/expert-package/README.md", listed)
        for number in range(1, 17):
            prefix = "docs/expert-package/%02d-" % number
            with self.subTest(section=number):
                self.assertTrue(any(path.startswith(prefix)
                                    for path in listed))

    def test_every_recorded_hash_still_matches_the_file(self):
        for row in self.manifest["files"]:
            path = os.path.join(REPO, *row["path"].split("/"))
            with self.subTest(artifact=row["path"]):
                self.assertTrue(os.path.isfile(path))
                with io.open(path, "rb") as handle:
                    measured = ("sha256:"
                                + hashlib.sha256(handle.read()).hexdigest())
                self.assertEqual(row["sha256"], measured)

    def test_it_is_bound_to_the_frozen_version(self):
        frozen = _read(REPO, "data", "closure",
                       "wave-05-frozen-candidate-version.json")
        self.assertEqual(self.manifest["frozen_version"]["combined_hash"],
                         frozen["combined_hash"])
        self.assertEqual(self.manifest["frozen_version"]["release_public_id"],
                         frozen["release_public_id"])

    def test_it_states_that_nobody_has_reviewed_it(self):
        self.assertFalse(
            self.manifest["reviewed_by_anyone_outside_this_project"])
        self.assertEqual(self.manifest["review_state"],
                         "PENDING_EXTERNAL_EXPERT_REVIEW")

    def test_a_rebuilt_manifest_matches(self):
        frozen = _read(REPO, "data", "closure",
                       "wave-05-frozen-candidate-version.json")
        seal = _read(PACKAGE, "expert-reserved-seal.json")
        fresh = package_manifest(
            REPO, [row["path"] for row in self.manifest["files"]],
            frozen=frozen, seal=seal)
        fresh["pre_template_manifest_hash"] = \
            self.manifest["pre_template_manifest_hash"]
        self.assertEqual(fresh, self.manifest)


class TestThePackageDoesNotClaimToHaveBeenReviewed(unittest.TestCase):
    """B2. Whole claims about a named subject, not words.

    A pattern that fired on "clinically validated" anywhere would be the
    wrong pattern for documents whose entire job is to deny it - and these
    documents deny it repeatedly, in prose a line-level negation check cannot
    see, because the denial is often in the sentence above. So the pattern
    requires a subject: it matches an assertion that *this* thing was reviewed
    or approved by someone, and does not match a sentence saying it was not.
    """

    FORBIDDEN = re.compile(
        r"(this (package|release|ruleset|software|build|work) "
        r"(has been|have been|was|is) "
        r"(reviewed|approved|validated|endorsed))"
        r"|((was|were|has been|have been) "
        r"(reviewed|approved|validated|endorsed) "
        r"by (an?|the) (external |independent |named |qualified )*"
        r"(expert|reviewer|specialist|pharmacologist|pharmacist|geneticist))"
        r"|(external expert (review )?(is |has been )?"
        r"(complete|completed|received|finished))"
        r"|(WP-C12 (is |has been )?(complete|completed|closed))"
        r"|(THS[- ]?6 (is |has been )?(closed|achieved))",
        re.IGNORECASE)

    #: A sentence carrying any of these is a denial and is not scanned. The
    #: trade is deliberate and it is a false-negative trade: a claim smuggled
    #: into a sentence that also contains the word "not" would be missed. The
    #: alternative - scanning every sentence - flags this package's own
    #: disclaimers on nearly every page, and a scanner that cries wolf is
    #: deleted within a week. The claims that matter are asserted plainly.
    NEGATION = re.compile(
        r"\b(no|not|nothing|never|nobody|neither|nor|cannot|none)\b"
        r"|\bnon-", re.IGNORECASE)

    @staticmethod
    def _sentences(text):
        for chunk in re.split(r"(?<=[.!?])\s+|\n", text):
            chunk = chunk.strip()
            if chunk:
                yield chunk

    def _documents(self):
        for base, _dirs, files in os.walk(DOCS):
            for name in sorted(files):
                if name.endswith(".md"):
                    yield os.path.join(base, name)

    def _offending(self, text):
        return [sentence for sentence in self._sentences(text)
                if not self.NEGATION.search(sentence)
                and self.FORBIDDEN.search(sentence)]

    def test_no_document_claims_a_review_happened(self):
        offenders = []
        for path in self._documents():
            with io.open(path, encoding="utf-8") as handle:
                text = handle.read()
            offenders.extend("%s: %s" % (os.path.relpath(path, REPO),
                                         sentence[:90])
                             for sentence in self._offending(text))
        self.assertEqual(offenders, [])

    def test_the_index_says_nobody_has_reviewed_it(self):
        with io.open(os.path.join(DOCS, "README.md"),
                     encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("Nobody outside this project has reviewed", text)
        self.assertIn("PENDING_EXTERNAL_EXPERT_REVIEW", text)

    #: Claims that must fire, and denials that must not. Both halves matter:
    #: a scanner nobody has seen fail is not a scanner, and one that fires on
    #: the project's own disclaimers would be deleted within a week.
    MUST_FIRE = (
        "This package has been reviewed by a named expert.",
        "The ruleset was approved by an external pharmacologist.",
        "External expert review is complete.",
        "WP-C12 is complete.",
        "THS-6 is closed.",
    )
    MUST_NOT_FIRE = (
        "No external expert has reviewed any of this.",
        "- that any output is clinically validated, or validated by anyone",
        "Nothing else in this project has been approved by anybody.",
        "## What has been approved by a human, and by whom",
        'Not "clinically validated". Not "independently validated".',
        "It has not been reviewed. It is the thing to be reviewed.",
        "**Nothing in this package has been reviewed. You would be the "
        "first.**",
    )

    def test_the_scan_fires_on_a_real_claim(self):
        for line in self.MUST_FIRE:
            with self.subTest(line=line):
                self.assertEqual(len(self._offending(line)), 1)

    def test_the_scan_does_not_fire_on_a_denial(self):
        for line in self.MUST_NOT_FIRE:
            with self.subTest(line=line):
                self.assertEqual(self._offending(line), [])


class TestTheReviewerWorkflowDocuments(unittest.TestCase):
    """B4. Each required element exists, in the document that owns it."""

    REQUIRED = (
        ("00-reviewer-instructions.md",
         ("criticism", "withdraw", "not a sign-off request")),
        ("01-qualification-and-identity.md",
         ("Professional qualification", "NONE_PERFORMED")),
        ("02-conflict-of-interest.md",
         ("financial interest", "Declaration")),
        ("03-consent-and-data-handling.md",
         ("No patient data", "Withdrawal", "Consent")),
        ("04-blind-first-workflow.md",
         ("blind", "before", "expected: null")),
        ("05-review-questionnaire.md",
         ("Severity", "Correction priority", "Signature",
          "Unsafe or misleading outputs")),
        ("06-submission-procedure.md",
         ("wp_c14b_intake.py", "verbatim", "HUMAN_REQUIRED")),
    )

    @staticmethod
    def _flat(path):
        """Whitespace-normalised, because these documents are hard-wrapped
        and a needle that happens to straddle a line break is not a missing
        element."""
        with io.open(path, encoding="utf-8") as handle:
            return re.sub(r"\s+", " ", handle.read())

    def test_each_document_contains_what_it_owns(self):
        for name, needles in self.REQUIRED:
            text = self._flat(os.path.join(DOCS, "reviewer", name))
            for needle in needles:
                with self.subTest(document=name, needle=needle):
                    self.assertIn(needle, text)

    def test_the_questionnaire_asks_every_criticism_area(self):
        text = self._flat(os.path.join(DOCS, "reviewer",
                                       "05-review-questionnaire.md"))
        for qid, _ in QUESTION_IDS:
            with self.subTest(question=qid):
                self.assertIn(qid, text)

    def test_no_reviewer_account_is_invented(self):
        text = self._flat(os.path.join(DOCS, "reviewer",
                                       "00-reviewer-instructions.md"))
        self.assertIn("no reviewer account", text)
        self.assertIn("would mean inventing a reviewer", text)


if __name__ == "__main__":
    unittest.main()
