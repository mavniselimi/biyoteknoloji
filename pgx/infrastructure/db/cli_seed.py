# -*- coding: utf-8 -*-
"""Deterministic foundation seed (WP-02).

Console entry point: ``pgx-db-seed``.

This module is the single implementation. ``scripts/db_seed.py`` is a thin
wrapper that delegates here, so the logic exists once and the installed package
owns it.

Seeds exactly one technical bookkeeping row: the ``pgx-internal-system`` source
registry entry that later work packages attach non-scientific records to.

What this seed is **not**:

* not a scientific source, and not ClinPGx;
* not usable as release evidence — ``release_eligible`` is ``false`` and the
  database refuses to make an ``INTERNAL_SYSTEM`` source release-eligible;
* not an expression of scientific validation or approval;
* not an import of legacy genes, drugs, evidence, rules, or demo profiles.

Determinism and idempotency:

* identity is a fixed UUID5, so the row has the same id in every environment;
* the canonical payload hash is identical on every run and in every process;
* a second run creates nothing and reports ``created_count = 0``;
* if the stored row has drifted from the canonical payload — **including its
  ``created_at`` timestamp** — the seed reports the drift and refuses to
  overwrite it.

No credential ever reaches stdout, stderr, or an exception message: the URL is
read from an environment variable and only its redacted form is printed.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from typing import Any, Dict, List, Optional

SEED_SCHEMA_VERSION = "wp02-foundation-seed/2"

#: Fixed technical key. The UUID5 derived from it is the row's identity.
INTERNAL_SYSTEM_SOURCE_KEY = "pgx-internal-system"

#: Fixed creation instant, so the canonical payload never depends on wall-clock
#: time. A run-dependent timestamp would make the seed hash unstable and would
#: make timestamp drift undetectable.
SEED_EPOCH = _dt.datetime(2026, 1, 1, 0, 0, 0, tzinfo=_dt.timezone.utc)

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_CONFIGURATION_FAILURE = 2

#: Fields compared when deciding whether the stored row has drifted. Unlike the
#: first WP-02 draft, ``created_at`` is included: a changed timestamp is a real
#: change to a row whose whole purpose is to be reproducible.
_COMPARED_FIELDS = (
    "source_key", "display_name", "role", "version_policy", "license_policy",
    "citation_policy", "release_eligible", "active", "created_at",
)


def _canonical_seed_payload() -> Dict[str, Any]:
    """The exact record this seed guarantees. Pure data, no I/O."""
    return {
        "source_key": INTERNAL_SYSTEM_SOURCE_KEY,
        "display_name": "PGx Platform internal system",
        "role": "INTERNAL_SYSTEM",
        "version_policy": "NOT_APPLICABLE_INTERNAL",
        "license_policy": "NOT_APPLICABLE_INTERNAL",
        "citation_policy": "NOT_APPLICABLE_INTERNAL",
        "release_eligible": False,
        "active": True,
        "created_at": SEED_EPOCH,
    }


def canonical_seed_manifest() -> Dict[str, Any]:
    """Return the deterministic seed manifest without touching a database.

    Importable and testable on its own: the hash can be verified with no
    PostgreSQL available and no driver installed.
    """
    from pgx.domain.hashing import sha256_digest
    from pgx.domain.identifiers import SourceRegistryEntryId

    payload = _canonical_seed_payload()
    entry_id = SourceRegistryEntryId.derive(INTERNAL_SYSTEM_SOURCE_KEY)
    record = dict(payload, id=entry_id.to_json())
    return {
        "seed_schema_version": SEED_SCHEMA_VERSION,
        "records": [record],
        "canonical_payload_hash": sha256_digest(
            {"seed_schema_version": SEED_SCHEMA_VERSION, "records": [record]}),
    }


def build_seed_entry() -> Any:
    """Build the domain object this seed guarantees."""
    from pgx.domain.enums import SourceRole
    from pgx.domain.identifiers import SourceRegistryEntryId
    from pgx.domain.models import SourceRegistryEntry

    payload = _canonical_seed_payload()
    return SourceRegistryEntry(
        id=SourceRegistryEntryId.derive(INTERNAL_SYSTEM_SOURCE_KEY),
        source_key=payload["source_key"],
        display_name=payload["display_name"],
        role=SourceRole(payload["role"]),
        version_policy=payload["version_policy"],
        license_policy=payload["license_policy"],
        citation_policy=payload["citation_policy"],
        release_eligible=payload["release_eligible"],
        active=payload["active"],
        created_at=payload["created_at"],
    )


def _normalized_utc(value: _dt.datetime) -> str:
    """Return an explicit, deterministic UTC spelling for comparison.

    Both sides of the drift check go through this, so a row stored in another
    session's timezone compares equal when it denotes the same instant, and
    unequal when it does not.
    """
    from pgx.domain.hashing import ensure_utc

    return ensure_utc(value, "created_at").isoformat().replace("+00:00", "Z")


def comparable_fields(entry: Any) -> Dict[str, Any]:
    """Return the field values that define drift, including ``created_at``."""
    values: Dict[str, Any] = {
        "source_key": entry.source_key,
        "display_name": entry.display_name,
        "role": entry.role.value,
        "version_policy": entry.version_policy,
        "license_policy": entry.license_policy,
        "citation_policy": entry.citation_policy,
        "release_eligible": entry.release_eligible,
        "active": entry.active,
        "created_at": _normalized_utc(entry.created_at),
    }
    return {field: values[field] for field in _COMPARED_FIELDS}


def detect_drift(expected: Any, stored: Any) -> List[Dict[str, Any]]:
    """Return every field where the stored row differs from the canonical one."""
    drift: List[Dict[str, Any]] = []
    if stored.id != expected.id:
        drift.append({"field": "id", "expected": expected.id.to_json(),
                      "stored": stored.id.to_json()})
    expected_fields = comparable_fields(expected)
    stored_fields = comparable_fields(stored)
    for field in _COMPARED_FIELDS:
        if stored_fields[field] != expected_fields[field]:
            drift.append({"field": field, "expected": expected_fields[field],
                          "stored": stored_fields[field]})
    return drift


def run_seed(database_url_env: str = "DATABASE_URL",
             dry_run: bool = False) -> Dict[str, Any]:
    """Apply the seed idempotently and return a machine-readable report."""
    from sqlalchemy import text

    from pgx.infrastructure.db.config import load_database_config
    from pgx.infrastructure.db.session import (
        create_database_engine, create_session_factory,
    )
    from pgx.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

    use_test = database_url_env == "TEST_DATABASE_URL"
    config = load_database_config(use_test_database=use_test)
    engine = create_database_engine(config)
    manifest = canonical_seed_manifest()
    expected = build_seed_entry()

    created = 0
    already_present = 0
    drift: List[Dict[str, Any]] = []
    revision: Optional[str] = None

    try:
        with engine.connect() as connection:
            row = connection.execute(
                text("SELECT version_num FROM alembic_version")).first()
            revision = None if row is None else str(row[0])

        factory = create_session_factory(engine)
        with SqlAlchemyUnitOfWork(factory) as uow:
            stored = uow.source_registry.get_by_source_key(INTERNAL_SYSTEM_SOURCE_KEY)
            if stored is None:
                if not dry_run:
                    uow.source_registry.add(expected)
                created = 1
            else:
                already_present = 1
                drift = detect_drift(expected, stored)
            if drift:
                # Never silently overwrite content somebody changed.
                uow.rollback()
            elif not dry_run:
                uow.commit()
    finally:
        engine.dispose()

    return {
        "seed_schema_version": SEED_SCHEMA_VERSION,
        "canonical_payload_hash": manifest["canonical_payload_hash"],
        "created_count": 0 if dry_run else created,
        "already_present_count": already_present,
        "drift_count": len(drift),
        "drift": drift,
        "database_schema_revision": revision,
        "database": config.safe_url,
        "dry_run": dry_run,
        "scientific_rows_created": 0,
        "compared_fields": list(_COMPARED_FIELDS),
        "note": (
            "Technical bookkeeping only. This row is not a scientific source, "
            "carries no validation or approval, and is not release evidence."
        ),
    }


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point for ``pgx-db-seed``."""
    from pgx.infrastructure.db.config import sanitize_message

    parser = argparse.ArgumentParser(
        prog="pgx-db-seed",
        description="Apply the deterministic WP-02 foundation seed (idempotent).")
    parser.add_argument(
        "--database-url-env", default="DATABASE_URL",
        choices=["DATABASE_URL", "TEST_DATABASE_URL"],
        help="Environment variable holding the PostgreSQL URL. The URL itself is "
             "never accepted on the command line, so it cannot reach the process "
             "list or shell history.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing.")
    parser.add_argument("--print-manifest", action="store_true",
                        help="Print the canonical seed manifest and exit. Makes no "
                             "database connection and needs no driver.")
    args = parser.parse_args(argv)

    if args.print_manifest:
        sys.stdout.write(json.dumps(canonical_seed_manifest(), indent=2,
                                    sort_keys=True, default=str) + "\n")
        return EXIT_OK

    try:
        report = run_seed(args.database_url_env, dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001 - surfaced as a precise CLI failure
        # sanitize_message strips any credential the driver may have echoed
        # back inside its error text.
        sys.stderr.write("SEED_FAILURE: %s: %s\n"
                         % (type(exc).__name__, sanitize_message(str(exc))))
        return EXIT_CONFIGURATION_FAILURE

    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    if report["drift_count"]:
        sys.stderr.write(
            "SEED_DRIFT: the stored foundation row differs from the canonical "
            "payload in %d field(s): %s. Nothing was overwritten. Resolve it "
            "deliberately.\n"
            % (report["drift_count"],
               ", ".join(item["field"] for item in report["drift"])))
        return EXIT_DRIFT
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
