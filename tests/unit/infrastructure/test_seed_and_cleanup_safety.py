# -*- coding: utf-8 -*-
"""Seed drift detection and destructive-statement policy (WP-02 corrective).

Two findings are proven here, both without a database.

**Seed drift.** The first draft compared every seeded field *except*
``created_at``. A row whose timestamp had been rewritten therefore reported
"already present, no drift" - for a record whose entire purpose is to be
byte-reproducible in every environment. ``created_at`` is now part of the
comparison, and these tests drive :func:`detect_drift` with a mutated row to
prove it.

**Destructive statements.** Integration teardown used
``DROP ... CASCADE`` / ``TRUNCATE ... CASCADE``. ``CASCADE`` follows dependency
edges the suite does not own, so a cascading drop in a shared database can
remove objects belonging to a later work package. Teardown now drops and clears
child-first without ``CASCADE``, and this suite reads the support module's AST
to prove no ``CASCADE`` re-enters.

Standard library only.
"""

from __future__ import annotations

import ast
import datetime as _dt
import io
import os
import re
import unittest

from pgx.infrastructure.db.cli_seed import (
    INTERNAL_SYSTEM_SOURCE_KEY, SEED_EPOCH, SEED_SCHEMA_VERSION,
    _COMPARED_FIELDS, build_seed_entry, canonical_seed_manifest,
    comparable_fields, detect_drift,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

SUPPORT_MODULE = "tests/integration/db/_support.py"

INTEGRATION_MODULES = (
    SUPPORT_MODULE,
    "tests/integration/db/test_migrations.py",
    "tests/integration/db/test_constraints.py",
    "tests/integration/db/test_repositories.py",
    "tests/integration/db/test_unit_of_work.py",
    "tests/integration/db/test_seed.py",
)


def _read(relative: str) -> str:
    with io.open(os.path.join(REPO_ROOT, relative), encoding="utf-8") as handle:
        return handle.read()


def _docstring_nodes(tree):
    """Every string node that is a docstring, so prose is excluded from checks."""
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            found.add(id(body[0].value))
    return found


def _code_strings(relative: str):
    """Return string literals that are code, not docstrings.

    Comments never reach the AST, so a comment cannot be mistaken for a
    statement either.
    """
    tree = ast.parse(_read(relative))
    docstrings = _docstring_nodes(tree)
    return [node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings]


def _ordered_tables(relative: str, function_name: str):
    """Return the ``ordered`` table tuple assigned inside ``function_name``."""
    tree = ast.parse(_read(relative))
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != function_name:
            continue
        for statement in ast.walk(node):
            if (isinstance(statement, ast.Assign)
                    and any(getattr(target, "id", None) == "ordered"
                            for target in statement.targets)
                    and isinstance(statement.value, (ast.Tuple, ast.List))):
                return [element.value for element in statement.value.elts]
    return []


def _replaced(entry, **changes):
    """Return a copy of a frozen domain object with fields replaced."""
    import dataclasses
    return dataclasses.replace(entry, **changes)


class TestSeedIsDeterministic(unittest.TestCase):

    def test_the_manifest_hash_is_stable_across_calls(self):
        self.assertEqual(canonical_seed_manifest()["canonical_payload_hash"],
                         canonical_seed_manifest()["canonical_payload_hash"])

    def test_the_identity_is_derived_not_random(self):
        self.assertEqual(build_seed_entry().id, build_seed_entry().id)

    def test_the_seed_epoch_is_fixed_and_utc(self):
        self.assertEqual(SEED_EPOCH.tzinfo, _dt.timezone.utc)
        self.assertEqual(build_seed_entry().created_at, SEED_EPOCH)

    def test_the_seeded_row_is_not_release_eligible(self):
        self.assertFalse(build_seed_entry().release_eligible)

    def test_the_schema_version_is_recorded_in_the_manifest(self):
        self.assertEqual(canonical_seed_manifest()["seed_schema_version"],
                         SEED_SCHEMA_VERSION)

    def test_exactly_one_row_is_seeded(self):
        self.assertEqual(len(canonical_seed_manifest()["records"]), 1)

    def test_the_seed_is_the_internal_system_source(self):
        self.assertEqual(build_seed_entry().source_key, INTERNAL_SYSTEM_SOURCE_KEY)


class TestDriftDetectionIncludesCreatedAt(unittest.TestCase):
    """The finding: a rewritten timestamp was invisible."""

    def setUp(self):
        self.expected = build_seed_entry()

    def test_created_at_is_a_compared_field(self):
        self.assertIn("created_at", _COMPARED_FIELDS)

    def test_created_at_is_reported_by_comparable_fields(self):
        self.assertIn("created_at", comparable_fields(self.expected))

    def test_an_identical_row_reports_no_drift(self):
        self.assertEqual(detect_drift(self.expected, build_seed_entry()), [])

    def test_a_changed_timestamp_is_detected(self):
        stored = _replaced(
            self.expected,
            created_at=SEED_EPOCH + _dt.timedelta(seconds=1))
        drift = detect_drift(self.expected, stored)
        self.assertEqual([item["field"] for item in drift], ["created_at"])

    def test_a_timestamp_a_year_out_is_detected(self):
        stored = _replaced(self.expected,
                           created_at=SEED_EPOCH.replace(year=2027))
        self.assertTrue(any(item["field"] == "created_at"
                            for item in detect_drift(self.expected, stored)))

    def test_the_same_instant_in_another_offset_is_not_drift(self):
        other_zone = _dt.timezone(_dt.timedelta(hours=3))
        stored = _replaced(self.expected,
                           created_at=SEED_EPOCH.astimezone(other_zone))
        self.assertEqual(detect_drift(self.expected, stored), [])

    def test_a_changed_display_name_is_detected(self):
        stored = _replaced(self.expected, display_name="Tampered")
        self.assertEqual(
            [item["field"] for item in detect_drift(self.expected, stored)],
            ["display_name"])

    def test_a_flipped_active_flag_is_detected(self):
        stored = _replaced(self.expected, active=False)
        self.assertTrue(any(item["field"] == "active"
                            for item in detect_drift(self.expected, stored)))

    def test_release_eligibility_cannot_drift_because_the_domain_refuses_it(self):
        """A stronger guarantee than drift detection: the row cannot exist.

        SAFETY-INV: an INTERNAL_SYSTEM source is technical bookkeeping and can
        never become release-eligible scientific evidence, so there is no
        in-memory value for drift detection to catch.
        """
        from pgx.domain.errors import DomainInvariantError

        with self.assertRaises(DomainInvariantError):
            _replaced(self.expected, release_eligible=True)
        self.assertIn("release_eligible", _COMPARED_FIELDS)

    def test_drift_reports_both_values(self):
        stored = _replaced(self.expected, display_name="Tampered")
        entry = detect_drift(self.expected, stored)[0]
        self.assertEqual(entry["stored"], "Tampered")
        self.assertEqual(entry["expected"], self.expected.display_name)

    def test_several_changes_are_all_reported(self):
        stored = _replaced(self.expected, display_name="Tampered",
                           created_at=SEED_EPOCH + _dt.timedelta(days=1))
        fields = {item["field"] for item in detect_drift(self.expected, stored)}
        self.assertEqual(fields, {"display_name", "created_at"})

    def test_every_seeded_field_is_compared(self):
        payload_fields = set(canonical_seed_manifest()["records"][0]) - {"id"}
        self.assertEqual(set(_COMPARED_FIELDS), payload_fields)


class TestNoCascadeInIntegrationTeardown(unittest.TestCase):
    """``CASCADE`` can reach objects this suite does not own.

    Every assertion below reads *code*, never prose: a docstring that explains
    why ``CASCADE`` is forbidden must not be mistaken for a ``CASCADE``
    statement, and a test that cannot tell them apart proves nothing.
    """

    def test_no_integration_module_executes_cascade(self):
        for relative in INTEGRATION_MODULES:
            with self.subTest(module=relative):
                offenders = [literal for literal in _code_strings(relative)
                             if re.search(r"(?i)\bCASCADE\b", literal)]
                self.assertEqual(offenders, [])

    def test_no_integration_module_executes_truncate(self):
        for relative in INTEGRATION_MODULES:
            with self.subTest(module=relative):
                offenders = [literal for literal in _code_strings(relative)
                             if re.search(r"(?i)\bTRUNCATE\b", literal)]
                self.assertEqual(offenders, [])

    def test_no_integration_module_drops_a_schema_or_database(self):
        pattern = r"(?i)\bDROP\s+(SCHEMA|DATABASE|OWNED)\b"
        for relative in INTEGRATION_MODULES:
            with self.subTest(module=relative):
                offenders = [literal for literal in _code_strings(relative)
                             if re.search(pattern, literal)]
                self.assertEqual(offenders, [])

    def test_the_only_drop_statement_is_a_plain_drop_table(self):
        statements = [literal for literal in _code_strings(SUPPORT_MODULE)
                      if re.search(r"(?i)\bDROP\b", literal)]
        self.assertEqual(statements, ['DROP TABLE IF EXISTS "%s"'])

    def test_row_clearing_uses_a_plain_delete(self):
        statements = [literal for literal in _code_strings(SUPPORT_MODULE)
                      if re.search(r"(?i)\bDELETE\b", literal)]
        self.assertEqual(statements, ['DELETE FROM "%s"'])

    def test_the_singleton_pointer_is_reset_rather_than_deleted(self):
        """Migration 0002 creates that row; activation always locks *it*.

        Deleting it between tests would leave later activations with nothing to
        lock - which is to say, nothing locked at all.
        """
        statements = [literal for literal in _code_strings(SUPPORT_MODULE)
                      if "active_release" in literal]
        self.assertTrue(any(literal.startswith('UPDATE "active_release"')
                            for literal in statements))
        for literal in statements:
            self.assertNotIn("DELETE", literal.upper())

    def test_teardown_touches_only_tables_the_migrations_own(self):
        from tests.integration.db._support import ALL_TABLES

        permitted = set(ALL_TABLES) | {"alembic_version"}
        for function in ("drop_wp02_objects", "clear_wp02_rows"):
            with self.subTest(function=function):
                tables = _ordered_tables(SUPPORT_MODULE, function)
                self.assertTrue(tables, "%s names no tables" % function)
                self.assertEqual(set(tables) - permitted, set())

    def test_row_clearing_never_touches_the_alembic_table(self):
        self.assertNotIn("alembic_version",
                         _ordered_tables(SUPPORT_MODULE, "clear_wp02_rows"))

    def test_teardown_covers_every_table_the_migrations_create(self):
        """A table left out of teardown accumulates rows between runs."""
        from tests.integration.db._support import ALL_TABLES

        dropped = set(_ordered_tables(SUPPORT_MODULE, "drop_wp02_objects"))
        self.assertEqual(set(ALL_TABLES) - dropped, set())

    def test_tables_are_ordered_children_before_parents(self):
        """Child-first ordering is what makes CASCADE unnecessary."""
        for function in ("drop_wp02_objects", "clear_wp02_rows"):
            with self.subTest(function=function):
                tables = _ordered_tables(SUPPORT_MODULE, function)
                for child, parent in (("rule_evidence", "computable_rules"),
                                      ("interpretation_evidence",
                                       "curated_interpretations"),
                                      ("evidence_records", "source_registry"),
                                      ("gene_aliases", "genes"),
                                      ("drug_aliases", "drugs"),
                                      # WP-03: the pointer and the audit trail
                                      # both reference release_bundles, which
                                      # references what WP-02 owns.
                                      ("audit_events", "release_bundles"),
                                      ("active_release", "release_bundles"),
                                      ("release_bundles", "ruleset_versions"),
                                      ("release_bundles", "dataset_versions"),
                                      ("release_bundles", "software_versions"),
                                      ("ruleset_rules", "ruleset_versions")):
                    self.assertLess(tables.index(child), tables.index(parent),
                                    "%s must be removed before %s"
                                    % (child, parent))

    def test_the_support_module_declares_its_safety_guards(self):
        tree = ast.parse(_read(SUPPORT_MODULE))
        defined = {node.name for node in ast.walk(tree)
                   if isinstance(node, ast.FunctionDef)}
        for name in ("unexpected_tables", "assert_disposable_test_schema",
                     "drop_wp02_objects", "clear_wp02_rows",
                     "require_postgres_dependencies"):
            self.assertIn(name, defined)

    def test_every_config_load_asks_for_the_test_database(self):
        """The application URL must never be the one a test connects with."""
        tree = ast.parse(_read(SUPPORT_MODULE))
        calls = [node for node in ast.walk(tree)
                 if isinstance(node, ast.Call)
                 and getattr(node.func, "id", None) == "load_database_config"]
        self.assertTrue(calls, "no load_database_config call found")
        for call in calls:
            keywords = {keyword.arg: keyword.value for keyword in call.keywords}
            self.assertIn("use_test_database", keywords)
            self.assertIs(keywords["use_test_database"].value, True)

    def test_the_application_url_is_read_only_to_refuse_a_collision(self):
        """``DATABASE_URL`` is read only by the two collision guards.

        It is never used to build an engine, open a connection, or configure
        Alembic - only to detect that the "test" target is in fact the
        application database.
        """
        tree = ast.parse(_read(SUPPORT_MODULE))
        holders = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for inner in ast.walk(node):
                if (isinstance(inner, ast.Constant)
                        and inner.value == "DATABASE_URL"):
                    holders.add(node.name)
        self.assertEqual(holders, {"assert_is_test_database",
                                   "assert_engine_targets_test_database"})

    def test_the_database_name_must_announce_itself_as_a_test(self):
        from tests.integration.db._support import (
            TestDatabaseSafetyError, assert_is_test_database,
        )
        assert_is_test_database(
            "postgresql+psycopg://u:p@localhost:55432/pgx_test")
        with self.assertRaises(TestDatabaseSafetyError):
            assert_is_test_database(
                "postgresql+psycopg://u:p@localhost:5432/pgx_dev")

    def test_a_url_without_a_database_name_is_refused(self):
        from tests.integration.db._support import (
            TestDatabaseSafetyError, assert_is_test_database,
        )
        with self.assertRaises(TestDatabaseSafetyError):
            assert_is_test_database("postgresql+psycopg://u:p@localhost:5432/")

    def test_a_test_url_equal_to_the_application_url_is_refused(self):
        from tests.integration.db._support import (
            TestDatabaseSafetyError, assert_is_test_database,
        )
        url = "postgresql+psycopg://u:p@localhost:5432/pgx_test"
        previous = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = url
        try:
            with self.assertRaises(TestDatabaseSafetyError):
                assert_is_test_database(url)
        finally:
            if previous is None:
                os.environ.pop("DATABASE_URL", None)
            else:  # pragma: no cover - restores a pre-existing value
                os.environ["DATABASE_URL"] = previous



class TestTheTestDatabaseNameMustMatchExactly(unittest.TestCase):
    """A substring rule cleared real databases for destruction.

    The previous guard accepted any name containing ``test`` or ``ci``. That is
    not a narrow class: ``financial`` contains ``ci``, ``contest`` contains
    ``test``, and ``production_ci_backup`` contains both. Each of those would
    have been migrated down to base by a test run pointed at it.
    """

    def _env(self, **overrides):
        environment = dict(os.environ)
        environment.pop("DATABASE_URL", None)
        environment.pop("PGX_TEST_DATABASE_NAME", None)
        environment.update(overrides)
        return environment

    def _accepts(self, database, **overrides):
        from tests.integration.db._support import assert_is_test_database

        assert_is_test_database(
            "postgresql+psycopg://u:p@localhost:5432/%s" % database,
            env=self._env(**overrides))

    def _rejects(self, database, **overrides):
        from tests.integration.db._support import (
            TestDatabaseSafetyError, assert_is_test_database,
        )
        with self.assertRaises(TestDatabaseSafetyError):
            assert_is_test_database(
                "postgresql+psycopg://u:p@localhost:5432/%s" % database,
                env=self._env(**overrides))

    def test_the_default_test_database_is_accepted(self):
        self._accepts("pgx_test")

    def test_an_explicitly_configured_ci_database_is_accepted(self):
        self._accepts("ci_pgx_scratch",
                      PGX_TEST_DATABASE_NAME="ci_pgx_scratch")

    def test_the_default_is_rejected_once_an_override_is_configured(self):
        self._rejects("pgx_test", PGX_TEST_DATABASE_NAME="ci_pgx_scratch")

    def test_financial_is_rejected(self):
        self._rejects("financial")

    def test_production_ci_backup_is_rejected(self):
        self._rejects("production_ci_backup")

    def test_contest_is_rejected(self):
        self._rejects("contest")

    def test_latest_production_is_rejected(self):
        self._rejects("latest_production")

    def test_clinical_is_rejected(self):
        self._rejects("clinical")

    def test_a_near_miss_name_is_rejected(self):
        for database in ("pgx_testing", "pgx_test_old", "test", "my_pgx_test"):
            with self.subTest(database=database):
                self._rejects(database)

    def test_a_url_naming_no_database_is_rejected(self):
        self._rejects("")

    def test_the_expected_name_defaults_to_pgx_test(self):
        from tests.integration.db._support import (
            DEFAULT_TEST_DATABASE_NAME, expected_test_database_name,
        )
        self.assertEqual(DEFAULT_TEST_DATABASE_NAME, "pgx_test")
        self.assertEqual(expected_test_database_name(self._env()), "pgx_test")

    def test_the_override_is_honoured_exactly(self):
        from tests.integration.db._support import expected_test_database_name

        self.assertEqual(
            expected_test_database_name(
                self._env(PGX_TEST_DATABASE_NAME="  ci_db  ")),
            "ci_db")

    def test_no_substring_matching_survives_in_the_source(self):
        """The old markers tuple and its ``any(... in name)`` test are gone."""
        source = _read(SUPPORT_MODULE)
        self.assertNotIn("_TEST_DATABASE_MARKERS", source)
        self.assertNotRegex(source, r"any\(marker in ")


class TestTheSameDatabaseCannotHideBehindADifferentUrl(unittest.TestCase):
    """String equality compared spellings; the endpoint comparison compares
    what actually gets dropped."""

    APPLICATION = "postgresql://app:appsecret@localhost:5432/pgx_test"

    def _env(self, application=None):
        environment = dict(os.environ)
        environment.pop("PGX_TEST_DATABASE_NAME", None)
        if application is None:
            environment.pop("DATABASE_URL", None)
        else:
            environment["DATABASE_URL"] = application
        return environment

    def _rejects(self, url, application):
        from tests.integration.db._support import (
            TestDatabaseSafetyError, assert_is_test_database,
        )
        with self.assertRaises(TestDatabaseSafetyError):
            assert_is_test_database(url, env=self._env(application))

    def _accepts(self, url, application):
        from tests.integration.db._support import assert_is_test_database

        assert_is_test_database(url, env=self._env(application))

    def test_a_different_driver_spelling_is_not_a_different_database(self):
        self._rejects("postgresql+psycopg://test:two@localhost:5432/pgx_test",
                      self.APPLICATION)

    def test_different_credentials_are_not_a_different_database(self):
        self._rejects("postgresql://other:different@localhost:5432/pgx_test",
                      self.APPLICATION)

    def test_127_0_0_1_is_localhost(self):
        self._rejects("postgresql+psycopg://u:p@127.0.0.1:5432/pgx_test",
                      self.APPLICATION)

    def test_ipv6_loopback_is_localhost(self):
        self._rejects("postgresql+psycopg://u:p@[::1]:5432/pgx_test",
                      self.APPLICATION)

    def test_an_omitted_port_is_the_default_port(self):
        self._rejects("postgresql+psycopg://u:p@localhost/pgx_test",
                      self.APPLICATION)

    def test_query_parameters_do_not_make_it_a_different_database(self):
        self._rejects(
            "postgresql+psycopg://u:p@localhost:5432/pgx_test?sslmode=require",
            self.APPLICATION + "?application_name=pgx")

    def test_query_parameter_order_is_irrelevant(self):
        from tests.integration.db._support import canonical_endpoint

        self.assertEqual(
            canonical_endpoint("postgresql://u:p@h:5432/pgx_test?a=1&b=2"),
            canonical_endpoint("postgresql://u:p@h:5432/pgx_test?b=2&a=1"))

    def test_a_different_database_name_is_allowed(self):
        self._accepts("postgresql+psycopg://u:p@localhost:5432/pgx_test",
                      "postgresql+psycopg://u:p@localhost:5432/pgx_dev")

    def test_a_different_host_is_allowed(self):
        self._accepts("postgresql+psycopg://u:p@localhost:5432/pgx_test",
                      "postgresql+psycopg://u:p@db.internal:5432/pgx_test")

    def test_a_different_port_is_allowed(self):
        self._accepts("postgresql+psycopg://u:p@localhost:55432/pgx_test",
                      "postgresql+psycopg://u:p@localhost:5432/pgx_test")

    def test_no_application_url_configured_is_allowed(self):
        self._accepts("postgresql+psycopg://u:p@localhost:5432/pgx_test", None)

    def test_a_malformed_port_does_not_crash_the_guard(self):
        from tests.integration.db._support import canonical_endpoint

        self.assertEqual(
            canonical_endpoint("postgresql://u:p@h:notaport/pgx_test"),
            ("postgresql", "h", 5432, "pgx_test"))


class TestTheSafetyErrorNeverCarriesACredential(unittest.TestCase):

    SECRETS = ("appsecret", "testsecret")

    def _message(self, url, application=None):
        from tests.integration.db._support import (
            TestDatabaseSafetyError, assert_is_test_database,
        )
        environment = dict(os.environ)
        environment.pop("PGX_TEST_DATABASE_NAME", None)
        environment.pop("DATABASE_URL", None)
        if application:
            environment["DATABASE_URL"] = application
        with self.assertRaises(TestDatabaseSafetyError) as caught:
            assert_is_test_database(url, env=environment)
        return str(caught.exception)

    def test_a_wrong_name_rejection_carries_no_credential(self):
        message = self._message(
            "postgresql+psycopg://u:testsecret@h:5432/financial")
        for secret in self.SECRETS:
            self.assertNotIn(secret, message)

    def test_a_collision_rejection_carries_no_credential(self):
        message = self._message(
            "postgresql+psycopg://t:testsecret@localhost:5432/pgx_test",
            "postgresql://app:appsecret@localhost:5432/pgx_test")
        for secret in self.SECRETS:
            self.assertNotIn(secret, message)

    def test_a_missing_database_rejection_carries_no_credential(self):
        message = self._message("postgresql+psycopg://u:testsecret@h:5432/")
        for secret in self.SECRETS:
            self.assertNotIn(secret, message)

    def test_the_rejection_still_names_the_offending_database(self):
        self.assertIn("financial", self._message(
            "postgresql+psycopg://u:testsecret@h:5432/financial"))


class TestEveryDestructiveHelperChecksFirst(unittest.TestCase):
    """A guard that runs only at engine construction guards the wrong moment."""

    DESTRUCTIVE = ("drop_wp02_objects", "clear_wp02_rows")

    def _first_statements(self, function_name):
        tree = ast.parse(_read(SUPPORT_MODULE))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == function_name:
                return node
        raise AssertionError("%s is not defined" % function_name)

    def test_each_destructive_helper_calls_the_engine_guard(self):
        for name in self.DESTRUCTIVE:
            with self.subTest(function=name):
                node = self._first_statements(name)
                called = {inner.func.id for inner in ast.walk(node)
                          if isinstance(inner, ast.Call)
                          and isinstance(inner.func, ast.Name)}
                self.assertIn("assert_engine_targets_test_database", called)

    def test_the_guard_runs_before_any_execute(self):
        for name in self.DESTRUCTIVE:
            with self.subTest(function=name):
                node = self._first_statements(name)
                guard_line = min(
                    inner.lineno for inner in ast.walk(node)
                    if isinstance(inner, ast.Call)
                    and getattr(inner.func, "id", None)
                    == "assert_engine_targets_test_database")
                execute_lines = [inner.lineno for inner in ast.walk(node)
                                 if isinstance(inner, ast.Call)
                                 and getattr(inner.func, "attr", None) == "execute"]
                self.assertTrue(execute_lines)
                self.assertLess(guard_line, min(execute_lines))

    def test_the_engine_builder_also_re_checks(self):
        node = self._first_statements("make_test_engine")
        called = {inner.func.id for inner in ast.walk(node)
                  if isinstance(inner, ast.Call)
                  and isinstance(inner.func, ast.Name)}
        self.assertIn("assert_is_test_database", called)
        self.assertIn("assert_engine_targets_test_database", called)

    def test_the_skip_message_names_the_disposable_service(self):
        source = _read(SUPPORT_MODULE)
        self.assertIn("docker compose --profile test up -d postgres-test", source)

    def test_the_skip_message_does_not_send_users_to_the_dev_database(self):
        source = _read(SUPPORT_MODULE)
        self.assertNotIn("docker compose up -d postgres`", source)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
