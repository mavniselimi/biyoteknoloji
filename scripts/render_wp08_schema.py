#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the WP-08 migration as plain SQL (stdlib only).

    python3 scripts/render_wp08_schema.py --out build/wp08-schema.sql
    python3 scripts/render_wp08_schema.py --direction downgrade

Same purpose and the same caveat as the WP-02 through WP-07 renderers: the
Alembic migration is authoritative, and this reads its AST to emit the
equivalent DDL so the schema can be executed against a real PostgreSQL server
in an environment where Alembic and SQLAlchemy cannot be installed. Because the
SQL is *derived* rather than hand-maintained, the two cannot drift.

**This is not Alembic.** Running the rendered SQL proves the schema is valid
PostgreSQL and that its constraints behave as designed. It proves nothing about
Alembic's runner, its revision chain, or ``alembic_version`` stamping. WP-08
records those criteria as BLOCKED, and this renderer is supplementary evidence,
never a substitute.

Beyond the WP-07 renderer it emits three more operations that ``0006``
introduces: ``op.alter_column`` for the nullability change on
``source_record_version``, ``op.create_unique_constraint`` for the replacement
provenance key, and ``op.create_foreign_key`` for the two references added to
an existing table. Emitting them in source order matters: the constraint that
replaces ``0001``'s cannot be created before the column it names exists, and
the nullability change has to land before a row without a version can be
written.
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
from render_wp03_schema import _terminate  # noqa: E402
from render_wp07_schema import _Wp07Renderer  # noqa: E402

MIGRATION = os.path.join(
    _REPO_ROOT, "migrations", "versions", "0006_wp08_evidence_store.py")


class _Wp08Renderer(_Wp07Renderer):
    """The WP-07 renderer plus the operations ``0006`` introduces.

    Subclassed rather than edited in place, for the same reason each earlier
    renderer was: the previous ones are frozen evidence tooling for earlier
    work packages, and changing one to serve a later migration would put WP-08's
    needs inside WP-02's evidence chain.
    """

    def value(self, node: ast.AST):
        """Evaluate the expression subset, plus the list literals ``0006`` uses.

        ``op.create_unique_constraint`` and ``op.create_foreign_key`` take
        column lists. The earlier renderers never met one, because every
        earlier constraint was declared inside a ``create_table`` call.
        """
        if isinstance(node, (ast.List, ast.Tuple)):
            return [self.value(item) for item in node.elts]
        return super().value(node)

    def render_alterations(self, function: ast.FunctionDef) -> List[str]:
        """Every ``ALTER TABLE`` statement, in the order the migration runs it.

        Order is load-bearing here. ``0006`` drops ``0001``'s provenance
        unique constraint and creates a replacement over the natural key, and
        it makes ``source_record_version`` nullable. Emitting those out of
        order produces SQL that either fails or - worse - succeeds while
        describing a different schema.
        """
        statements: List[str] = []
        for node in ast.walk(function):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None)
            if name == "add_column":
                statements.append(self._add_column(node))
            elif name == "alter_column":
                statements.append(self._alter_column(node))
            elif name == "drop_constraint":
                statements.append(
                    "ALTER TABLE %s DROP CONSTRAINT %s;"
                    % (self.value(node.args[1]), self.value(node.args[0])))
            elif name == "create_check_constraint":
                statements.append(
                    "ALTER TABLE %s ADD CONSTRAINT %s CHECK (%s);"
                    % (self.value(node.args[1]), self.value(node.args[0]),
                       self._condition(node.args[2])))
            elif name == "create_unique_constraint":
                statements.append(
                    "ALTER TABLE %s ADD CONSTRAINT %s UNIQUE (%s);"
                    % (self.value(node.args[1]), self.value(node.args[0]),
                       ", ".join(self.value(node.args[2]))))
            elif name == "create_foreign_key":
                statements.append(self._create_foreign_key(node))
            elif name == "drop_column":
                statements.append(
                    "ALTER TABLE %s DROP COLUMN %s;"
                    % (self.value(node.args[0]), self.value(node.args[1])))
        return statements

    def _alter_column(self, node: ast.Call) -> str:
        """Render a nullability change. Nothing else is supported.

        A type change is deliberately refused rather than guessed at: an
        unrendered ``USING`` clause would produce SQL that runs and silently
        loses data.
        """
        table = self.value(node.args[0])
        column = self.value(node.args[1])
        nullable = None
        for keyword in node.keywords:
            if keyword.arg == "nullable":
                nullable = bool(self.value(keyword.value))
            elif keyword.arg not in ("existing_type", "existing_nullable",
                                     "existing_server_default"):
                raise UnsupportedConstruct(
                    "alter_column keyword %r is not rendered; add it "
                    "deliberately rather than emitting SQL that omits it"
                    % keyword.arg)
        if nullable is None:
            raise UnsupportedConstruct(
                "alter_column on %s.%s changes nothing this renderer emits"
                % (table, column))
        return ("ALTER TABLE %s ALTER COLUMN %s %s NOT NULL;"
                % (table, column, "DROP" if nullable else "SET"))

    def _create_foreign_key(self, node: ast.Call) -> str:
        constraint = self.value(node.args[0])
        table = self.value(node.args[1])
        target = self.value(node.args[2])
        columns = ", ".join(self.value(node.args[3]))
        target_columns = ", ".join(self.value(node.args[4]))
        on_delete = ""
        for keyword in node.keywords:
            if keyword.arg == "ondelete":
                on_delete = " ON DELETE %s" % self.value(keyword.value)
        return ("ALTER TABLE %s ADD CONSTRAINT %s FOREIGN KEY (%s) "
                "REFERENCES %s (%s)%s;"
                % (table, constraint, columns, target, target_columns,
                   on_delete))


