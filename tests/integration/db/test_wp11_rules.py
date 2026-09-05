# -*- coding: utf-8 -*-
"""WP-11 rule and ruleset constraints on real PostgreSQL.

Skipped wherever Alembic, SQLAlchemy or ``TEST_DATABASE_URL`` is unavailable,
which is everywhere in the current environment. A skip is not a pass: the
WP-11 report records the Alembic criterion as BLOCKED, and the equivalent
evidence was produced by running the rendered DDL against PostgreSQL 16.13 by
hand. ``docs/evidence/wp11-schema-validation.md`` records that run, the 24
behavioural probes, and what it does and does not prove.

These tests exist so that the moment Alembic can be installed, the same
guarantees are checked by the suite rather than by a transcript.
"""

from __future__ import annotations

import datetime as _dt
import unittest
import uuid

from tests.integration.db._support import PostgresTestCase

NOW = _dt.datetime(2026, 9, 3, 12, 0, tzinfo=_dt.timezone.utc)
DIGEST = "sha256:" + "a" * 64
OTHER = "sha256:" + "b" * 64


class Wp11TestCase(PostgresTestCase):
    """One DRAFT rule, with the upstream rows it needs to exist."""

    def _execute(self, sql, **params):
        from sqlalchemy import text
        with self.engine.begin() as connection:
            return connection.execute(text(sql), params)

    def _draft_rule(self, **overrides):
        rule_id = overrides.pop("id", uuid.uuid4())
        self._execute(
            "INSERT INTO computable_rules (id, interpretation_id,"
            " condition_json, attention_level, status, rule_version,"
            " created_by, created_at, rule_family_id, content_hash,"
            " lifecycle_version, gene_canonical_key, drug_canonical_key)"
            " VALUES (:id, :interp, '{}', :level, 'DRAFT', 1, 'TEST-author-1',"
            " :now, :family, :hash, 1, 'GENE:TESTGENE1', 'DRUG:testdrug-alpha')",
            id=rule_id, interp=uuid.uuid4(),
            level=overrides.get("attention_level", "MEDIUM"),
            now=NOW, family=uuid.uuid4(), hash=DIGEST)
        return rule_id


class TestARuleMayNotAuthorNotAssessed(Wp11TestCase):

    def test_not_assessed_is_refused(self):
        from sqlalchemy.exc import IntegrityError
        with self.assertRaises(IntegrityError):
            self._draft_rule(attention_level="NOT_ASSESSED")


class TestTheRuleLifecycleIsEnforcedByTheDatabase(Wp11TestCase):

    def test_draft_to_validated_directly_is_refused(self):
        from sqlalchemy.exc import DBAPIError
        rule_id = self._draft_rule()
        with self.assertRaises(DBAPIError):
            self._execute(
                "UPDATE computable_rules SET status='VALIDATED',"
                " lifecycle_version=2 WHERE id=:id", id=rule_id)

    def test_a_status_change_must_advance_the_lifecycle_version(self):
        from sqlalchemy.exc import DBAPIError
        rule_id = self._draft_rule()
        with self.assertRaises(DBAPIError):
            self._execute(
                "UPDATE computable_rules SET status='CURATED'"
                " WHERE id=:id", id=rule_id)

    def test_a_rule_cannot_be_deleted(self):
        from sqlalchemy.exc import DBAPIError
        rule_id = self._draft_rule()
        with self.assertRaises(DBAPIError):
            self._execute("DELETE FROM computable_rules WHERE id=:id",
                          id=rule_id)


class TestSeparationOfDutiesIsEnforcedByTheDatabase(Wp11TestCase):

    def test_the_validator_may_not_be_the_author(self):
        from sqlalchemy.exc import IntegrityError
        rule_id = self._draft_rule()
        self._execute(
            "UPDATE computable_rules SET status='CURATED', lifecycle_version=2,"
            " curation_revision_id='REV-1', curation_revision_hash=:h"
            " WHERE id=:id", id=rule_id, h=DIGEST)
        with self.assertRaises(IntegrityError):
            self._execute(
                "UPDATE computable_rules SET status='VALIDATED',"
                " lifecycle_version=3, validated_by='TEST-author-1',"
                " validated_at=:now WHERE id=:id", id=rule_id, now=NOW)


