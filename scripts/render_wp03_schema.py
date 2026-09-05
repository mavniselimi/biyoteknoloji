#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the WP-03 migration as plain SQL (stdlib only).

    python3 scripts/render_wp03_schema.py --out build/wp03-schema.sql

Same purpose and the same caveat as ``scripts/render_wp02_schema.py``: the
Alembic migration is authoritative, and this reads its AST to emit the
equivalent DDL so the schema can be executed against a real PostgreSQL server
in an environment where Alembic and SQLAlchemy cannot be installed. Because the
SQL is *derived* rather than hand-maintained, the two cannot drift.

**This is not Alembic.** Running the rendered SQL proves the schema is valid
PostgreSQL and that its constraints behave as designed. It proves nothing about
Alembic's runner, its revision chain, or ``alembic_version`` stamping. WP-03
records those criteria as BLOCKED, and this renderer is supplementary evidence,
never a substitute.

Beyond the WP-02 renderer it also emits what ``0002`` adds through
``op.execute``: the singleton pointer row, and the append-only trigger with its
function. A renderer that silently skipped those would produce a schema missing
exactly the two mechanisms WP-03 depends on.
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
    POSTGRES_IDENTIFIER_LIMIT, UnsupportedConstruct, _Renderer,
    over_length_identifiers,
)

MIGRATION = os.path.join(
    _REPO_ROOT, "migrations", "versions", "0002_wp03_release_registry.py")


class _Wp03Renderer(_Renderer):
    """The WP-02 renderer plus the ``op.execute`` forms ``0002`` uses."""

    def render_executes(self, upgrade: ast.FunctionDef) -> List[str]:
        """Return the SQL behind each ``op.execute(...)`` in ``upgrade()``.

        Two forms appear, and both are resolved rather than skipped:

        * ``op.execute(MODULE_CONSTANT)`` - the trigger and its function;
        * ``op.execute(sa.text("...").bindparams(k=v))`` - the singleton row,
          whose parameters are substituted here so the rendered SQL is
          executable on its own.
        """
        statements: List[str] = []
        for node in ast.walk(upgrade):
            if not isinstance(node, ast.Call):
                continue
            if self.call_name(node) != "op.execute":
                continue
            statements.append(self._execute_sql(node.args[0]))
        return statements

    def _execute_sql(self, argument: ast.AST) -> str:
        # op.execute("literal") or op.execute(MODULE_CONSTANT)
        if isinstance(argument, (ast.Constant, ast.Name)):
            return str(self.value(argument)).strip()

        # op.execute(sa.text("...").bindparams(name=value))
        if isinstance(argument, ast.Call):
            # ``sa.text(...).bindparams(...)`` chains a call onto a call, so
            # call_name() sees only the trailing attribute.
            name = self.call_name(argument).split(".")[-1]
            if name == "bindparams":
                inner = argument.func.value  # type: ignore[attr-defined]
                sql = str(self.value(inner.args[0])).strip()
                for keyword in argument.keywords:
                    literal = self.value(keyword.value)
                    rendered = ("'%s'" % literal if isinstance(literal, str)
                                else str(literal))
                    sql = sql.replace(":%s" % keyword.arg, rendered)
                return sql
            if name == "text":
                return str(self.value(argument.args[0])).strip()
        raise UnsupportedConstruct(
            "unsupported op.execute argument: %s" % ast.dump(argument)[:120])


def render_schema(migration_path: str = MIGRATION) -> str:
    """Return the SQL rendering of the WP-03 migration's ``upgrade()``."""
    with io.open(migration_path, encoding="utf-8") as handle:
        module = ast.parse(handle.read(), filename=migration_path)
    upgrade = None
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == "upgrade":
            upgrade = node
    if upgrade is None:
        raise UnsupportedConstruct("no upgrade() function found")

    renderer = _Wp03Renderer(module)
    tables = renderer.render(ast.Module(body=[upgrade], type_ignores=[]))
    executes = renderer.render_executes(upgrade)
    header = (
        "-- WP-03 release registry schema.\n"
        "-- GENERATED from migrations/versions/0002_wp03_release_registry.py by\n"
        "-- scripts/render_wp03_schema.py. Do not edit by hand: the migration is\n"
        "-- authoritative and this file is regenerated from it.\n"
        "-- Requires the WP-02 schema (0001) to be present first.\n"
    )
    body = "\n\n".join(tables + [_terminate(sql) for sql in executes])
    return header + "\n" + body + "\n"


def _terminate(sql: str) -> str:
    """Ensure a rendered statement ends with a semicolon."""
    return sql if sql.rstrip().endswith(";") else sql.rstrip() + ";"


def main(argv: Optional[list] = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="render_wp03_schema.py",
        description="Render the WP-03 migration as executable PostgreSQL DDL.")
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
        statements = sql.count(";\n") + sql.count(";\n\n")
        sys.stdout.write("wrote %s (%d statements)\n"
                         % (args.out, sql.count("CREATE") + sql.count("INSERT")))
    else:
        sys.stdout.write(sql)
    return 0


if __name__ == "__main__":
    sys.exit(main())
