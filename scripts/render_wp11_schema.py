#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the WP-11 migration as plain SQL (stdlib only).

    python3 scripts/render_wp11_schema.py --out build/wp11-schema.sql
    python3 scripts/render_wp11_schema.py --direction downgrade

Same purpose and the same caveat as the WP-02 through WP-10 renderers: the
Alembic migration is authoritative, and this reads its AST to emit the
equivalent DDL so the schema can be executed against a real PostgreSQL server
in an environment where Alembic and SQLAlchemy cannot be installed. Because the
SQL is *derived* rather than hand-maintained, the two cannot drift.

**This is not Alembic.** Running the rendered SQL proves the schema is valid
PostgreSQL and that its constraints and triggers behave as designed. It proves
nothing about Alembic's runner, its revision chain, or ``alembic_version``
stamping.

Beyond the WP-10 renderer, ``0008`` needs one ordering change: it adds columns
to three existing tables *and* creates new tables whose triggers reference
those columns, so the added columns must land before the trigger bodies run.
The WP-08 upgrade ranking already places columns before executes; the
downgrade guard keeps its WP-10 position at the front.
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
from render_wp10_schema import _downgrade_order_wp10  # noqa: E402

MIGRATION = os.path.join(
    _REPO_ROOT, "migrations", "versions", "0008_wp11_rules_and_rulesets.py")


class _Wp11Renderer(_Wp08Renderer):
    """The WP-08 renderer plus ``op.drop_constraint`` with a unique type.

    ``0008`` drops a unique constraint and a foreign key by name in its
    downgrade, which earlier migrations only ever did for checks. The parent
    renderer already emits ``ALTER TABLE ... DROP CONSTRAINT`` regardless of
    the declared type, so nothing needs overriding; the subclass exists so a
    future WP-11 change has somewhere to go that is not inside WP-08's evidence
    tooling.
    """


def render_schema(migration_path: str = MIGRATION,
                  direction: str = "upgrade") -> str:
    """Return the SQL rendering of one direction of the WP-11 migration."""
    with io.open(migration_path, encoding="utf-8") as handle:
        module = ast.parse(handle.read(), filename=migration_path)
    functions = {node.name: node for node in module.body
                 if isinstance(node, ast.FunctionDef)}
    renderer = _Wp11Renderer(module)

    if direction == "downgrade":
        downgrade = functions.get("downgrade")
        if downgrade is None:
            raise UnsupportedConstruct("no downgrade() function found")
        header = (
            "-- WP-11 downgrade: remove exactly the 0008 objects.\n"
            "-- GENERATED from migrations/versions/0008_wp11_rules_and_rulesets.py\n"
            "-- by scripts/render_wp11_schema.py --direction downgrade.\n"
            "-- Refused on a database holding an approved rule or a frozen\n"
            "-- ruleset: those rows record that named people approved a\n"
            "-- scientific claim, and a frozen ruleset may be cited by a\n"
            "-- release or a historical assessment.\n"
            "-- Wrapped in one transaction so the refusal is total.\n")
        statements: List[str] = []
        for node in ast.walk(downgrade):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None)
            if name == "execute":
                statements.append(_terminate(renderer.value(node.args[0])))
            elif name == "drop_index":
                statements.append("DROP INDEX %s;" % renderer.value(node.args[0]))
            elif name == "drop_table":
                statements.append("DROP TABLE %s;" % renderer.value(node.args[0]))
        statements.extend(renderer.render_alterations(downgrade))
        return _transactional(header,
                              "\n\n".join(_downgrade_order_wp10(statements)))

    upgrade = functions.get("upgrade")
    if upgrade is None:
        raise UnsupportedConstruct("no upgrade() function found")

    alterations = renderer.render_alterations(upgrade)
    tables = renderer.render(ast.Module(body=[upgrade], type_ignores=[]))
    executes = renderer.render_executes(upgrade)
    header = (
        "-- WP-11 governed computable rules and immutable rulesets.\n"
        "-- GENERATED from migrations/versions/0008_wp11_rules_and_rulesets.py\n"
        "-- by scripts/render_wp11_schema.py. Do not edit by hand: the\n"
        "-- migration is authoritative and this file is regenerated from it.\n"
        "-- Requires the WP-02 (0001) through WP-10 (0007) schemas.\n"
        "-- Extends computable_rules, ruleset_versions and ruleset_rules\n"
        "-- rather than creating parallel tables: two answers to 'what rules\n"
        "-- exist' is the drift the release registry exists to stop.\n"
        "-- Wrapped in one transaction, as Alembic runs upgrade().\n")
    body = "\n\n".join(_upgrade_order(tables + alterations)
                       + [_terminate(sql) for sql in executes])
    return _transactional(header, body)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="render_wp11_schema.py",
        description="Render the WP-11 migration as executable PostgreSQL DDL.")
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
