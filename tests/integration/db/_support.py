# -*- coding: utf-8 -*-
"""Integration test support and database safety guards (WP-02).

Safety rules, all enforced before a single statement runs:

* only ``TEST_DATABASE_URL`` is ever used to connect - ``DATABASE_URL`` is read
  once, and only to refuse a target that turns out to be the same database;
* the target database name must **exactly equal** the configured test database
  name, so pointing the variable at a real database fails loudly instead of
  dropping its tables;
* the two URLs are compared as canonical endpoints (driver family, host, port,
  database), so different credentials or a different driver spelling cannot
  disguise the application database as a test one;
* SQLite is impossible: the URL validator rejects it, and these tests never
  fall back to another engine;
* teardown removes only the schema objects this suite created, never a database
  and never a Docker volume;
* no ``CASCADE`` is used anywhere: a cascading drop or truncate could reach
  objects a later work package owns, so tables are cleared child-first instead;
* if the target database holds a table WP-02 does not own, the suite **fails**
  rather than cleaning up around it.

When ``TEST_DATABASE_URL`` is absent the suite skips with an explicit reason.
A skip is not a pass: the WP-02 report records the PostgreSQL criteria as
BLOCKED in that case.
"""

from __future__ import annotations

import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

REPO_ROOT = _REPO_ROOT

#: The database this suite is allowed to destroy, unless overridden.
DEFAULT_TEST_DATABASE_NAME = "pgx_test"

#: Optional exact override, for a CI runner whose database has another name.
TEST_DATABASE_NAME_ENV = "PGX_TEST_DATABASE_NAME"

#: Host spellings that denote the same machine. ``""`` is a local socket.
_LOOPBACK_HOSTS = frozenset({
    "localhost", "127.0.0.1", "::1", "0:0:0:0:0:0:0:1", "",
})

#: Every accepted spelling of the PostgreSQL driver collapses to one family, so
#: ``postgresql://`` and ``postgresql+psycopg://`` are recognised as the same
#: server rather than as two unrelated URLs.
_POSTGRES_SCHEME_FAMILY = frozenset({"postgres", "postgresql"})

WP02_TABLES = (
    "source_registry", "dataset_versions", "genes", "gene_aliases", "drugs",
    "drug_aliases", "evidence_records", "curated_interpretations",
    "interpretation_evidence", "computable_rules", "rule_evidence",
)

#: WP-03 release registry tables, in dependency order (parents first).
WP03_TABLES = (
    "software_versions", "ruleset_versions", "ruleset_rules", "release_bundles",
    "active_release", "audit_events",
)

#: Everything the migrated schema owns.
ALL_TABLES = WP02_TABLES + WP03_TABLES


#: Runtime dependencies these tests cannot run without.
_REQUIRED_MODULES = ("sqlalchemy", "alembic", "psycopg")


def require_postgres_dependencies() -> None:
    """Skip with a precise reason when a database dependency is missing.

    Checked before anything imports the infrastructure layer, so the reason is
    "psycopg is not installed" rather than an opaque ImportError from deep in a
    module chain.
    """
    import importlib.util

    missing = [name for name in _REQUIRED_MODULES
               if importlib.util.find_spec(name) is None]
    if missing:
        raise unittest.SkipTest(
            "PostgreSQL integration tests require %s, which %s not installed in "
            "this environment. Install the project with `uv sync`, start the "
            "disposable database with "
            "`docker compose --profile test up -d postgres-test`, and retry. This "
            "skip is NOT a pass: the WP-02 acceptance report records the "
            "PostgreSQL criteria as BLOCKED."
            % (", ".join(missing), "is" if len(missing) == 1 else "are"))


class TestDatabaseSafetyError(RuntimeError):
    """Raised when the configured target is not safe to use for tests."""


def test_database_url() -> str:
    """Return ``TEST_DATABASE_URL`` or skip with an explicit reason."""
    url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not url:
        raise unittest.SkipTest(
            "TEST_DATABASE_URL is not set. PostgreSQL integration tests require a "
            "real PostgreSQL database; they never fall back to SQLite. Start the "
            "DISPOSABLE test database - not the development one, because these "
            "tests run `alembic downgrade base` - with "
            "`docker compose --profile test up -d postgres-test`, then export "
            "TEST_DATABASE_URL (see .env.example). This skip is not a pass: the "
            "WP-02 acceptance report records the PostgreSQL criteria as BLOCKED.")
    return url


def expected_test_database_name(env=None) -> str:
    """The one database name this suite may destroy.

    Defaults to ``pgx_test``; a CI runner whose database is named differently
    sets ``PGX_TEST_DATABASE_NAME`` to that exact name. There is deliberately no
    pattern and no substring rule - see :func:`assert_is_test_database`.
    """
    environment = os.environ if env is None else env
    configured = (environment.get(TEST_DATABASE_NAME_ENV) or "").strip()
    return configured or DEFAULT_TEST_DATABASE_NAME