def render_schema(migration_path: str = MIGRATION,
                  direction: str = "upgrade") -> str:
    """Return the SQL rendering of one direction of the WP-08 migration."""
    with io.open(migration_path, encoding="utf-8") as handle:
        module = ast.parse(handle.read(), filename=migration_path)
    functions = {node.name: node for node in module.body
                 if isinstance(node, ast.FunctionDef)}
    renderer = _Wp08Renderer(module)

    if direction == "downgrade":
        downgrade = functions.get("downgrade")
        if downgrade is None:
            raise UnsupportedConstruct("no downgrade() function found")
        header = (
            "-- WP-08 downgrade: remove exactly the 0006 objects.\n"
            "-- GENERATED from migrations/versions/0006_wp08_evidence_store.py\n"
            "-- by scripts/render_wp08_schema.py --direction downgrade.\n"
            "-- Refused on a database holding evidence rows with no source\n"
            "-- record version: restoring 0001's NOT NULL would require\n"
            "-- writing a version nobody knows. That refusal is correct.\n"
            "-- Wrapped in one transaction so that refusal is also total:\n"
            "-- Alembic runs downgrade() in a transaction, and a half-applied\n"
            "-- schema is a worse outcome than a rejected one.\n")
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
            header, "\n\n".join(_downgrade_order(statements)))

    upgrade = functions.get("upgrade")
    if upgrade is None:
        raise UnsupportedConstruct("no upgrade() function found")

    alterations = renderer.render_alterations(upgrade)
    tables = renderer.render(ast.Module(body=[upgrade], type_ignores=[]))
    executes = renderer.render_executes(upgrade)
    header = (
        "-- WP-08 evidence store: provenance, attribution, links and issues.\n"
        "-- GENERATED from migrations/versions/0006_wp08_evidence_store.py by\n"
        "-- scripts/render_wp08_schema.py. Do not edit by hand: the migration\n"
        "-- is authoritative and this file is regenerated from it.\n"
        "-- Requires the WP-02 (0001) through WP-07 (0005) schemas.\n"
        "-- Wrapped in one transaction, as Alembic runs upgrade(): a schema\n"
        "-- that failed halfway is not a state this project accepts.\n")
    body = "\n\n".join(_upgrade_order(tables + alterations)
                       + [_terminate(sql) for sql in executes])
    return _transactional(header, body)


def _transactional(header: str, body: str) -> str:
    """Wrap a rendered direction in a single explicit transaction.

    PostgreSQL applies DDL transactionally, and Alembic runs each migration
    that way. Rendering the statements bare meant psql auto-committed each
    one, so a downgrade that correctly refused to invent a version string had
    already dropped eight tables by the time it refused. Either the whole
    direction applies or none of it does.
    """
    return "%s\nBEGIN;\n\n%s\n\nCOMMIT;\n" % (header, body)


def _upgrade_order(statements: List[str]) -> List[str]:
    """Sort the upgrade so every statement's dependencies already exist.

    ``ast.walk`` does not preserve statement order, and the natural reading
    order is wrong anyway: ``0006`` creates an index on
    ``evidence_records.natural_key``, a column the same migration adds. Emitted
    as written, the index would be created before its column.

    So statements are ranked by what they need: tables, then the columns added
    to existing tables, then the constraints over those columns, then every
    index. Ranking is stable, so statements of one kind keep their source
    order - which is what makes the drop-then-recreate constraint pair land the
    right way round.
    """
    def rank(statement: str) -> int:
        if statement.startswith("CREATE TABLE"):
            return 0
        if "ADD COLUMN" in statement:
            return 1
        if "ALTER COLUMN" in statement:
            return 2
        if "DROP CONSTRAINT" in statement:
            return 3
        if "ADD CONSTRAINT" in statement:
            return 4
        if statement.startswith("CREATE INDEX") or \
                statement.startswith("CREATE UNIQUE INDEX"):
            return 5
        return 6
    return sorted(statements, key=rank)


def _downgrade_order(statements: List[str]) -> List[str]:
    """Undo the upgrade in the reverse of the order that built it.

    ``ast.walk`` does not preserve statement order, so the downgrade is
    reassembled by kind. The ranking is the mirror of ``_upgrade_order``:
    whatever the upgrade created last is removed first.

    The columns ``0006`` adds to ``evidence_records`` must go before the
    tables ``0006`` creates, because ``evidence_build_id`` carries a foreign
    key into ``evidence_builds``. Dropping the tables first fails with
    "cannot drop table evidence_builds because other objects depend on it",
    which is what an earlier ordering did. Restoring what ``0001`` owned -
    the ``NOT NULL`` on ``source_record_version`` and the provenance unique
    constraint - comes last, once the columns that displaced them are gone.
    """
    def rank(statement: str) -> int:
        if statement.startswith("DROP TRIGGER"):
            return 0
        if statement.startswith("DROP FUNCTION"):
            return 1
        if statement.startswith("DROP INDEX"):
            return 2
        if "DROP CONSTRAINT" in statement:
            return 3
        if "DROP COLUMN" in statement:
            return 4
        if statement.startswith("DROP TABLE"):
            return 5
        if "ALTER COLUMN" in statement:
            return 6
        if "ADD CONSTRAINT" in statement:
            return 7
        return 8
    return sorted(statements, key=rank)


def main(argv: Optional[list] = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="render_wp08_schema.py",
        description="Render the WP-08 migration as executable PostgreSQL DDL.")
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
            "IDENTIFIER_TOO_LONG: PostgreSQL truncates identifiers at %d "
            "bytes, which would break downgrade(): %s\n"
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
