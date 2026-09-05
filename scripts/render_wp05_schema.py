#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the WP-05 migration as plain SQL (stdlib only).

    python3 scripts/render_wp05_schema.py --out build/wp05-schema.sql

Same purpose and the same caveat as ``scripts/render_wp02_schema.py`` and
``scripts/render_wp03_schema.py``: the Alembic migration is authoritative, and
this reads its AST to emit the equivalent DDL so the schema can be executed
against a real PostgreSQL server in an environment where Alembic and SQLAlchemy
cannot be installed. Because the SQL is *derived* rather than hand-maintained,
the two cannot drift.

**This is not Alembic.** Running the rendered SQL proves the schema is valid
PostgreSQL and that its constraints behave as designed. It proves nothing about
Alembic's runner, its revision chain, or ``alembic_version`` stamping. WP-05
records those criteria as BLOCKED, and this renderer is supplementary evidence,
never a substitute.

Like the WP-03 renderer it also emits what ``0003`` adds through ``op.execute``:
the shared append-only function and the two triggers that use it. A renderer
that skipped those would produce a schema missing exactly the mechanism that
makes a review decision non-rewritable.
"""

from __future__ import annotations

import argparse
import ast
import io
import os
import sys
from typing import Optional

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPTS_DIR)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from render_wp02_schema import (  # noqa: E402
    POSTGRES_IDENTIFIER_LIMIT, UnsupportedConstruct, over_length_identifiers,
)
from render_wp03_schema import _Wp03Renderer, _terminate  # noqa: E402

MIGRATION = os.path.join(
    _REPO_ROOT, "migrations", "versions", "0003_wp05_source_policy.py")


class _Wp05Renderer(_Wp03Renderer):
    """The WP-03 renderer plus the one type helper ``0003`` introduces.

    Subclassed rather than editing the WP-02 renderer: that file is frozen
    tooling for an earlier work package, and a change there to support a later
    migration would put WP-05's needs inside WP-02's evidence chain.
    """

    def call(self, node: ast.Call):
        if self.call_name(node) == "_jsonb":
            return "JSONB"
        return super().call(node)


def render_schema(migration_path: str = MIGRATION) -> str:
    """Return the SQL rendering of the WP-05 migration's ``upgrade()``."""
    with io.open(migration_path, encoding="utf-8") as handle:
        module = ast.parse(handle.read(), filename=migration_path)
    upgrade = None
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == "upgrade":
            upgrade = node
    if upgrade is None:
        raise UnsupportedConstruct("no upgrade() function found")

    renderer = _Wp05Renderer(module)
    tables = renderer.render(ast.Module(body=[upgrade], type_ignores=[]))
    executes = renderer.render_executes(upgrade)
    header = (
        "-- WP-05 scientific source policy schema.\n"
        "-- GENERATED from migrations/versions/0003_wp05_source_policy.py by\n"
        "-- scripts/render_wp05_schema.py. Do not edit by hand: the migration is\n"
        "-- authoritative and this file is regenerated from it.\n"
        "-- Requires the WP-02 (0001) and WP-03 (0002) schemas first.\n"
    )
    body = "\n\n".join(tables + [_terminate(sql) for sql in executes])
    return header + "\n" + body + "\n"


def main(argv: Optional[list] = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="render_wp05_schema.py",
        description="Render the WP-05 migration as executable PostgreSQL DDL.")
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
                         % (args.out, sql.count("CREATE")))
    else:
        sys.stdout.write(sql)
    return 0


if __name__ == "__main__":
    sys.exit(main())