def _scheme_family(scheme: str) -> str:
    """Collapse ``postgresql+psycopg`` and ``postgresql`` to one family."""
    base = (scheme or "").lower().split("+", 1)[0]
    return "postgresql" if base in _POSTGRES_SCHEME_FAMILY else base


def canonical_endpoint(url: str):
    """Return ``(family, host, port, database)`` - what a URL actually targets.

    Credentials, driver spelling, query parameters and their order are all
    discarded, because none of them change which bytes on which server get
    dropped. Comparing raw URL strings missed exactly that: ``postgresql://
    app:one@localhost:5432/pgx_test`` and ``postgresql+psycopg://
    test:two@localhost:5432/pgx_test`` are different strings and the same
    database.
    """
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host in _LOOPBACK_HOSTS:
        host = "localhost"
    try:
        port = parts.port
    except ValueError:
        port = None
    return (_scheme_family(parts.scheme), host, port or 5432,
            parts.path.lstrip("/"))


def _describe(endpoint) -> str:
    """A safe description of an endpoint: never a credential."""
    _family, host, port, database = endpoint
    return "%s:%s/%s" % (host, port, database or "<no database>")


def assert_is_test_database(url: str, env=None) -> None:
    """Refuse anything that is not exactly the configured test database.

    Two rules, both learned from a guard that was too permissive.

    **Exact name, never a substring.** The previous rule accepted any database
    whose name contained ``test`` or ``ci``. That accepted ``financial``
    (because of the ``ci`` in the middle), ``contest``, ``latest_production``
    and ``production_ci_backup`` - real databases, all of them cleared for
    destructive migration tests. The name must now equal
    :func:`expected_test_database_name` character for character.

    **Canonical endpoint, never string equality.** The previous rule refused
    ``TEST_DATABASE_URL`` only when it was byte-identical to ``DATABASE_URL``,
    so the same database reached through a different driver spelling or a
    different login sailed through. Both URLs are now reduced to
    ``(family, host, port, database)`` before comparison, with loopback
    spellings unified.

    No message raised here contains a credential: only host, port and database
    name are ever quoted.
    """
    environment = os.environ if env is None else env
    endpoint = canonical_endpoint(url)
    _family, _host, _port, database = endpoint
    expected = expected_test_database_name(env)

    if not database:
        raise TestDatabaseSafetyError(
            "TEST_DATABASE_URL names no database (target %s)."
            % _describe(endpoint))

    if database != expected:
        raise TestDatabaseSafetyError(
            "refusing to run destructive migration tests against database %r. "
            "The name must be exactly %r; a name that merely contains 'test' or "
            "'ci' is not accepted, because databases such as 'financial', "
            "'contest' and 'production_ci_backup' would qualify. Point "
            "TEST_DATABASE_URL at the disposable service, or set %s to the "
            "exact name of your CI database."
            % (database, expected, TEST_DATABASE_NAME_ENV))

    application_url = (environment.get("DATABASE_URL") or "").strip()
    if application_url and canonical_endpoint(application_url) == endpoint:
        raise TestDatabaseSafetyError(
            "TEST_DATABASE_URL and DATABASE_URL resolve to the same database "
            "(%s). Different credentials or a different driver spelling do not "
            "make them different databases. The test suite runs destructive "
            "migrations, so it must target a separate database."
            % _describe(endpoint))


def make_test_engine():
    """Create an engine bound to the validated test database."""
    require_postgres_dependencies()
    url = test_database_url()
    assert_is_test_database(url)

    from pgx.infrastructure.db.config import load_database_config
    from pgx.infrastructure.db.session import create_database_engine

    config = load_database_config(use_test_database=True)
    engine = create_database_engine(config)
    # Checked once more from the engine itself: the URL that was validated and
    # the URL the engine ended up with must be the same database.
    assert_engine_targets_test_database(engine)
    return engine


def alembic_config():
    """Alembic config pointed at the test database only."""
    require_postgres_dependencies()
    from alembic.config import Config

    url = test_database_url()
    assert_is_test_database(url)
    os.environ["PGX_ALEMBIC_USE_TEST_DATABASE"] = "1"
    config = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return config


def engine_endpoint(engine):
    """Canonical endpoint of a live engine, read from its URL fields.

    Built from the parsed components rather than a rendered string, so no
    password is materialised on the way to a comparison.
    """
    url = engine.url
    host = (url.host or "").lower()
    if host in _LOOPBACK_HOSTS:
        host = "localhost"
    return (_scheme_family(url.drivername), host, url.port or 5432,
            url.database or "")


