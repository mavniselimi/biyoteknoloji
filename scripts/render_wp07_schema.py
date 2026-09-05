#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the WP-07 migration as plain SQL (stdlib only).

    python3 scripts/render_wp07_schema.py --out build/wp07-schema.sql

Same purpose and the same caveat as the WP-02, WP-03, WP-05 and WP-06
renderers: the Alembic migration is authoritative, and this reads its AST to
emit the equivalent DDL so the schema can be executed against a real PostgreSQL
server in an environment where Alembic and SQLAlchemy cannot be installed.
Because the SQL is *derived* rather than hand-maintained, the two cannot drift.

**This is not Alembic.** Running the rendered SQL proves the schema is valid
PostgreSQL and that its constraints behave as designed. It proves nothing about
Alembic's runner, its revision chain, or ``alembic_version`` stamping. WP-07
records those criteria as BLOCKED, and this renderer is supplementary evidence,
never a substitute.

Beyond the WP-06 renderer it also emits ``op.add_column`` as ``ALTER TABLE ...
ADD COLUMN``, and ``op.drop_constraint``/``op.create_check_constraint`` pairs in
source order rather than grouped, because ``0005`` performs one *narrowing*
constraint replacement whose two halves must run in the right order for the
executed schema to end up where the migration says it does.
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
    POSTGRES_IDENTIFIER_LIMIT, UnsupportedConstruct, over_length_identifiers,
)
from render_wp06_schema import _Wp06Renderer  # noqa: E402
from render_wp03_schema import _terminate  # noqa: E402

MIGRATION = os.path.join(
    _REPO_ROOT, "migrations", "versions", "0005_wp07_canonicalization.py")


class _Wp07Renderer(_Wp06Renderer):
    """The WP-06 renderer plus the constructs ``0005`` introduces.

    Subclassed rather than edited in place, for the same reason WP-06
    subclassed WP-03: the earlier renderers are frozen evidence tooling for
    earlier work packages.
    """

    def call(self, node: ast.Call):
        name = self.call_name(node)
        if name in ("sa.Text", "Text"):
            return "TEXT"
        return super().call(node)

    def render_alterations(self, upgrade: ast.FunctionDef) -> List[str]:
        """Return ``ALTER TABLE`` statements in the order the migration runs them.

        Order matters here in a way it did not in ``0004``. ``0005`` drops
        ``ck_dataset_versions_published_requires_approval`` and creates the
        narrower ``ck_dataset_versions_approval_requires_reviewer`` in its
        place; emitting those two out of order, or emitting a column's
        constraint before the column exists, would produce SQL that fails or -
        worse - succeeds while describing a different schema.
        """
        statements: List[str] = []
        for node in ast.walk(upgrade):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None)
            if name == "add_column":
                statements.append(self._add_column(node))
            elif name == "drop_constraint":
                constraint = self.value(node.args[0])
                table = self.value(node.args[1])
                statements.append(
                    "ALTER TABLE %s DROP CONSTRAINT %s;" % (table, constraint))
            elif name == "create_check_constraint":
                constraint = self.value(node.args[0])
                table = self.value(node.args[1])
                condition = self._condition(node.args[2])
                statements.append(
                    "ALTER TABLE %s ADD CONSTRAINT %s CHECK (%s);"
                    % (table, constraint, condition))
        return statements

    def _add_column(self, node: ast.Call) -> str:
        """Render one ``op.add_column(table, sa.Column(...))``."""
        table = self.value(node.args[0])
        column = node.args[1]
        if not isinstance(column, ast.Call):
            raise UnsupportedConstruct(
                "add_column expects an sa.Column(...) call")
        column_name = self.value(column.args[0])
        column_type = self.call(column.args[1]) if len(column.args) > 1 else None
        if column_type is None:
            raise UnsupportedConstruct(
                "add_column on %s.%s has no rendered type" % (table, column_name))
        nullable = True
        default = None
        for keyword in column.keywords:
            if keyword.arg == "nullable":
                nullable = bool(self.value(keyword.value))
            elif keyword.arg == "server_default":
                default = self._condition(keyword.value)
        parts = ["ALTER TABLE %s ADD COLUMN %s %s"
                 % (table, column_name, column_type)]
        if default is not None:
            parts.append("DEFAULT %s" % default)
        if not nullable:
            parts.append("NOT NULL")
        return " ".join(parts) + ";"

    def render_downgrade(self, downgrade: ast.FunctionDef) -> List[str]:
        """Render ``downgrade()`` in source order.

        Rendered rather than hand-written for the same reason ``upgrade()`` is:
        a hand-maintained down path drifts from the migration silently, and the
        first person to discover the drift is the one trying to roll back. Every
        operation appears in the order the migration performs it, because
        dropping a table before the rows that reference it, or a column before
        its constraint, fails.
        """
        statements: List[str] = []
        for node in ast.walk(downgrade):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None)
            if name == "execute":
                statements.append(_terminate(self.value(node.args[0])))
            elif name == "drop_constraint":
                statements.append(
                    "ALTER TABLE %s DROP CONSTRAINT %s;"
                    % (self.value(node.args[1]), self.value(node.args[0])))
            elif name == "create_check_constraint":
                statements.append(
                    "ALTER TABLE %s ADD CONSTRAINT %s CHECK (%s);"
                    % (self.value(node.args[1]), self.value(node.args[0]),
                       self._condition(node.args[2])))
            elif name == "drop_index":
                statements.append("DROP INDEX %s;" % self.value(node.args[0]))
            elif name == "drop_table":
                statements.append("DROP TABLE %s;" % self.value(node.args[0]))
            elif name == "drop_column":
                statements.append(
                    "ALTER TABLE %s DROP COLUMN %s;"
                    % (self.value(node.args[0]), self.value(node.args[1])))
        return statements


