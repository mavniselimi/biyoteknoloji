# -*- coding: utf-8 -*-
"""Alembic environment (WP-02).

Importing this module opens no connection: the URL is read from the
environment, and a connection is established only when Alembic actually runs a
migration. ``alembic.ini`` holds no credential.

Set ``PGX_ALEMBIC_USE_TEST_DATABASE=1`` to target ``TEST_DATABASE_URL`` instead
of ``DATABASE_URL``. Integration tests always set it, so a test run can never
migrate the application database.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from pgx.infrastructure.db.base import metadata as target_metadata  # noqa: E402
from pgx.infrastructure.db.config import (  # noqa: E402
    DatabaseConfigurationError,
    load_database_config,
)
# Every module that defines mapped classes has to be imported here, not just
# the largest one. ``target_metadata`` is what Alembic compares the database
# against, and a table whose module was never imported is a table autogenerate
# would propose *dropping* - which is how a hand-written migration's tables
# get silently reverted by a generated one.
#
# WP-22's seven review tables were missing from this list; WP-23's five are
# added at the same time rather than repeating the omission.
import pgx.infrastructure.db.models  # noqa: E402,F401  (release, curation, rules, assessments)
import pgx.infrastructure.db.expert_reviews  # noqa: E402,F401  (WP-22)
import pgx.infrastructure.db.security  # noqa: E402,F401  (WP-23)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _resolve_url() -> str:
    """Return the database URL, or fail with an explicit configuration error."""
    use_test = os.environ.get("PGX_ALEMBIC_USE_TEST_DATABASE", "").strip() in (
        "1", "true", "yes", "on")
    try:
        settings = load_database_config(use_test_database=use_test)
    except DatabaseConfigurationError as exc:
        raise SystemExit("alembic: %s" % exc) from exc
    return settings.url


def run_migrations_offline() -> None:
    """Emit SQL without connecting (``alembic upgrade --sql``)."""
    context.configure(
        url=_resolve_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _resolve_url()
    connectable = engine_from_config(
        section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
