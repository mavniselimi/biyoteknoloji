# -*- coding: utf-8 -*-
"""The committed WP-23 artifacts and the gate they report (WP-23).

The assertions worth reading are the ones separating **implemented**,
**configured** and **operating**. This work package's characteristic failure
is a document that reports the first while a reader takes it for the third, so
the gate status carries all three as separate fields and this file checks they
disagree in the direction they actually do.
"""

from __future__ import annotations

import io
import json
import os
import unittest

from pgx.application.security_schema import (build_schemas,
                                             validate_audit_verification,
                                             validate_rate_limit_policy,
                                             validate_rbac_registry,
                                             validate_session_projection,
                                             validate_user_projection,
                                             validate_wp23_gate_status)
from pgx.application.security_schema import FORBIDDEN_PROPERTY_NAMES
from pgx.security.artifacts import (DETERMINISTIC_ARTIFACT_PATHS,
                                    build_artifacts,
                                    build_audit_action_registry)
from pgx.security.gate_status import (MODULE_MARKERS, build_wp23_gate_status,
                                      security_gate_state,
                                      security_module_markers)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                         "..", "..", ".."))


def _read(relative):
    with io.open(os.path.join(REPO_ROOT, *relative.split("/")),
                 encoding="utf-8") as handle:
        return handle.read()


class TestTheArtifactsAreCommittedAndCurrent(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.built = build_artifacts(REPO_ROOT)

    def test_every_deterministic_artifact_matches_a_fresh_build(self):
        for relative in DETERMINISTIC_ARTIFACT_PATHS:
            with self.subTest(artifact=relative):
                self.assertEqual(_read(relative), self.built[relative])

    def test_every_schema_is_committed_and_current(self):
        for relative, _schema in build_schemas().items():
            with self.subTest(schema=relative):
                self.assertEqual(_read(relative), self.built[relative])

    def test_the_environment_measuring_artifacts_are_excluded(self):
        """The scan walks the filesystem and the gate reads the environment,
        so two builds on different machines legitimately differ."""
        for relative in ("data/security/wp23-secret-scan-report.json",
                         "data/security/wp23-real-gate-status.json"):
            with self.subTest(artifact=relative):
                self.assertNotIn(relative, DETERMINISTIC_ARTIFACT_PATHS)
                self.assertTrue(os.path.exists(
                    os.path.join(REPO_ROOT, *relative.split("/"))))

    def test_every_artifact_is_canonical_json(self):
        for relative, rendered in sorted(self.built.items()):
            with self.subTest(artifact=relative):
                document = json.loads(rendered)
                self.assertEqual(
                    rendered,
                    json.dumps(document, indent=2, sort_keys=True,
                               ensure_ascii=True) + "\n")

    def test_no_published_document_contains_an_account_or_a_secret(self):
        """A26. Not one user row, session, hash, cookie or token."""
        for relative, rendered in sorted(self.built.items()):
            with self.subTest(artifact=relative):
                for marker in ("$argon2id$v=", "__Host-pgx_session=",
                               "Bearer ", "password_hash\": \"",
                               "csrf_secret", "token_digest\": \""):
                    self.assertNotIn(marker, rendered)

    def test_no_schema_declares_a_forbidden_property(self):
        """A published document cannot even have a place to put one."""
        for relative, schema in build_schemas().items():
            properties = set(schema.get("properties", {}))
            for nested in schema.get("properties", {}).values():
                if isinstance(nested, dict) and "items" in nested:
                    item = nested["items"]
                    if isinstance(item, dict):
                        properties |= set(item.get("properties", {}))
            for forbidden in FORBIDDEN_PROPERTY_NAMES:
                with self.subTest(schema=relative, property=forbidden):
                    self.assertNotIn(forbidden, properties)


class TestThePublishedRegistries(unittest.TestCase):

    def test_the_rbac_registry_validates_and_names_no_hierarchy(self):
        document = json.loads(_read("data/security/wp23-rbac-registry.json"))
        self.assertEqual(validate_rbac_registry(document), [])
        self.assertIsNone(document["role_hierarchy"])

    def test_the_rate_limit_policy_validates(self):
        document = json.loads(
            _read("data/security/wp23-rate-limit-policy.json"))
        self.assertEqual(validate_rate_limit_policy(document), [])

    def test_the_action_registry_covers_every_governed_area(self):
        registry = build_audit_action_registry()
        for area in ("authentication", "assessment", "release",
                     "curation_and_rules", "expert_review"):
            with self.subTest(area=area):
                self.assertIn(area, registry["areas"])
                self.assertTrue(registry["areas"][area])

    def test_the_action_registry_carries_no_event(self):
        """It names actions. The trail itself is not published."""
        rendered = json.dumps(build_audit_action_registry())
        for marker in ("actor_id", "event_hash", "session_reference",
                       "occurred_at"):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, rendered)


