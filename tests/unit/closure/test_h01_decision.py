# -*- coding: utf-8 -*-
"""The recorded human decision on H01.

A real person's name is in this record. Almost every test here exists to
protect them from it: the decision must stay bound to the bytes they actually
read, it must not silently follow an edited evidence table, it must not claim
a kind of signature nobody produced, and it must not quietly widen into an
approval of things they did not approve.
"""

from __future__ import annotations

import csv
import io
import json
import os
import shutil
import tempfile
import unittest

from pgx.application.snapshot_schema import validate_against_schema
from pgx.closure.h01_decision import (DISPOSITIONS, PROHIBITED_MODES,
                                      REVIEWED_ARTIFACTS, REVIEWED_HASHES,
                                      REVIEWER, SOURCE_OUTCOMES,
                                      build_decision, measure_hashes,
                                      render_approval_form)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
PACKAGE = os.path.join(REPO_ROOT, "docs", "closure", "checkpoints",
                       "H01-source-policy")
RECORD = os.path.join(REPO_ROOT, "data", "closure",
                      "h01-source-policy-decision.json")
FORM = os.path.join(PACKAGE, "approval-form.md")
SCHEMA = os.path.join(REPO_ROOT, "schemas",
                      "closure-human-decision.schema.json")
REGISTRY = os.path.join(REPO_ROOT, "config", "scientific-sources.json")

EXPECTED_DECISIONS = 20
EXPECTED_APPROVED_SOURCES = 4

#: The registry as it stood when the H01 decision was recorded. Pinned so
#: that "this decision changed no source" is checkable rather than asserted.
REGISTRY_SHA256_AT_DECISION = (
    "1765ef403cf704aa1af4f5709d79c95bc559ca3079a2b6daaffcd2fd0ab9c574")


def _read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


class TestTheDecisionIsBoundToWhatWasReviewed(unittest.TestCase):

    def test_the_reviewed_digests_still_match_the_files(self):
        measured = measure_hashes(REPO_ROOT)
        for name, expected in sorted(REVIEWED_HASHES.items()):
            with self.subTest(artifact=name):
                self.assertEqual(measured[name], expected)

    def test_the_record_is_in_the_recorded_state(self):
        payload = build_decision(REPO_ROOT)
        self.assertEqual(payload["state"], "RECORDED")
        self.assertTrue(payload["hash_binding"]["reviewed_content_matches"])
        self.assertNotIn("reattestation_request", payload)

    def test_the_binding_covers_both_reviewed_artifacts(self):
        payload = build_decision(REPO_ROOT)
        reviewed = {row["artifact"].rsplit("/", 1)[-1]
                    for row in payload["hash_binding"]["rows"]
                    if row["role"] == "REVIEWED_CONTENT"}
        self.assertEqual(reviewed, set(REVIEWED_ARTIFACTS))


