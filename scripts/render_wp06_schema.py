#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the WP-06 migration as plain SQL (stdlib only).

    python3 scripts/render_wp06_schema.py --out build/wp06-schema.sql

Same purpose and the same caveat as the WP-02, WP-03 and WP-05 renderers: the
Alembic migration is authoritative, and this reads its AST to emit the
equivalent DDL so the schema can be executed against a real PostgreSQL server in
an environment where Alembic and SQLAlchemy cannot be installed. Because the SQL
is *derived* rather than hand-maintained, the two cannot drift.

**This is not Alembic.** Running the rendered SQL proves the schema is valid
PostgreSQL and that its constraints behave as designed. It proves nothing about
Alembic's runner, its revision chain, or ``alembic_version`` stamping. WP-06
records those criteria as BLOCKED, and this renderer is supplementary evidence,
never a substitute.

Beyond the earlier renderers it also emits the two constraint operations
``0004`` uses to widen the audit-action list, and the identity-immutability
trigger with its function. A renderer that skipped either would produce a schema
missing exactly the mechanisms WP-06 depends on.
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
from render_wp03_schema import _Wp03Renderer, _terminate  # noqa: E402

MIGRATION = os.path.join(
    _REPO_ROOT, "migrations", "versions", "0004_wp06_raw_snapshots.py")


class _Wp06Renderer(_Wp03Renderer):
    """The WP-03 renderer plus the constructs ``0004`` introduces.

    Subclassed rather than editing the earlier renderers: those are frozen
    tooling for earlier work packages, and changing one to serve a later
    migration would put WP-06's needs inside WP-02's evidence chain.
    """

    def call(self, node: ast.Call):
        if self.call_name(node) == "_jsonb":
            return "JSONB"
        if self.call_name(node) in ("sa.BigInteger", "BigInteger"):
            return "BIGINT"
        return super().call(node)

    def render_constraint_changes(self, upgrade: ast.FunctionDef) -> List[str]:
        """Return the ``ALTER TABLE`` statements behind constraint operations.

        ``0004`` drops one check constraint and recreates it with one more
        permitted value. Both halves are emitted, in order, so the executed
        schema really does admit the new audit action - which is the only way
        an executed-schema test of it can mean anything.
        """
        statements: List[str] = []
        for node in ast.walk(upgrade):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None)
            if name == "drop_constraint":
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

    def _condition(self, node: ast.AST) -> str:
        """Unwrap ``sa.text("...")`` around a check-constraint condition."""
        if isinstance(node, ast.Call) and self.call_name(node) in ("sa.text",
                                                                   "text"):
            return self.value(node.args[0])
        value = self.value(node)
        if isinstance(value, dict) and "__sql__" in value:
            return value["__sql__"]
        return str(value)


def render_schema(migration_path: str = MIGRATION) -> str:
    """Return the SQL rendering of the WP-06 migration's ``upgrade()``."""
    with io.open(migration_path, encoding="utf-8") as handle:
        module = ast.parse(handle.read(), filename=migration_path)
    upgrade = None
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == "upgrade":
            upgrade = node
    if upgrade is None:
        raise UnsupportedConstruct("no upgrade() function found")

    renderer = _Wp06Renderer(module)
    tables = renderer.render(ast.Module(body=[upgrade], type_ignores=[]))
    constraints = renderer.render_constraint_changes(upgrade)
    executes = renderer.render_executes(upgrade)
    header = (
        "-- WP-06 immutable raw snapshot schema.\n"
        "-- GENERATED from migrations/versions/0004_wp06_raw_snapshots.py by\n"
        "-- scripts/render_wp06_schema.py. Do not edit by hand: the migration is\n"
        "-- authoritative and this file is regenerated from it.\n"
        "-- Requires the WP-02 (0001), WP-03 (0002) and WP-05 (0003) schemas.\n"
    )
    body = "\n\n".join(tables + constraints
                       + [_terminate(sql) for sql in executes])
    return header + "\n" + body + "\n"


def main(argv: Optional[list] = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="render_wp06_schema.py",
        description="Render the WP-06 migration as executable PostgreSQL DDL.")
    parser.add_argument("--out", default=None, help="Write SQL here instead of stdout.")
    parser.add_argument("--check-identifiers", action="store_true",
                        help="Fail if any identifier exceeds PostgreSQL's 63-byte limit.")
    args = parser.parse_args(argv)

    try:
        sql = render_schema()
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