class TestARulesetCannotJumpToFrozen(Wp11TestCase):

    def _ruleset(self, status="BUILDING"):
        ruleset_id = uuid.uuid4()
        self._execute(
            "INSERT INTO ruleset_versions (id, public_id, status,"
            " manifest_hash, created_at, lifecycle_version)"
            " VALUES (:id, :pid, :status, :hash, :now, 1)",
            id=ruleset_id, pid="PGX-RULESET-29991231-001", status=status,
            hash=DIGEST, now=NOW)
        return ruleset_id

    def test_building_to_frozen_is_refused(self):
        from sqlalchemy.exc import DBAPIError
        ruleset_id = self._ruleset()
        with self.assertRaises(DBAPIError):
            self._execute(
                "UPDATE ruleset_versions SET status='FROZEN',"
                " lifecycle_version=2 WHERE id=:id", id=ruleset_id)

    def test_a_frozen_ruleset_cannot_be_unfrozen(self):
        from sqlalchemy.exc import DBAPIError
        ruleset_id = self._ruleset()
        self._execute(
            "UPDATE ruleset_versions SET status='VALIDATED',"
            " lifecycle_version=2 WHERE id=:id", id=ruleset_id)
        self._execute(
            "UPDATE ruleset_versions SET status='FROZEN', lifecycle_version=3,"
            " frozen_by='TEST-builder-1', frozen_at=:now,"
            " ruleset_content_hash=:hash,"
            " artifact_relative_path='PGX-RULESET-29991231-001'"
            " WHERE id=:id", id=ruleset_id, now=NOW, hash=OTHER)
        with self.assertRaises(DBAPIError):
            self._execute(
                "UPDATE ruleset_versions SET status='BUILDING',"
                " lifecycle_version=4 WHERE id=:id", id=ruleset_id)


class TestBuildAndApprovalRecordsAreAppendOnly(Wp11TestCase):

    def test_a_build_record_cannot_be_updated(self):
        from sqlalchemy.exc import DBAPIError
        ruleset_id = uuid.uuid4()
        self._execute(
            "INSERT INTO ruleset_versions (id, public_id, status,"
            " manifest_hash, created_at, lifecycle_version)"
            " VALUES (:id, 'PGX-RULESET-29991231-002', 'BUILDING', :hash,"
            " :now, 1)", id=ruleset_id, hash=DIGEST, now=NOW)
        build_id = uuid.uuid4()
        self._execute(
            "INSERT INTO ruleset_builds (id, ruleset_id, started_at,"
            " completed_at, built_by, outcome, member_count, issue_codes)"
            " VALUES (:id, :rs, :now, :now, 'TEST-builder-1', 'FAILED', 0,"
            " '[]')", id=build_id, rs=ruleset_id, now=NOW)
        with self.assertRaises(DBAPIError):
            self._execute(
                "UPDATE ruleset_builds SET outcome='SUCCEEDED' WHERE id=:id",
                id=build_id)


class TestTheAuditActionVocabularyIsClosed(Wp11TestCase):

    def test_the_new_rule_actions_are_accepted(self):
        for action in ("RULE_DRAFTED", "RULE_VALIDATED", "RULESET_FROZEN",
                       "RULE_VALIDATION_REFUSED"):
            with self.subTest(action=action):
                self._execute(
                    "INSERT INTO audit_events (id, action, actor,"
                    " object_type, object_id, occurred_at)"
                    " VALUES (:id, :action, 'TEST-actor-1', 'computable_rule',"
                    " 'x', :now)", id=uuid.uuid4(), action=action, now=NOW)

    def test_an_invented_action_is_refused(self):
        from sqlalchemy.exc import IntegrityError
        with self.assertRaises(IntegrityError):
            self._execute(
                "INSERT INTO audit_events (id, action, actor, object_type,"
                " object_id, occurred_at) VALUES (:id, 'RULE_AUTO_APPROVED',"
                " 'TEST-actor-1', 'computable_rule', 'x', :now)",
                id=uuid.uuid4(), now=NOW)


if __name__ == "__main__":
    unittest.main()