def render_schema(migration_path: str = MIGRATION,
                  direction: str = "upgrade") -> str:
    """Return the SQL rendering of one direction of the WP-07 migration."""
    with io.open(migration_path, encoding="utf-8") as handle:
        module = ast.parse(handle.read(), filename=migration_path)
    functions = {node.name: node for node in module.body
                 if isinstance(node, ast.FunctionDef)}
    if direction == "downgrade":
        downgrade = functions.get("downgrade")
        if downgrade is None:
            raise UnsupportedConstruct("no downgrade() function found")
        renderer = _Wp07Renderer(module)
        header = (
            "-- WP-07 downgrade: remove exactly the 0005 objects.\n"
            "-- GENERATED from migrations/versions/0005_wp07_canonicalization.py\n"
            "-- by scripts/render_wp07_schema.py --direction downgrade.\n"
            "-- Refused on a database holding a DATASET_QUALITY_CHECKED audit\n"
            "-- event: restoring the six-value constraint would fail, and the\n"
            "-- audit trail is append-only. That refusal is correct.\n")
        return header + "\n" + "\n\n".join(
            renderer.render_downgrade(downgrade)) + "\n"

    upgrade = functions.get("upgrade")
    if upgrade is None:
        raise UnsupportedConstruct("no upgrade() function found")

    renderer = _Wp07Renderer(module)
    alterations = renderer.render_alterations(upgrade)
    tables = renderer.render(ast.Module(body=[upgrade], type_ignores=[]))
    executes = renderer.render_executes(upgrade)
    header = (
        "-- WP-07 canonical build, alias review, resolution queue and\n"
        "-- duplicate schema.\n"
        "-- GENERATED from migrations/versions/0005_wp07_canonicalization.py by\n"
        "-- scripts/render_wp07_schema.py. Do not edit by hand: the migration is\n"
        "-- authoritative and this file is regenerated from it.\n"
        "-- Requires the WP-02 (0001), WP-03 (0002), WP-05 (0003) and\n"
        "-- WP-06 (0004) schemas.\n"
    )
    # Column additions and constraint replacements first: the alias constraints
    # cannot be created before their columns exist, and the dataset approval
    # replacement must land before anything is inserted against it.
    body = "\n\n".join(alterations + tables
                       + [_terminate(sql) for sql in executes])
    return header + "\n" + body + "\n"


def main(argv: Optional[list] = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="render_wp07_schema.py",
        description="Render the WP-07 migration as executable PostgreSQL DDL.")
    parser.add_argument("--out", default=None,
                        help="Write SQL here instead of stdout.")
    parser.add_argument("--check-identifiers", action="store_true",
                        help="Fail if any identifier exceeds PostgreSQL's "
                             "63-byte limit.")
    parser.add_argument("--direction", choices=("upgrade", "downgrade"),
                        default="upgrade",
                        help="Which direction of the migration to render.")
    args = parser.parse_args(argv)

    try:
        sql = render_schema(direction=args.direction)
    except UnsupportedConstruct as exc:
        sys.stderr.write("RENDER_FAILURE: %s\n" % exc)
        return 2

    too_long = over_length_identifiers(sql)
    if too_long:
        sys.stderr.write(
            "IDENTIFIER_TOO_LONG: PostgreSQL truncates identifiers at %d bytes, "
            "which would break downgrade(): %s\n"
            % (POSTGRES_IDENTIFIER_LIMIT, ", ".join(too_long)))
        if args.check_identifiers:
            return 3

    if args.out:
        directory = os.path.dirname(os.path.abspath(args.out))
        if directory:
            os.makedirs(directory, exist_ok=True)
        with io.open(args.out, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(sql)
        sys.stdout.write("wrote %s (%d statements)\n"
                         % (args.out, sql.count("CREATE") + sql.count("ALTER")))
    else:
        sys.stdout.write(sql)
    return 0


if __name__ == "__main__":
    sys.exit(main())
