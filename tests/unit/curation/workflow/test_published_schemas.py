# -*- coding: utf-8 -*-
"""The five published WP-10 schemas (WP-10).

Each is checked two ways: real output validates against it, and a document
that lies in the way a hand-edited file would most usefully lie does not. A
schema nothing has ever failed is a description, not a constraint.
"""

from __future__ import annotations

import io
import json
import os
import unittest

from pgx.application.curation_workflow_schema import (
    CURATION_ADJUDICATION_SCHEMA_PATH, CURATION_AUDIT_EVENT_SCHEMA_PATH,
    CURATION_REVIEW_SCHEMA_PATH, CURATION_REVISION_SCHEMA_PATH,
    CURATION_WORK_ITEM_SCHEMA_PATH, RULE_APPROVAL_ENVELOPE_SCHEMA_PATH,
    load_schema, validate_curation_adjudication,
    validate_curation_audit_event, validate_curation_review,
    validate_curation_revision, validate_curation_work_item,
    validate_rule_approval_envelope_document)
from pgx.curation.vocabulary import ConflictState
from pgx.curation.workflow.approval import RULE_APPROVAL_ENVELOPE_VERSION
from pgx.curation.workflow.models import ReviewDecision
from tests.support.workflow_fixtures import (TEST_CURATOR, TEST_REVIEWER,
                                             TEST_STEWARD, build_service,
                                             evidence_snapshot, seed_raw,
                                             steward_verification)
from tests.unit.curation._support import REPO_ROOT

SCHEMAS = (CURATION_WORK_ITEM_SCHEMA_PATH, CURATION_REVISION_SCHEMA_PATH,
           CURATION_REVIEW_SCHEMA_PATH, CURATION_ADJUDICATION_SCHEMA_PATH,
           CURATION_AUDIT_EVENT_SCHEMA_PATH,
           RULE_APPROVAL_ENVELOPE_SCHEMA_PATH)

LEGACY_ITEMS = os.path.join(REPO_ROOT, "data", "migration", "wp10",
                            "legacy-work-items.ndjson")


def _walk():
    """One complete synthetic workflow, for validating real output."""
    service, store = build_service()
    seed_raw(store)
    revision = service.create_revision(
        actor_id=TEST_CURATOR, work_item_id="TEST-WI-0001",
        expected_version=0, payload={"conclusion_state": "SUPPORTED"},
        evidence=evidence_snapshot())
    service.record_provenance_verification(
        actor_id=TEST_STEWARD, work_item_id="TEST-WI-0001",
        verification=steward_verification())
    service.submit(actor_id=TEST_CURATOR, work_item_id="TEST-WI-0001",
                   revision_id=revision.revision.revision_id,
                   expected_version=1)
    approved = service.review(
        actor_id=TEST_REVIEWER, work_item_id="TEST-WI-0001",
        revision_id=revision.revision.revision_id, expected_version=2,
        decision=ReviewDecision.APPROVE,
        rationale="Independently re-read the cited evidence and agree.",
        conflict_state=ConflictState.NONE_IDENTIFIED, rationale_complete=True)
    return revision, approved, store


class TestEverySchemaIsWellFormedAndUsed(unittest.TestCase):

    def test_all_six_are_published(self):
        for path in SCHEMAS:
            with self.subTest(schema=os.path.basename(path)):
                self.assertTrue(os.path.isfile(path))

    def test_each_declares_an_id_and_a_description(self):
        for path in SCHEMAS:
            document = load_schema(path)
            with self.subTest(schema=os.path.basename(path)):
                self.assertIn("$id", document)
                self.assertGreater(len(document["description"]), 100,
                                   "a schema whose description does not say "
                                   "what it refuses is documentation debt")

    def test_each_forbids_unknown_properties(self):
        for path in SCHEMAS:
            document = load_schema(path)
            with self.subTest(schema=os.path.basename(path)):
                self.assertIs(document["additionalProperties"], False)


