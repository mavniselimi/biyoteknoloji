#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the WP-10 migration as plain SQL (stdlib only).

    python3 scripts/render_wp10_schema.py --out build/wp10-schema.sql
    python3 scripts/render_wp10_schema.py --direction downgrade

Same purpose and the same caveat as the WP-02 through WP-08 renderers: the
Alembic migration is authoritative, and this reads its AST to emit the
equivalent DDL so the schema can be executed against a real PostgreSQL server
in an environment where Alembic and SQLAlchemy cannot be installed. Because the
SQL is *derived* rather than hand-maintained, the two cannot drift.

**This is not Alembic.** Running the rendered SQL proves the schema is valid
PostgreSQL and that its constraints and triggers behave as designed. It proves
nothing about Alembic's runner, its revision chain, or ``alembic_version``
stamping. WP-10 records those criteria as BLOCKED for the same reason WP-02
through WP-08 did, and this renderer is supplementary evidence, never a
substitute.

Beyond the WP-08 renderer, one thing changes: ``0007``'s downgrade opens with a
``DO $$ ... $$`` guard that refuses to proceed on a database holding real
curation decisions. It must be emitted **first**, before any drop. The WP-08
ordering ranked anonymous blocks last, which would have produced SQL that
dropped every table and then checked whether it should have.
"""

from __future__ import annotations

import argparse
import ast
import io
import os
import sys
from typing import List, Optional

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPTS_DIR)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from render_wp02_schema import (  # noqa: E402
    UnsupportedConstruct, over_length_identifiers,
)
from render_wp03_schema import _terminate  # noqa: E402
from render_wp08_schema import (  # noqa: E402
    _Wp08Renderer, _transactional, _upgrade_order,
)

MIGRATION = os.path.join(
    _REPO_ROOT, "migrations", "versions", "0007_wp10_curation_workflow.py")


class _Wp10Renderer(_Wp08Renderer):
    """The WP-08 renderer, unchanged.

    ``0007`` introduces no operation the WP-08 renderer cannot already emit:
    seven ``create_table`` calls, indexes, a constraint drop-and-recreate on
    ``audit_events``, and ``op.execute`` for the functions and triggers. It is
    subclassed rather than reused directly so that a future WP-10 change has
    somewhere to go that is not inside WP-08's evidence tooling.
    """


def _downgrade_order_wp10(statements: List[str]) -> List[str]:
    """Mirror of the upgrade, with the refusal guard first.

    The guard is an anonymous ``DO`` block that raises when the database holds
    decided work items, reviews or adjudications. It has to run before the
    first ``DROP``: a refusal that arrives after the tables are gone has
    refused nothing. Everything else keeps the WP-08 ranking.
    """
    def rank(statement: str) -> int:
        if statement.lstrip().startswith("DO $$"):
            return 0
        if statement.startswith("DROP TRIGGER"):
            return 1
        if statement.startswith("DROP FUNCTION"):
            return 2
        if statement.startswith("DROP INDEX"):
            return 3
        if "DROP CONSTRAINT" in statement:
            return 4
        if "DROP COLUMN" in statement:
            return 5
        if statement.startswith("DROP TABLE"):
            return 6
        if "ALTER COLUMN" in statement:
            return 7
        if "ADD CONSTRAINT" in statement:
            return 8
        return 9
    return sorted(statements, key=rank)


def render_schema(migration_path: str = MIGRATION,
                  direction: str = "upgrade") -> str:
    """Return the SQL rendering of one direction of the WP-10 migration."""
    with io.open(migration_path, encoding="utf-8") as handle:
        module = ast.parse(handle.read(), filename=migration_path)
    functions = {node.name: node for node in module.body
                 if isinstance(node, ast.FunctionDef)}
    renderer = _Wp10Renderer(module)

    if direction == "downgrade":
        downgrade = functions.get("downgrade")
        if downgrade is None:
            raise UnsupportedConstruct("no downgrade() function found")
        header = (
            "-- WP-10 downgrade: remove exactly the 0007 objects.\n"
            "-- GENERATED from migrations/versions/0007_wp10_curation_workflow.py\n"
            "-- by scripts/render_wp10_schema.py --direction downgrade.\n"
            "-- Refused on a database holding a decided work item, a review or\n"
            "-- an adjudication: those rows are the only record that named\n"
            "-- people reached a scientific conclusion, and no migration should\n"
            "-- destroy that on an operator's behalf.\n"
            "-- Wrapped in one transaction so the refusal is total: the guard\n"
            "-- raises before the first DROP, and nothing is left half-gone.\n")
        statements: List[str] = []
        for node in ast.walk(downgrade):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None)
            if name == "execute":
                statements.append(_terminate(renderer.value(node.args[0])))
            elif name == "drop_index":
                statements.append("DROP INDEX %s;"
                                  % renderer.value(node.args[0]))
            elif name == "drop_table":
                statements.append("DROP TABLE %s;"
                                  % renderer.value(node.args[0]))
        statements.extend(renderer.render_alterations(downgrade))
        return _transactional(
            header, "\n\n".join(_downgrade_order_wp10(statements)))

    upgrade = functions.get("upgrade")
    if upgrade is None:
        raise UnsupportedConstruct("no upgrade() function found")

    alterations = renderer.render_alterations(upgrade)
    tables = renderer.render(ast.Module(body=[upgrade], type_ignores=[]))
    executes = renderer.render_executes(upgrade)
    header = (
        "-- WP-10 curation workflow: work items, revisions, reviews,\n"
        "-- adjudication, provenance verification and role assignments.\n"
        "-- GENERATED from migrations/versions/0007_wp10_curation_workflow.py\n"
        "-- by scripts/render_wp10_schema.py. Do not edit by hand: the\n"
        "-- migration is authoritative and this file is regenerated from it.\n"
        "-- Requires the WP-02 (0001) through WP-08 (0006) schemas.\n"
        "-- curation_role_assignments is created empty and stays empty: this\n"
        "-- project has no authenticated identity to assign a role to.\n"
        "-- Wrapped in one transaction, as Alembic runs upgrade().\n")
    body = "\n\n".join(_upgrade_order(tables + alterations)
                       + [_terminate(sql) for sql in executes])
    return _transactional(header, body)


def main(argv: Optional[list] = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="render_wp10_schema.py",
        description="Render the WP-10 migration as executable PostgreSQL DDL.")
    parser.add_argument("--migration", default=MIGRATION)
    parser.add_argument("--direction", default="upgrade",
                        choices=("upgrade", "downgrade"))
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    sql = render_schema(args.migration, args.direction)
    offenders = over_length_identifiers(sql)
    if offenders:
        sys.stderr.write(
            "identifiers exceeding PostgreSQL's limit would be silently "
            "truncated: %s\n" % ", ".join(sorted(offenders)))
        return 2

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with io.open(args.out, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(sql)
        sys.stdout.write("wrote %s (%d bytes)\n" % (args.out, len(sql)))
    else:
        sys.stdout.write(sql)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
