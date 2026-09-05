# -*- coding: utf-8 -*-
"""The protocol document, its dictionary and its validator (WP-09)."""

from __future__ import annotations

import datetime as _dt
import io
import json
import os
import unittest

from pgx.application.curation_schema import (
    validate_curation_field_dictionary, validate_curation_protocol)
from pgx.curation.errors import ApprovalError, ProtocolError
from pgx.curation.exercises import build_exercise_packet
from pgx.curation.fields import (FIELD_DICTIONARY, FieldDefinition,
                                 field_dictionary_json)
from pgx.curation.legacy_review import build_review_inventory
from pgx.curation.models import ReviewSignature
from pgx.curation.protocol import (CURATION_PROTOCOL_VERSION,
                                   PROTOCOL_REQUIREMENTS, ApprovalRecord,
                                   ProtocolDocument, build_protocol_document)
from pgx.curation.validation import (ISSUE_CODES, validate_protocol)
from pgx.curation.vocabulary import (CurationRole, ProtocolStatus,
                                     vocabulary_registry)

from tests.unit.curation._support import (EVIDENCE_BUILD,
                                          FIELD_DICTIONARY_JSON, NOW,
                                          PROPOSALS, PROTOCOL_JSON, signature)


class TestTheProtocolIsVersionedAndComplete(unittest.TestCase):

    def setUp(self):
        self.document = build_protocol_document()

    def test_it_declares_a_version(self):
        self.assertEqual(self.document.protocol_version,
                         CURATION_PROTOCOL_VERSION)

    def test_requirement_ids_are_unique(self):
        ids = [item.requirement_id for item in PROTOCOL_REQUIREMENTS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_requirement_id_has_the_stable_shape(self):
        for item in PROTOCOL_REQUIREMENTS:
            with self.subTest(requirement=item.requirement_id):
                self.assertRegex(item.requirement_id, r"^CUR-PROT-\d{3}$")

    def test_every_requirement_maps_to_code_test_and_checklist(self):
        for item in PROTOCOL_REQUIREMENTS:
            with self.subTest(requirement=item.requirement_id):
                self.assertTrue(item.implementation.strip())
                self.assertTrue(item.test_reference.strip())
                self.assertTrue(item.checklist_item.strip())
                self.assertIn(item.validation_code, ISSUE_CODES)

    def test_a_duplicate_requirement_id_is_refused(self):
        with self.assertRaises(ProtocolError):
            ProtocolDocument(
                protocol_version="v", status=ProtocolStatus.DRAFT,
                requirements=(PROTOCOL_REQUIREMENTS[0],
                              PROTOCOL_REQUIREMENTS[0]),
                roles=self.document.roles, case_rules={"a": "b"},
                vocabularies=vocabulary_registry(),
                field_dictionary_version="d")

    def test_the_content_hash_is_deterministic(self):
        self.assertEqual(build_protocol_document().content_hash(),
                         self.document.content_hash())

    def test_the_content_hash_excludes_operational_timestamps(self):
        stamped = build_protocol_document()
        object.__setattr__(stamped, "generated_at", NOW)
        self.assertEqual(stamped.content_hash(), self.document.content_hash())

    def test_published_vocabularies_match_the_code(self):
        self.assertEqual(dict(self.document.vocabularies),
                         dict(vocabulary_registry()))


class TestFieldDictionaryIsComplete(unittest.TestCase):

    def test_every_field_states_an_owner(self):
        for item in FIELD_DICTIONARY:
            with self.subTest(field=item.name):
                self.assertIn(str(item.owner),
                              ("SOURCE", "CURATOR", "SYSTEM"))

    def test_every_field_states_what_null_means(self):
        for item in FIELD_DICTIONARY:
            with self.subTest(field=item.name):
                self.assertGreater(len(item.null_meaning.strip()), 10)

    def test_every_field_names_a_prohibited_interpretation(self):
        for item in FIELD_DICTIONARY:
            with self.subTest(field=item.name):
                self.assertTrue(item.prohibited_interpretations)

    def test_a_field_without_a_prohibited_interpretation_is_refused(self):
        with self.assertRaises(ProtocolError):
            FieldDefinition(
                name="x", owner="CURATOR", type_name="string", required=True,
                allowed_values=None, null_meaning="means nothing at all here",
                validation="none", provenance_requirement="none",
                human_judgement_required=False, may_enter_rule=False,
                prohibited_interpretations=())

    def test_a_field_without_null_semantics_is_refused(self):
        with self.assertRaises(ProtocolError):
            FieldDefinition(
                name="x", owner="CURATOR", type_name="string", required=True,
                allowed_values=None, null_meaning="  ",
                validation="none", provenance_requirement="none",
                human_judgement_required=False, may_enter_rule=False,
                prohibited_interpretations=("not a thing",))

    def test_an_invalid_owner_is_refused(self):
        with self.assertRaises(ProtocolError):
            FieldDefinition(
                name="x", owner="EVERYONE", type_name="string", required=True,
                allowed_values=None, null_meaning="means nothing at all here",
                validation="none", provenance_requirement="none",
                human_judgement_required=False, may_enter_rule=False,
                prohibited_interpretations=("not a thing",))

    def test_no_field_is_owned_by_both_source_and_curator(self):
        source = {item.name for item in FIELD_DICTIONARY
                  if str(item.owner) == "SOURCE"}
        curator = {item.name for item in FIELD_DICTIONARY
                   if str(item.owner) == "CURATOR"}
        self.assertEqual(source & curator, set())


class TestApprovalMetadataIsGenuine(unittest.TestCase):

    def _approval(self, **overrides):
        document = build_protocol_document()
        payload = dict(
            protocol_version=document.protocol_version,
            protocol_content_hash=document.content_hash(),
            protocol_owner="Dr Ayse Yilmaz",
            approver=signature(
                "Prof Elif Sahin",
                CurationRole.INDEPENDENT_SCIENTIFIC_REVIEWER,
                "Read the protocol in full and accept its requirements."),
            approval_evidence_reference="minutes/2026-09-02-review.pdf",
            effective_date=_dt.date(2026, 9, 2),
            review_due_date=_dt.date(2027, 9, 2))
        payload.update(overrides)
        return ApprovalRecord(**payload)

    def test_a_complete_approval_is_expressible(self):
        self.assertTrue(self._approval().approver.person)

    def test_a_placeholder_approver_is_refused(self):
        for name in ("TEST_REVIEWER", "TODO", "team", "scientific advisor",
                     "anonymous", "system"):
            with self.subTest(name=name):
                with self.assertRaises(Exception):
                    self._approval(approver=ReviewSignature(
                        person=name,
                        role=CurationRole.INDEPENDENT_SCIENTIFIC_REVIEWER,
                        at=NOW, rationale="Approved the protocol document."))

    def test_a_non_scientific_approver_is_refused(self):
        with self.assertRaises(ApprovalError):
            self._approval(approver=signature(
                "Ali Veli", CurationRole.ENGINEERING_OBSERVER,
                "Confirmed the tooling produces the artifacts."))

    def test_the_owner_cannot_approve_their_own_protocol(self):
        with self.assertRaises(ApprovalError):
            self._approval(protocol_owner="Prof Elif Sahin")

    def test_an_approval_with_no_expiry_is_refused(self):
        with self.assertRaises(ApprovalError):
            self._approval(review_due_date=_dt.date(2026, 9, 2))

    def test_an_approval_naming_a_different_content_hash_is_refused(self):
        with self.assertRaises(ApprovalError):
            build_protocol_document(
                status=ProtocolStatus.APPROVED,
                approval=self._approval(
                    protocol_content_hash="sha256:" + "00" * 32))

    def test_approved_without_an_approval_record_is_refused(self):
        with self.assertRaises(ApprovalError):
            build_protocol_document(status=ProtocolStatus.APPROVED)

    def test_the_checked_in_protocol_is_not_approved(self):
        document = build_protocol_document()
        self.assertEqual(document.status,
                         ProtocolStatus.AWAITING_EXPERT_REVIEW)
        self.assertIsNone(document.approval)
        self.assertFalse(document.is_expert_approved)


class TestCompletenessAndApprovalAreSeparate(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.document = build_protocol_document()
        cls.inventory = (build_review_inventory(PROPOSALS)
                         if os.path.isfile(PROPOSALS) else None)
        cls.packet = (build_exercise_packet(EVIDENCE_BUILD, PROPOSALS)
                      if os.path.isdir(EVIDENCE_BUILD) else None)
        cls.uuids = None
        if os.path.isdir(EVIDENCE_BUILD):
            with io.open(os.path.join(EVIDENCE_BUILD,
                                      "evidence-records.ndjson"),
                         encoding="utf-8") as handle:
                cls.uuids = [json.loads(line)["record_uuid"]
                             for line in handle if line.strip()]

    def _report(self, **overrides):
        payload = dict(document=self.document, inventory=self.inventory,
                       packet=self.packet,
                       evidence_record_uuids=self.uuids,
                       expected_proposal_count=1559)
        payload.update(overrides)
        return validate_protocol(**payload)

    def test_the_protocol_is_technically_complete(self):
        self.assertEqual(self._report().technical_completeness, "PASS")

    def test_expert_approval_is_blocked(self):
        self.assertEqual(self._report().expert_approval, "BLOCKED")

    def test_the_two_verdicts_are_not_one_boolean(self):
        report = self._report()
        payload = report.to_json()
        self.assertIn("technical_completeness", payload)
        self.assertIn("expert_approval", payload)
        self.assertNotEqual(payload["technical_completeness"],
                            payload["expert_approval"])

    def test_missing_approval_does_not_fail_technical_completeness(self):
        report = self._report()
        codes = {item.code for item in report.issues}
        self.assertIn("CUR_APPROVAL_ABSENT", codes)
        self.assertEqual(report.technical_completeness, "PASS")

    def test_the_report_is_deterministic(self):
        self.assertEqual(self._report().to_json(), self._report().to_json())

    def test_a_missing_artifact_is_blocking(self):
        report = self._report(artifact_paths=("/nonexistent/protocol.json",))
        self.assertEqual(report.technical_completeness, "FAIL")

    def test_a_wrong_proposal_count_is_blocking(self):
        if self.inventory is None:
            self.skipTest("no proposals in this checkout")
        report = self._report(expected_proposal_count=1)
        self.assertEqual(report.technical_completeness, "FAIL")

    def test_absent_inputs_are_reported_rather_than_passed_silently(self):
        report = validate_protocol(self.document)
        codes = {item.code for item in report.issues}
        self.assertIn("CUR_LEGACY_PROPOSAL_MISSING", codes)
        self.assertIn("CUR_EXERCISE_EVIDENCE_MISSING", codes)

    def test_every_check_is_named_in_the_report(self):
        self.assertGreaterEqual(len(self._report().checks_run), 15)

    def test_an_undeclared_issue_code_cannot_be_raised(self):
        from pgx.curation.validation import ValidationIssue
        with self.assertRaises(KeyError):
            ValidationIssue(code="CUR_MADE_UP", severity="BLOCKING",
                            subject="x", detail="y")


class TestTheCheckedInArtifacts(unittest.TestCase):

    def _read(self, path):
        with io.open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def test_the_protocol_artifact_matches_the_code(self):
        if not os.path.isfile(PROTOCOL_JSON):
            self.skipTest("no protocol artifact in this checkout")
        payload = self._read(PROTOCOL_JSON)
        self.assertEqual(payload["content_hash"],
                         build_protocol_document().content_hash())

    def test_the_protocol_artifact_validates(self):
        if not os.path.isfile(PROTOCOL_JSON):
            self.skipTest("no protocol artifact in this checkout")
        self.assertEqual(
            validate_curation_protocol(self._read(PROTOCOL_JSON)), ())

    def test_the_field_dictionary_artifact_validates(self):
        if not os.path.isfile(FIELD_DICTIONARY_JSON):
            self.skipTest("no field dictionary in this checkout")
        self.assertEqual(validate_curation_field_dictionary(
            self._read(FIELD_DICTIONARY_JSON)), ())

    def test_the_field_dictionary_artifact_matches_the_code(self):
        if not os.path.isfile(FIELD_DICTIONARY_JSON):
            self.skipTest("no field dictionary in this checkout")
        self.assertEqual(self._read(FIELD_DICTIONARY_JSON),
                         field_dictionary_json())

    def test_the_artifact_declares_its_vocabularies_are_draft(self):
        if not os.path.isfile(PROTOCOL_JSON):
            self.skipTest("no protocol artifact in this checkout")
        self.assertEqual(self._read(PROTOCOL_JSON)["vocabulary_status"],
                         "DRAFT_AWAITING_EXPERT_REVIEW")

    def test_an_artifact_claiming_approval_fails_its_schema(self):
        if not os.path.isfile(PROTOCOL_JSON):
            self.skipTest("no protocol artifact in this checkout")
        payload = self._read(PROTOCOL_JSON)
        payload["vocabulary_status"] = "APPROVED"
        self.assertTrue(validate_curation_protocol(payload))

    def test_an_artifact_naming_an_engineering_approver_fails_its_schema(self):
        if not os.path.isfile(PROTOCOL_JSON):
            self.skipTest("no protocol artifact in this checkout")
        payload = self._read(PROTOCOL_JSON)
        payload["approval"] = {
            "protocol_version": payload["protocol_version"],
            "protocol_content_hash": payload["content_hash"],
            "protocol_owner": "Dr Ayse Yilmaz",
            "approver": {"person": "Ali Veli",
                         "role": "ENGINEERING_OBSERVER",
                         "at": "2026-09-02T12:00:00Z",
                         "rationale": "Confirmed the tooling runs correctly."},
            "approval_evidence_reference": "x",
            "effective_date": "2026-09-02", "review_due_date": "2027-09-02"}
        self.assertTrue(validate_curation_protocol(payload))