class TestSafeProjectionsHaveNowhereToLeak(unittest.TestCase):

    def test_a_user_projection_validates_and_has_no_hash_property(self):
        from tests.fixtures.wp23.security import RecordingHasher, user

        document = user(hasher=RecordingHasher()).safe_projection()
        self.assertEqual(validate_user_projection(document), [])
        self.assertNotIn("password_hash", document)

    def test_a_user_projection_with_a_hash_is_refused(self):
        """``additionalProperties: false``: absence by construction rather
        than by a producer remembering to drop it."""
        from tests.fixtures.wp23.security import RecordingHasher, user

        document = dict(user(hasher=RecordingHasher()).safe_projection())
        document["password_hash"] = "$argon2id$anything"
        self.assertTrue(validate_user_projection(document))

    def test_a_session_projection_validates_and_carries_no_digest(self):
        from pgx.security.sessions import (SessionPolicy, build_session,
                                           new_session_token)
        from tests.fixtures.wp23.security import NOW

        record = build_session(
            session_id="SES-TEST-ONLY-1", user_id="TEST-ONLY-user-1",
            role="ADMIN", token=new_session_token(), csrf_secret="x" * 32,
            auth_generation=1, now=NOW, policy=SessionPolicy())
        document = record.safe_projection()
        self.assertEqual(validate_session_projection(document), [])
        self.assertNotIn("token_digest", document)
        self.assertNotIn("csrf_secret", document)

    def test_a_session_projection_carrying_a_digest_is_refused(self):
        from pgx.security.sessions import (SessionPolicy, build_session,
                                           new_session_token)
        from tests.fixtures.wp23.security import NOW

        record = build_session(
            session_id="SES-TEST-ONLY-1", user_id="TEST-ONLY-user-1",
            role="ADMIN", token=new_session_token(), csrf_secret="x" * 32,
            auth_generation=1, now=NOW, policy=SessionPolicy())
        document = dict(record.safe_projection())
        document["token_digest"] = record.token_digest
        self.assertTrue(validate_session_projection(document))


class TestTheGateSeparatesThreeAnswers(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.status = json.loads(
            _read("data/security/wp23-real-gate-status.json"))

    def test_it_validates(self):
        self.assertEqual(validate_wp23_gate_status(self.status), [])

    def test_the_software_is_implemented(self):
        self.assertEqual(self.status["implementation_status"], "IMPLEMENTED")
        for field in ("authentication_software_implemented",
                      "session_management_implemented", "csrf_implemented",
                      "rate_limiting_implemented",
                      "canonical_audit_implemented",
                      "argon2_dependency_declared"):
            with self.subTest(field=field):
                self.assertTrue(self.status[field])

    def test_nothing_is_configured(self):
        """A31. The default unconfigured deployment fails closed."""
        for field in ("database_available", "authentication_configured",
                      "csrf_operational", "rate_limiting_operational",
                      "https_termination_observed",
                      "migration_0011_executed"):
            with self.subTest(field=field):
                self.assertFalse(self.status[field])

    def test_nothing_is_operating(self):
        self.assertIsNone(self.status["real_users_configured"])
        self.assertIsNone(self.status["audit_chain_verified"])
        self.assertFalse(self.status["backup_executed"])
        self.assertFalse(self.status["restore_executed"])
        self.assertFalse(self.status["restore_verified"])
        self.assertFalse(
            self.status["session_authentication_exercised_operationally"])

    def test_null_and_zero_stay_distinguishable(self):
        """"We did not look" must not read as "we looked and found none"."""
        self.assertIn("null rather than zero",
                      self.status["real_user_count_source"])

    def test_the_gate_is_blocked_and_the_release_may_not_proceed(self):
        self.assertEqual(self.status["security_gate_status"], "BLOCKED")
        self.assertFalse(self.status["release_may_proceed"])

    def test_every_blocker_names_an_owner(self):
        self.assertGreater(self.status["blocking_count"], 0)
        for blocker in self.status["blockers"]:
            with self.subTest(code=blocker["code"]):
                self.assertTrue(blocker["owner"])

    def test_wp22_and_wp21_truths_are_unchanged(self):
        """A28, A47, A48. WP-23 configured nothing about either."""
        self.assertFalse(self.status["expert_review_performed"])
        self.assertFalse(self.status["clinical_validation_performed"])

    def test_pass_demands_every_operational_precondition(self):
        """The state function, exercised directly: no single missing
        precondition can be papered over by the others."""
        satisfied = dict(
            implemented=True, argon2=True, database=True,
            migration_executed=True, real_users=1,
            authentication_configured=True, https_observed=True,
            audit_chain_verified=True, backup_verified=True,
            secret_findings=0)
        self.assertEqual(security_gate_state(**satisfied), "PASS")
        for field, blocking_value in (
                ("argon2", False), ("database", False),
                ("migration_executed", False), ("real_users", 0),
                ("authentication_configured", False),
                ("https_observed", False), ("audit_chain_verified", False),
                ("backup_verified", False)):
            with self.subTest(missing=field):
                probe = dict(satisfied)
                probe[field] = blocking_value
                self.assertEqual(security_gate_state(**probe), "BLOCKED")

    def test_a_secret_finding_fails_rather_than_blocks(self):
        """A finding is a defect in this repository, not a missing external
        precondition, so it is FAILED rather than BLOCKED."""
        probe = dict(
            implemented=True, argon2=True, database=True,
            migration_executed=True, real_users=1,
            authentication_configured=True, https_observed=True,
            audit_chain_verified=True, backup_verified=True,
            secret_findings=1)
        self.assertEqual(security_gate_state(**probe), "FAILED")

    def test_every_module_marker_exists(self):
        self.assertEqual(len(security_module_markers(REPO_ROOT)),
                         len(MODULE_MARKERS))

    def test_the_document_states_it_is_not_a_certification(self):
        self.assertIn("not a penetration test",
                      self.status["not_a_security_certification"])


class TestAuditVerificationWithoutAStore(unittest.TestCase):

    def test_it_reports_null_rather_than_a_passing_result(self):
        from pgx.application.audit_cli import verification_document

        document = verification_document(None)
        self.assertEqual(validate_audit_verification(document), [])
        self.assertIsNone(document["verified"])
        self.assertIn("not a passing result", document["reason"])

    def test_it_promises_to_report_no_event_content(self):
        from pgx.application.audit_cli import verification_document

        self.assertTrue(
            verification_document(None)["reports_no_event_content"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
