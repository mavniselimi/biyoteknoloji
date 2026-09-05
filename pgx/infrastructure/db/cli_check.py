# -*- coding: utf-8 -*-
"""Database connectivity and schema report (WP-02).

Console entry point: ``pgx-db-check``.

This module is the single implementation; ``scripts/db_check.py`` delegates
here. Read-only: it connects, reports the server version, the Alembic revision,
and which WP-02 foundation tables exist. It creates nothing, drops nothing, and
never prints a credential.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional

EXPECTED_TABLES = (
    "source_registry", "dataset_versions", "genes", "gene_aliases", "drugs",
    "drug_aliases", "evidence_records", "curated_interpretations",
    "interpretation_evidence", "computable_rules", "rule_evidence",
)

EXIT_OK = 0
EXIT_INCOMPLETE_SCHEMA = 1
EXIT_CONFIGURATION_FAILURE = 2


def run_check(database_url_env: str = "DATABASE_URL") -> Dict[str, Any]:
    """Return a machine-readable connectivity and schema report."""
    from sqlalchemy import inspect, text

    from pgx.infrastructure.db.config import load_database_config
    from pgx.infrastructure.db.session import create_database_engine, verify_connectivity

    use_test = database_url_env == "TEST_DATABASE_URL"
    config = load_database_config(use_test_database=use_test)
    engine = create_database_engine(config)
    try:
        server_version = verify_connectivity(engine)
        inspector = inspect(engine)
        present = set(inspector.get_table_names())
        revision: Optional[str] = None
        if "alembic_version" in present:
            with engine.connect() as connection:
                row = connection.execute(
                    text("SELECT version_num FROM alembic_version")).first()
                revision = None if row is None else str(row[0])
        missing = [name for name in EXPECTED_TABLES if name not in present]
        return {
            "database": config.safe_url,
            "source_env_var": config.source_env_var,
            "server_version": server_version,
            "alembic_revision": revision,
            "expected_tables": list(EXPECTED_TABLES),
            "missing_tables": missing,
            "schema_complete": not missing,
        }
    finally:
        engine.dispose()


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point for ``pgx-db-check``."""
    from pgx.infrastructure.db.config import sanitize_message

    parser = argparse.ArgumentParser(
        prog="pgx-db-check",
        description="Report PostgreSQL connectivity and WP-02 schema state.")
    parser.add_argument("--database-url-env", default="DATABASE_URL",
                        choices=["DATABASE_URL", "TEST_DATABASE_URL"])
    args = parser.parse_args(argv)
    try:
        report = run_check(args.database_url_env)
    except Exception as exc:  # noqa: BLE001 - surfaced as a precise CLI failure
        sys.stderr.write("DB_CHECK_FAILURE: %s: %s\n"
                         % (type(exc).__name__, sanitize_message(str(exc))))
        return EXIT_CONFIGURATION_FAILURE
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return EXIT_OK if report["schema_complete"] else EXIT_INCOMPLETE_SCHEMA


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
