# -*- coding: utf-8 -*-
"""The WP-11 rule-approval envelope validator (WP-10).

WP-10 writes the validator and nothing else. No ``ComputableRule``, no rules
package, no rule reaching ``VALIDATED``. The tests below assert both halves:
that a well-formed envelope is recognised, and that this module cannot be used
to create or promote anything.
"""

from __future__ import annotations

import ast
import datetime as _dt
import io
import os
import unittest

from pgx.curation.vocabulary import CurationRole
from pgx.curation.workflow.approval import (REQUIRED_ENVELOPE_FIELDS,
                                            RULE_APPROVAL_ENVELOPE_VERSION,
                                            RuleApprovalEnvelope,
                                            validate_rule_approval_envelope)
from pgx.curation.workflow.errors import RuleApprovalError
from tests.unit.curation._support import REPO_ROOT

ROLES = {
    "TEST-curator-1": [CurationRole.SCIENTIFIC_CURATOR],
    "TEST-reviewer-1": [CurationRole.INDEPENDENT_SCIENTIFIC_REVIEWER],
    "TEST-owner-1": [CurationRole.PROTOCOL_OWNER],
    "TEST-steward-1": [CurationRole.DATA_PROVENANCE_STEWARD],
}


def envelope(**overrides):
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
        "evidence_record_uuids": ["11111111-1111-4111-8111-111111111111"],
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


class TestAWellFormedEnvelope(unittest.TestCase):

    def test_it_validates(self):
        result = validate_rule_approval_envelope(envelope(), role_lookup=ROLES)
        self.assertTrue(result.valid, result.violations)
        self.assertEqual(result.missing, ())

    def test_validity_is_not_approval(self):
        """The advisory is part of the verdict, not a footnote. A valid
        envelope names three people; whether those people exist and said this
        is WP-23's question and this object cannot answer it."""
        result = validate_rule_approval_envelope(envelope(), role_lookup=ROLES)
        self.assertIn("not an approval", result.advisory)
        self.assertIn("WP-23", result.advisory)

    def test_it_reports_creating_and_transitioning_nothing(self):
        payload = validate_rule_approval_envelope(
            envelope(), role_lookup=ROLES).to_json()
        self.assertFalse(payload["creates_rule"])
        self.assertFalse(payload["transitions_rule"])

    def test_parsing_returns_an_envelope_object(self):
        parsed = RuleApprovalEnvelope.parse(envelope(), role_lookup=ROLES)
        self.assertTrue(parsed.validation.valid)


class TestItFailsClosed(unittest.TestCase):

    def test_an_empty_envelope_is_missing_everything(self):
        result = validate_rule_approval_envelope({})
        self.assertFalse(result.valid)
        self.assertEqual(set(result.missing), set(REQUIRED_ENVELOPE_FIELDS))

    def test_every_required_field_is_individually_required(self):
        for field in REQUIRED_ENVELOPE_FIELDS:
            with self.subTest(field=field):
                payload = envelope()
                del payload[field]
                result = validate_rule_approval_envelope(payload,
                                                         role_lookup=ROLES)
                self.assertFalse(result.valid)
                self.assertIn(field, result.missing)

    def test_every_required_field_says_why_it_is_required(self):
        for field, reason in REQUIRED_ENVELOPE_FIELDS.items():
            with self.subTest(field=field):
                self.assertGreater(len(reason.strip()), 20)

    def test_parsing_an_invalid_envelope_raises(self):
        with self.assertRaises(RuleApprovalError) as caught:
            RuleApprovalEnvelope.parse({}, role_lookup=ROLES)
        self.assertEqual(len(caught.exception.missing),
                         len(REQUIRED_ENVELOPE_FIELDS))


class TestSeparationOfDuties(unittest.TestCase):

    def test_the_author_may_not_review_their_own_rule(self):
        result = validate_rule_approval_envelope(
            envelope(reviewed_by="TEST-curator-1"), role_lookup=dict(
                ROLES, **{"TEST-curator-1": [
                    CurationRole.SCIENTIFIC_CURATOR,
                    CurationRole.INDEPENDENT_SCIENTIFIC_REVIEWER]}))
        self.assertFalse(result.valid)
        self.assertTrue(any("not an independent review" in violation
                            for violation in result.violations))

    def test_the_author_may_not_approve_their_own_rule(self):
        result = validate_rule_approval_envelope(
            envelope(approved_by="TEST-curator-1"), role_lookup=dict(
                ROLES, **{"TEST-curator-1": [
                    CurationRole.SCIENTIFIC_CURATOR,
                    CurationRole.PROTOCOL_OWNER]}))
        self.assertFalse(result.valid)
        self.assertTrue(any("self-release" in violation
                            for violation in result.violations))

    def test_each_party_must_hold_a_role_that_permits_their_act(self):
        result = validate_rule_approval_envelope(
            envelope(reviewed_by="TEST-steward-1"), role_lookup=ROLES)
        self.assertFalse(result.valid)
        self.assertTrue(any("DATA_PROVENANCE_STEWARD" in violation
                            for violation in result.violations))

    def test_role_checks_are_skipped_and_said_to_be_skipped_without_a_lookup(self):
        """No lookup is not 'no roles'. A caller that supplied none is not
        claiming the parties are unqualified."""
        result = validate_rule_approval_envelope(envelope())
        self.assertTrue(result.valid)