def assert_engine_targets_test_database(engine, env=None) -> None:
    """Re-check the target from the engine itself, not from the environment.

    :func:`assert_is_test_database` validates the URL before an engine exists.
    This runs again immediately before anything destructive, so an engine built
    some other way - or handed in by a future caller - is still checked. A
    guard that only runs at construction time protects the wrong moment.
    """
    environment = os.environ if env is None else env
    endpoint = engine_endpoint(engine)
    _family, _host, _port, database = endpoint
    expected = expected_test_database_name(env)

    if database != expected:
        raise TestDatabaseSafetyError(
            "refusing to run a destructive statement against database %r; this "
            "suite may only touch %r." % (database, expected))

    application_url = (environment.get("DATABASE_URL") or "").strip()
    if application_url and canonical_endpoint(application_url) == endpoint:
        raise TestDatabaseSafetyError(
            "refusing to run a destructive statement against %s: it is the same "
            "database DATABASE_URL points at." % _describe(endpoint))


def unexpected_tables(engine) -> list:
    """Return public tables that are neither WP-02's nor Alembic's.

    A table from a later work package means this database is not the disposable
    WP-02 test database it is supposed to be. Cleaning up around it - or worse,
    dropping it with CASCADE - could destroy someone's work, so the suite stops
    instead.
    """
    from sqlalchemy import inspect

    known = set(ALL_TABLES) | {"alembic_version"}
    return sorted(name for name in inspect(engine).get_table_names()
                  if name not in known)


def assert_disposable_test_schema(engine) -> None:
    """Fail loudly if the target database holds anything WP-02 does not own."""
    unexpected = unexpected_tables(engine)
    if unexpected:
        raise TestDatabaseSafetyError(
            "the target database contains %d table(s) this work package does not "
            "own: %s. Integration tests run destructive migrations, so they refuse "
            "to operate on a database shared with other work. Point "
            "TEST_DATABASE_URL at the disposable `postgres-test` service "
            "(docker compose --profile test up -d postgres-test)."
            % (len(unexpected), ", ".join(unexpected)))


def drop_wp02_objects(engine) -> None:
    """Remove exactly the objects this work package creates.

    No ``CASCADE`` anywhere: a cascading drop would silently take dependent
    objects a later work package owns. Tables are dropped children-first, in
    the same order as the migration's ``downgrade()``, so ordinary foreign keys
    are satisfied without cascading.

    This is teardown for a disposable database. The schema lifecycle itself
    belongs to Alembic; this function only guarantees a clean slate between
    runs of a suite that may have been interrupted.
    """
    from sqlalchemy import text

    assert_engine_targets_test_database(engine)
    assert_disposable_test_schema(engine)

    ordered = (
        # WP-03 first: audit_events and active_release reference release_bundles,
        # which references the dataset and ruleset that WP-02 owns.
        "audit_events", "active_release", "release_bundles", "ruleset_rules",
        "ruleset_versions", "software_versions",
        # WP-02.
        "rule_evidence", "computable_rules", "interpretation_evidence",
        "curated_interpretations", "evidence_records", "drug_aliases", "drugs",
        "gene_aliases", "genes", "dataset_versions", "source_registry",
        "alembic_version",
    )
    with engine.begin() as connection:
        for table in ordered:
            connection.execute(text('DROP TABLE IF EXISTS "%s"' % table))


def clear_wp02_rows(engine) -> None:
    """Empty the WP-02 tables between tests, without CASCADE.

    ``DELETE`` in child-before-parent order rather than ``TRUNCATE ... CASCADE``:
    truncating with CASCADE would reach into any table that later references
    these, which is exactly the accident this function must not have.
    """
    from sqlalchemy import text

    assert_engine_targets_test_database(engine)

    ordered = (
        "audit_events", "active_release", "release_bundles", "ruleset_rules",
        "ruleset_versions", "software_versions",
        "rule_evidence", "computable_rules", "interpretation_evidence",
        "curated_interpretations", "evidence_records", "drug_aliases", "drugs",
        "gene_aliases", "genes", "dataset_versions", "source_registry",
    )
    with engine.begin() as connection:
        for table in ordered:
            if table == "active_release":
                # The singleton row is created by migration 0002 and must
                # survive: activation always locks *this* row. Reset it to its
                # bootstrap state instead of deleting it.
                connection.execute(text(
                    'UPDATE "active_release" SET release_id = NULL, '
                    "generation = 0, updated_by = 'system:test-reset'"))
                continue
            connection.execute(text('DELETE FROM "%s"' % table))


class PostgresTestCase(unittest.TestCase):
    """Base class that provisions the WP-02 schema on the test database."""

    engine = None

    @classmethod
    def setUpClass(cls):
        require_postgres_dependencies()
        from alembic import command

        cls.engine = make_test_engine()
        # Refuses to continue if the database holds anything WP-02 does not own.
        drop_wp02_objects(cls.engine)
        # The real Alembic chain owns schema creation; the suite never builds
        # the schema by hand.
        command.upgrade(alembic_config(), "head")

    @classmethod
    def tearDownClass(cls):
        if cls.engine is not None:
            drop_wp02_objects(cls.engine)
            cls.engine.dispose()

    def setUp(self):
        # Each test starts from empty tables, without re-running migrations and
        # without CASCADE.
        clear_wp02_rows(self.engine)