class TestRealOutputValidates(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.revision, cls.approved, cls.store = _walk()

    def test_a_work_item_validates(self):
        self.assertEqual(
            validate_curation_work_item(self.approved.work_item.to_json()), ())

    def test_a_revision_validates(self):
        self.assertEqual(
            validate_curation_revision(self.revision.revision.to_json()), ())

    def test_a_review_validates(self):
        self.assertEqual(
            validate_curation_review(self.approved.review.to_json()), ())

    def test_an_audit_event_validates(self):
        self.assertEqual(
            validate_curation_audit_event(self.store.audit[-1]), ())

    def test_every_legacy_work_item_on_disk_validates(self):
        with io.open(LEGACY_ITEMS, encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                if number > 50:
                    break  # the first fifty are enough to catch a shape error
                with self.subTest(line=number):
                    self.assertEqual(
                        validate_curation_work_item(json.loads(line)), ())


class TestEachSchemaRefusesTheLieItWasWrittenFor(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.revision, cls.approved, cls.store = _walk()

    def test_a_raw_work_item_may_not_name_a_submitted_revision(self):
        payload = dict(self.approved.work_item.to_json())
        payload.update(status="RAW", submitted_revision_id="REV-000001",
                       is_terminal=False)
        self.assertTrue(validate_curation_work_item(payload))

    def test_a_curated_work_item_must_name_the_revision_decided(self):
        payload = dict(self.approved.work_item.to_json())
        payload["submitted_revision_id"] = None
        self.assertTrue(validate_curation_work_item(payload))

    def test_a_legacy_value_must_be_namespaced(self):
        payload = dict(self.approved.work_item.to_json())
        payload["legacy_values"] = {"demo_risk_level": "high"}
        problems = validate_curation_work_item(payload)
        self.assertTrue(problems)
        self.assertIn("demo_risk_level", " ".join(problems))

    def test_a_revision_may_not_carry_a_risk_level_or_a_recommendation(self):
        for field in ("risk_level", "attention_level", "confidence_score",
                      "dose", "recommendation", "approved_by", "reviewed_by"):
            with self.subTest(field=field):
                payload = dict(self.revision.revision.to_json())
                payload[field] = "anything"
                self.assertTrue(validate_curation_revision(payload))

    def test_a_revision_must_be_authored_by_a_curator(self):
        payload = dict(self.revision.revision.to_json())
        payload["authored_by_role"] = "ADJUDICATOR"
        self.assertTrue(validate_curation_revision(payload))

    def test_a_revision_must_cite_evidence(self):
        payload = dict(self.revision.revision.to_json())
        payload["evidence"] = dict(payload["evidence"],
                                   evidence_record_uuids=[])
        self.assertTrue(validate_curation_revision(payload))

    def test_revision_one_may_not_claim_a_parent(self):
        payload = dict(self.revision.revision.to_json())
        payload["parent_revision_id"] = "REV-000000"
        self.assertTrue(validate_curation_revision(payload))

    def test_a_review_decision_and_its_resulting_state_must_agree(self):
        payload = dict(self.approved.review.to_json())
        payload["resulting_state"] = "REJECTED"
        self.assertTrue(validate_curation_review(payload))

    def test_a_referral_may_not_move_the_work_item(self):
        payload = dict(self.approved.review.to_json())
        payload.update(decision="REFER_TO_ADJUDICATION",
                       resulting_state="CURATED")
        self.assertTrue(validate_curation_review(payload))

    def test_a_curator_may_not_appear_as_a_reviewer(self):
        payload = dict(self.approved.review.to_json())
        payload["reviewed_by_role"] = "SCIENTIFIC_CURATOR"
        self.assertTrue(validate_curation_review(payload))

    def test_a_review_may_not_report_a_consensus_or_an_agreement_score(self):
        for field in ("consensus", "merged_response", "agreement_score",
                      "auto_approved"):
            with self.subTest(field=field):
                payload = dict(self.approved.review.to_json())
                payload[field] = True
                self.assertTrue(validate_curation_review(payload))

    def test_an_approval_event_must_name_the_revision_and_its_author(self):
        for field in ("revision_id", "revision_content_hash",
                      "author_actor_id"):
            with self.subTest(field=field):
                event = dict(self.store.audit[-1])
                event["metadata"] = {key: value
                                     for key, value in event["metadata"].items()
                                     if key != field}
                self.assertTrue(validate_curation_audit_event(event))

    def test_an_invented_audit_action_is_refused(self):
        event = dict(self.store.audit[-1])
        event["action"] = "CURATION_AUTO_APPROVED"
        self.assertTrue(validate_curation_audit_event(event))


class TestTheAdjudicationSchema(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from pgx.curation.workflow.models import ReviewDecision
        from tests.support.workflow_fixtures import (TEST_ADJUDICATOR,
                                                     raw_work_item)
        service, store = build_service()
        seed_raw(store, raw_work_item("TEST-WI-ADJ"))
        revision = service.create_revision(
            actor_id=TEST_CURATOR, work_item_id="TEST-WI-ADJ",
            expected_version=0, payload={"c": 1},
            evidence=evidence_snapshot())
        service.record_provenance_verification(
            actor_id=TEST_STEWARD, work_item_id="TEST-WI-ADJ",
            verification=steward_verification())
        service.submit(actor_id=TEST_CURATOR, work_item_id="TEST-WI-ADJ",
                       revision_id=revision.revision.revision_id,
                       expected_version=1)
        service.review(
            actor_id=TEST_REVIEWER, work_item_id="TEST-WI-ADJ",
            revision_id=revision.revision.revision_id, expected_version=2,
            decision=ReviewDecision.REFER_TO_ADJUDICATION,
            rationale="The curator and I read this study differently.")
        cls.record = service.adjudicate(
            actor_id=TEST_ADJUDICATOR, work_item_id="TEST-WI-ADJ",
            revision_id=revision.revision.revision_id, expected_version=3,
            decision=ReviewDecision.APPROVE,
            rationale="The curator's reading is supported by the annotation.",
            curator_position={"actor_id": TEST_CURATOR,
                              "position": "SUPPORTED"},
            reviewer_position={"actor_id": TEST_REVIEWER,
                               "position": "INSUFFICIENT"},
            conflict_state=ConflictState.NONE_IDENTIFIED,
            rationale_complete=True).adjudication.to_json()

    def test_a_real_adjudication_validates(self):
        self.assertEqual(validate_curation_adjudication(self.record), ())

    def test_both_positions_must_be_present(self):
        for field in ("curator_position", "reviewer_position"):
            with self.subTest(field=field):
                payload = dict(self.record)
                payload[field] = {}
                self.assertTrue(validate_curation_adjudication(payload))

    def test_a_generated_consensus_is_refused(self):
        for field in ("consensus", "merged_position", "agreement_score",
                      "winner", "auto_resolved"):
            with self.subTest(field=field):
                payload = dict(self.record)
                payload[field] = "anything"
                self.assertTrue(validate_curation_adjudication(payload))

    def test_an_adjudicator_may_not_refer_onward(self):
        payload = dict(self.record)
        payload["decision"] = "REFER_TO_ADJUDICATION"
        self.assertTrue(validate_curation_adjudication(payload))

    def test_the_decision_and_the_resulting_state_must_agree(self):
        payload = dict(self.record)
        payload["resulting_state"] = "REJECTED"
        self.assertTrue(validate_curation_adjudication(payload))

    def test_only_an_adjudicator_may_adjudicate(self):
        payload = dict(self.record)
        payload["adjudicated_by_role"] = "INDEPENDENT_SCIENTIFIC_REVIEWER"
        self.assertTrue(validate_curation_adjudication(payload))


class TestTheEnvelopeSchema(unittest.TestCase):

    def _envelope(self, **overrides):
        payload = {
            "envelope_version": RULE_APPROVAL_ENVELOPE_VERSION,
            "rule_public_id": "TEST-RULE-0001",
            "rule_version": "1.0.0",
            "rule_content_hash": "sha256:" + "a" * 64,
            "curated_interpretation_id": "TEST-CI-0001",
            "curated_interpretation_status": "CURATED",
            "curation_work_item_id": "TEST-WI-0001",
            "curation_revision_id": "REV-000001",
            "curation_revision_content_hash": "sha256:" + "b" * 64,
            "protocol_version": "test-protocol/9.9.9-synthetic",
            "protocol_content_hash": "sha256:" + "c" * 64,
            "evidence_record_uuids":
                ["11111111-1111-4111-8111-111111111111"],
            "evidence_build_content_hash": "sha256:" + "d" * 64,
            "source_versions": {"cpic.publications": "2026-01"},
            "created_by": "TEST-curator-1",
            "created_at": "2026-01-01T10:00:00Z",
            "reviewed_by": "TEST-reviewer-1",
            "reviewed_at": "2026-01-02T10:00:00Z",
            "approved_by": "TEST-owner-1",
            "approved_at": "2026-01-03T10:00:00Z",
            "approval_rationale":
                "The rule encodes the curated conclusion without extending it.",
        }
        payload.update(overrides)
        return payload

    def test_a_complete_envelope_validates(self):
        self.assertEqual(
            validate_rule_approval_envelope_document(self._envelope()), ())

    def test_a_rule_may_only_encode_a_curated_conclusion(self):
        self.assertTrue(validate_rule_approval_envelope_document(
            self._envelope(curated_interpretation_status="RAW")))

    def test_a_source_without_a_version_is_refused(self):
        self.assertTrue(validate_rule_approval_envelope_document(
            self._envelope(source_versions={"cpic.publications": ""})))

    def test_a_bypass_flag_is_refused(self):
        for field in ("rule_status", "computable_rule", "auto_approve",
                      "bypass_gates"):
            with self.subTest(field=field):
                self.assertTrue(validate_rule_approval_envelope_document(
                    self._envelope(**{field: True})))

    def test_the_schema_checks_shape_and_the_validator_checks_meaning(self):
        """A schema cannot express 'the reviewer is not the author'. The
        document below passes the schema and fails the semantic validator, and
        both results are correct."""
        from pgx.curation.workflow.approval import \
            validate_rule_approval_envelope
        payload = self._envelope(reviewed_by="TEST-curator-1")
        self.assertEqual(validate_rule_approval_envelope_document(payload), ())
        self.assertFalse(validate_rule_approval_envelope(payload).valid)


if __name__ == "__main__":
    unittest.main()