class TestWhatItRefuses(unittest.TestCase):

    def test_a_rule_may_only_encode_a_curated_conclusion(self):
        for status in ("RAW", "UNDER_REVIEW", "REJECTED", "DRAFT"):
            with self.subTest(status=status):
                result = validate_rule_approval_envelope(
                    envelope(curated_interpretation_status=status),
                    role_lookup=ROLES)
                self.assertFalse(result.valid)

    def test_an_unpinned_hash_is_refused(self):
        for field in ("rule_content_hash", "curation_revision_content_hash",
                      "protocol_content_hash", "evidence_build_content_hash"):
            with self.subTest(field=field):
                result = validate_rule_approval_envelope(
                    envelope(**{field: "deadbeef"}), role_lookup=ROLES)
                self.assertFalse(result.valid)

    def test_a_naive_timestamp_is_refused(self):
        result = validate_rule_approval_envelope(
            envelope(approved_at="2026-01-03T10:00:00"), role_lookup=ROLES)
        self.assertFalse(result.valid)
        self.assertTrue(any("not a point in time" in violation
                            for violation in result.violations))

    def test_an_approval_may_not_precede_its_review(self):
        result = validate_rule_approval_envelope(
            envelope(approved_at="2026-01-01T09:00:00Z"), role_lookup=ROLES)
        self.assertFalse(result.valid)

    def test_a_review_may_not_precede_the_rule(self):
        result = validate_rule_approval_envelope(
            envelope(reviewed_at="2025-01-01T09:00:00Z"), role_lookup=ROLES)
        self.assertFalse(result.valid)

    def test_duplicated_evidence_is_refused(self):
        result = validate_rule_approval_envelope(
            envelope(evidence_record_uuids=["a", "a"]), role_lookup=ROLES)
        self.assertFalse(result.valid)
        self.assertTrue(any("inflates" in violation
                            for violation in result.violations))

    def test_a_source_without_a_version_is_refused(self):
        result = validate_rule_approval_envelope(
            envelope(source_versions={"cpic.publications": ""}),
            role_lookup=ROLES)
        self.assertFalse(result.valid)

    def test_a_thin_rationale_is_refused(self):
        result = validate_rule_approval_envelope(
            envelope(approval_rationale="ok"), role_lookup=ROLES)
        self.assertFalse(result.valid)
        self.assertTrue(any("cannot be contested" in violation
                            for violation in result.violations))

    def test_a_flag_that_would_bypass_the_process_is_refused(self):
        for field in ("rule_status", "computable_rule", "auto_approve",
                      "bypass_gates"):
            with self.subTest(field=field):
                result = validate_rule_approval_envelope(
                    envelope(**{field: True}), role_lookup=ROLES)
                self.assertFalse(result.valid)

    def test_an_envelope_from_another_contract_is_refused_not_guessed_at(self):
        result = validate_rule_approval_envelope(
            envelope(envelope_version="other/2"), role_lookup=ROLES)
        self.assertFalse(result.valid)
        self.assertTrue(any("will not guess" in violation
                            for violation in result.violations))

    def test_every_fault_is_reported_not_just_the_first(self):
        result = validate_rule_approval_envelope(
            envelope(approval_rationale="ok", rule_content_hash="x",
                     curated_interpretation_status="RAW"),
            role_lookup=ROLES)
        self.assertGreaterEqual(len(result.violations), 3)


class TestValidatingAnEnvelopeCreatesNoRule(unittest.TestCase):
    """``pgx/rules`` now exists, and this class no longer asserts that it does
    not: that assertion would record only that this file predates WP-11.

    What it stood for survives unchanged and is checked here instead. Validating
    an approval envelope is reading a document, not authorising anything: the
    validator must not import the rules layer and must not name a rule type, so
    a passing envelope cannot become a rule as a side effect of being checked.
    """

    def test_the_validator_does_not_import_the_rules_layer(self):
        path = os.path.join(REPO_ROOT, "pgx", "curation", "workflow",
                            "approval.py")
        with io.open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.ImportFrom):
                module = node.module
            elif isinstance(node, ast.Import):
                module = node.names[0].name
            if module:
                with self.subTest(imported=module):
                    self.assertFalse(module == "pgx.rules"
                                     or module.startswith("pgx.rules."))

    def test_the_validator_constructs_no_rule(self):
        path = os.path.join(REPO_ROOT, "pgx", "curation", "workflow",
                            "approval.py")
        with io.open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        identifiers = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                identifiers.add(node.id)
            elif isinstance(node, ast.Attribute):
                identifiers.add(node.attr)
            elif isinstance(node, ast.ImportFrom):
                identifiers.update(alias.name for alias in node.names)
                if node.module:
                    identifiers.add(node.module)
        for forbidden in ("ComputableRule", "ComputableRuleORM",
                          "RulesetVersion", "RuleRegistry", "RuleBuilder"):
            with self.subTest(name=forbidden):
                self.assertNotIn(forbidden, identifiers)

    def test_no_rule_reaches_validated(self):
        """Read from the code, not the prose. The module's own docstring says
        it reaches nothing, and a substring search would have failed on that
        sentence while missing a real assignment."""
        path = os.path.join(REPO_ROOT, "pgx", "curation", "workflow",
                            "approval.py")
        with io.open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc:
                    docstrings.add(doc)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and \
                    isinstance(node.value, str) and \
                    node.value not in docstrings:
                with self.subTest(constant=node.value[:40]):
                    self.assertNotIn("VALIDATED", node.value)

    def test_the_validator_touches_no_database(self):
        path = os.path.join(REPO_ROOT, "pgx", "curation", "workflow",
                            "approval.py")
        with io.open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = ([alias.name for alias in node.names]
                         + ([node.module] if getattr(node, "module", None)
                            else []))
                for name in names:
                    with self.subTest(imported=name):
                        self.assertFalse(name.startswith("sqlalchemy"))
                        self.assertFalse(
                            name.startswith("pgx.infrastructure"))


if __name__ == "__main__":
    unittest.main()