class TestAnEditedEvidenceTableVoidsTheApproval(unittest.TestCase):
    """The property the whole record exists for.

    If the reviewed content changes, the approval must not travel to it. This
    builds a tree whose evidence table has been altered by one byte and
    checks that the record refuses to read as approved.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="pgx-h01-drift-")
        target = os.path.join(self.root, "docs", "closure", "checkpoints",
                              "H01-source-policy")
        os.makedirs(target)
        for name in os.listdir(PACKAGE):
            shutil.copyfile(os.path.join(PACKAGE, name),
                            os.path.join(target, name))
        self.evidence = os.path.join(target, "evidence-table.csv")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _alter(self):
        with io.open(self.evidence, "a", encoding="utf-8",
                     newline="\n") as handle:
            handle.write("altered,after,the,review\n")

    def test_an_altered_evidence_table_is_not_approved(self):
        self._alter()
        payload = build_decision(self.root)
        self.assertEqual(payload["state"], "AWAITING_REATTESTATION")
        self.assertFalse(payload["hash_binding"]["reviewed_content_matches"])

    def test_the_record_names_the_old_and_the_new_digest(self):
        self._alter()
        payload = build_decision(self.root)
        changed = payload["reattestation_request"]["changed"]
        self.assertEqual(len(changed), 1)
        row = changed[0]
        self.assertEqual(row["attested_sha256"],
                         REVIEWED_HASHES["evidence-table.csv"])
        self.assertNotEqual(row["measured_sha256"], row["attested_sha256"])
        self.assertEqual(len(row["measured_sha256"]), 64)

    def test_the_approval_is_not_transferred_to_the_new_content(self):
        self._alter()
        payload = build_decision(self.root)
        self.assertIn("not", payload["reattestation_request"]
                      ["what_is_needed"].lower())
        errors = validate_against_schema(
            payload, json.loads(_read(SCHEMA)))
        self.assertEqual(list(errors), [])

    def test_the_form_says_re_attestation_rather_than_approval(self):
        self._alter()
        rendered = render_approval_form(build_decision(self.root))
        self.assertIn("AWAITING RE-ATTESTATION", rendered)

    def test_a_supporting_document_change_does_not_void_the_decision(self):
        """The decision was recorded against the two reviewed artifacts.

        Drift in a supporting document is reported, because a reader should
        know, but it does not silently revoke a decision that was never
        recorded against it.
        """
        with io.open(os.path.join(self.root, "docs", "closure", "checkpoints",
                                  "H01-source-policy", "risk-summary.md"),
                     "a", encoding="utf-8", newline="\n") as handle:
            handle.write("\nadded later\n")
        payload = build_decision(self.root)
        self.assertEqual(payload["state"], "RECORDED")
        self.assertTrue(payload["hash_binding"]["supporting_drift"])


class TestTheRecordDoesNotOverstateTheSignature(unittest.TestCase):

    def test_the_signature_is_recorded_as_a_typed_name(self):
        self.assertEqual(REVIEWER["signature_method"], "TYPED_NAME")

    def test_no_identity_verification_is_claimed(self):
        self.assertEqual(REVIEWER["identity_verification"], "NONE_PERFORMED")

    def test_the_provenance_names_the_relay(self):
        self.assertIn("relayed", REVIEWER["provenance"])

    def test_the_form_states_the_provenance_and_the_absence_of_verification(self):
        rendered = _read(FORM)
        self.assertIn("TYPED_NAME", rendered)
        self.assertIn("NONE_PERFORMED", rendered)
        self.assertIn(REVIEWER["identity_verification_note"], rendered)

    def test_the_attestation_is_preserved_verbatim(self):
        payload = build_decision(REPO_ROOT)
        attestation = payload["attestation_verbatim"]
        for fragment in ("Mehmet Yetiş", "eczacı", "APPROVED WITH CONDITIONS",
                         "M.Yetiş", "06/09/2026"):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, attestation)


class TestTheDecisionUsesTheRepositoryVocabulary(unittest.TestCase):

    def test_the_decision_enum_is_one_the_repository_already_has(self):
        from pgx.scientific.models import ReviewDecision, SourcePolicyStatus

        ReviewDecision.parse(REVIEWER["repository_decision_enum"], "decision")
        SourcePolicyStatus.parse(REVIEWER["repository_status_enum"], "status")

    def test_every_disposition_uses_a_real_status(self):
        from pgx.scientific.models import SourcePolicyStatus

        for item in DISPOSITIONS:
            with self.subTest(decision=item["decision_id"]):
                SourcePolicyStatus.parse(item["registry_status"],
                                         item["decision_id"])

    def test_every_acquisition_mode_and_reuse_dimension_is_real(self):
        from pgx.scientific.models import AcquisitionMode, ReuseDimension

        for item in SOURCE_OUTCOMES:
            for mode in (list(item["permitted_acquisition_modes"])
                         + list(item["prohibited_acquisition_modes"])):
                with self.subTest(source=item["source_key"], mode=mode):
                    AcquisitionMode.parse(mode, item["source_key"])
            for dimension in (list(item["permitted_reuse"])
                              + list(item["prohibited_reuse"])):
                with self.subTest(source=item["source_key"], dim=dimension):
                    ReuseDimension.parse(dimension, item["source_key"])

    def test_no_source_is_both_permitted_and_prohibited_a_mode(self):
        for item in SOURCE_OUTCOMES:
            with self.subTest(source=item["source_key"]):
                self.assertEqual(
                    set(item["permitted_acquisition_modes"])
                    & set(item["prohibited_acquisition_modes"]), set())
                self.assertEqual(set(item["permitted_reuse"])
                                 & set(item["prohibited_reuse"]), set())


class TestTheDecisionCoversEveryProposal(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with io.open(os.path.join(PACKAGE, "proposed-decisions.csv"),
                     encoding="utf-8") as handle:
            cls.proposals = list(csv.DictReader(handle))

    def test_every_proposed_decision_has_an_outcome(self):
        proposed = {row["decision_id"]: row["source_key"]
                    for row in self.proposals}
        recorded = {item["decision_id"]: item["source_key"]
                    for item in DISPOSITIONS}
        self.assertEqual(recorded, proposed)
        self.assertEqual(len(recorded), EXPECTED_DECISIONS)

    def test_no_source_is_approved_that_the_attestation_did_not_name(self):
        """The approved set is exactly four, and each is named in the text."""
        approved = [item["source_key"] for item in DISPOSITIONS
                    if item["registry_status"] == "APPROVED_WITH_RESTRICTIONS"]
        self.assertEqual(len(approved), EXPECTED_APPROVED_SOURCES)
        self.assertEqual(sorted(approved),
                         sorted(item["source_key"]
                                for item in SOURCE_OUTCOMES))
        attestation = build_decision(REPO_ROOT)["attestation_verbatim"].lower()
        for key in approved:
            provider = key.split(".")[0]
            with self.subTest(source=key):
                self.assertIn(provider, attestation)

    def test_the_two_api_sources_are_not_approved(self):
        for item in DISPOSITIONS:
            if item["source_key"].endswith(".api"):
                with self.subTest(source=item["source_key"]):
                    self.assertEqual(item["registry_status"], "PENDING_REVIEW")
                    self.assertEqual(item["outcome"], "DEFER_API_UNTIL_TERMS")

    def test_no_approved_source_permits_the_official_api_mode(self):
        for item in SOURCE_OUTCOMES:
            with self.subTest(source=item["source_key"]):
                self.assertNotIn("OFFICIAL_API",
                                 item["permitted_acquisition_modes"])
                self.assertIn("OFFICIAL_API",
                              item["prohibited_acquisition_modes"])

    def test_no_approved_source_permits_redistribution_or_commercial_use(self):
        for item in SOURCE_OUTCOMES:
            for dimension in ("VERBATIM_REDISTRIBUTION", "COMMERCIAL_USE",
                              "AUTOMATED_ACQUISITION", "BULK_DOWNLOAD"):
                with self.subTest(source=item["source_key"], dim=dimension):
                    self.assertNotIn(dimension, item["permitted_reuse"])
                    self.assertIn(dimension, item["prohibited_reuse"])

    def test_fda_and_titck_are_deferred_not_rejected(self):
        deferred = {item["source_key"]: item for item in DISPOSITIONS
                    if item["source_key"] in ("druglabel.fda",
                                              "druglabel.titck")}
        self.assertEqual(len(deferred), 2)
        for key, item in deferred.items():
            with self.subTest(source=key):
                self.assertEqual(item["outcome"],
                                 "DEFER_OUTSIDE_FIRST_RELEASE_SCOPE")
                self.assertEqual(item["registry_status"], "PENDING_REVIEW")


class TestTheRegistryIsUntouched(unittest.TestCase):
    """The approval records a human decision; it does not grant access."""

    def test_the_record_says_it_changed_no_source_status(self):
        payload = build_decision(REPO_ROOT)
        self.assertFalse(
            payload["registry_change"]["config_scientific_sources_changed"])
        self.assertTrue(payload["registry_change"]["gaps"])

    def test_every_registered_source_is_still_pending_review(self):
        with io.open(REGISTRY, encoding="utf-8") as handle:
            registry = json.load(handle)
        for entry in registry["sources"]:
            with self.subTest(source=entry["source_key"]):
                self.assertEqual(entry["status"], "PENDING_REVIEW")

    def test_no_approved_source_has_been_given_an_acquisition_mode(self):
        """The four the reviewer approved still carry no acquisition mode.

        Three ``internal.*`` entries already carried ``INTERNAL_DERIVATION``
        before this decision and still do; that is the registry's own
        pre-existing state and this decision did not touch it. What matters
        here is that nothing the reviewer approved has silently acquired a
        mode, which is how an approval turns into access.
        """
        approved = {item["source_key"] for item in SOURCE_OUTCOMES}
        with io.open(REGISTRY, encoding="utf-8") as handle:
            registry = json.load(handle)
        seen = 0
        for entry in registry["sources"]:
            if entry["source_key"] not in approved:
                continue
            seen += 1
            with self.subTest(source=entry["source_key"]):
                self.assertEqual(entry["acquisition_mode"], "NOT_DETERMINED")
        self.assertEqual(seen, EXPECTED_APPROVED_SOURCES)

    def test_the_registry_file_is_byte_for_byte_what_it_was(self):
        """The strongest form of "untouched": the digest is pinned.

        If a later change edits the registry, this fails and whoever changed
        it has to say why here rather than letting an approval record and a
        registry drift apart quietly.
        """
        import hashlib

        with io.open(REGISTRY, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        self.assertEqual(digest, REGISTRY_SHA256_AT_DECISION)

    def test_the_policy_validator_still_approves_nothing(self):
        import datetime as _dt

        from pgx.scientific.policy import load_registry
        from pgx.scientific.validation import approved_source_keys

        registry = load_registry(REGISTRY)
        now = _dt.datetime.now(_dt.timezone.utc)
        self.assertEqual(tuple(approved_source_keys(registry, now)), ())

    def test_every_gap_names_who_clears_it(self):
        for gap in build_decision(REPO_ROOT)["registry_change"]["gaps"]:
            with self.subTest(gap=gap["gap"]):
                self.assertTrue(gap["who_clears_it"].strip())
                self.assertTrue(gap["why_it_cannot_be_filled_now"].strip())


class TestTheBoundaryWithOtherGates(unittest.TestCase):

    def test_the_record_names_what_it_does_not_approve(self):
        payload = build_decision(REPO_ROOT)
        listed = " ".join(payload["not_approved_by_this_decision"]).lower()
        for subject in ("h02", "h03", "clinical use", "rule",
                        "dose", "redistribution"):
            with self.subTest(subject=subject):
                self.assertIn(subject, listed)

    def test_the_owner_decisions_are_preserved(self):
        payload = build_decision(REPO_ROOT)
        listed = " ".join(payload["preserved_owner_decisions"]).lower()
        for subject in ("amitriptyline", "clopidogrel", "rapid", "fda"):
            with self.subTest(subject=subject):
                self.assertIn(subject, listed)

    def test_the_other_checkpoints_are_still_undecided(self):
        from pgx.closure.checkpoints import _approval_form, CHECKPOINTS

        for checkpoint in CHECKPOINTS:
            if checkpoint["id"] == "H01-source-policy":
                continue
            path = os.path.join(REPO_ROOT, "docs", "closure", "checkpoints",
                                checkpoint["id"], "approval-form.md")
            with self.subTest(checkpoint=checkpoint["id"]):
                self.assertEqual(_read(path), _approval_form(checkpoint))


class TestTheCommittedArtifacts(unittest.TestCase):

    def test_the_committed_record_is_what_the_producer_writes(self):
        expected = json.dumps(build_decision(REPO_ROOT), indent=2,
                              sort_keys=True, ensure_ascii=False) + "\n"
        self.assertEqual(_read(RECORD), expected)

    def test_the_committed_form_is_what_the_renderer_writes(self):
        self.assertEqual(_read(FORM),
                         render_approval_form(build_decision(REPO_ROOT)))

    def test_the_record_validates_against_its_schema(self):
        errors = validate_against_schema(json.loads(_read(RECORD)),
                                         json.loads(_read(SCHEMA)))
        self.assertEqual(list(errors), [])

    def test_rebuilding_produces_identical_bytes(self):
        self.assertEqual(build_decision(REPO_ROOT), build_decision(REPO_ROOT))

    def test_the_checkpoint_index_reports_exactly_one_decision(self):
        """Counted from the table, not matched against the sentence.

        The index prose is rewritten whenever a checkpoint is added, and a
        test pinned to its wording fails for that rather than for anything
        being wrong. What matters is that exactly one row is marked decided
        and that it is H01.
        """
        index = _read(os.path.join(REPO_ROOT, "docs", "closure", "checkpoints",
                                   "README.md"))
        rows = [line for line in index.splitlines()
                if line.startswith("| [`H0")]
        decided = [line for line in rows if line.rstrip().endswith("| yes |")]
        self.assertEqual(len(decided), 1, rows)
        self.assertIn("H01-source-policy", decided[0])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
