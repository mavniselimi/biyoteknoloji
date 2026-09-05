#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the WP-02 Alembic migration as plain SQL (stdlib only).

    python3 scripts/render_wp02_schema.py --out build/wp02-schema.sql

The Alembic migration is authoritative. This renderer reads its AST and emits
the equivalent ``CREATE TABLE`` / ``CREATE INDEX`` statements, so the SQL can be
executed against a real PostgreSQL server in an environment where Alembic and
SQLAlchemy are not installed. Because the SQL is *derived* rather than
hand-maintained, the two cannot drift apart.

It is not a general Alembic-to-SQL translator: it understands exactly the
constructs this one migration uses and raises on anything else, rather than
silently emitting a schema that differs from the migration.
"""

from __future__ import annotations

import argparse
import ast
import io
import os
import sys
from typing import Any, List, Optional

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRATION = os.path.join(_REPO_ROOT, "migrations", "versions", "0001_wp02_foundation.py")

#: PostgreSQL truncates identifiers at this many bytes.
POSTGRES_IDENTIFIER_LIMIT = 63


class UnsupportedConstruct(RuntimeError):
    """Raised when the migration uses something this renderer does not model."""


class _Renderer:
    def __init__(self, module: ast.Module) -> None:
        self.constants = {}
        for node in module.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name):
                try:
                    self.constants[node.targets[0].id] = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    continue

    # -- literal evaluation ---------------------------------------------

    def value(self, node: ast.AST) -> Any:
        """Evaluate the small expression subset the migration uses."""
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in self.constants:
                return self.constants[node.id]
            raise UnsupportedConstruct("unknown name %r" % node.id)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            left = self.value(node.left)
            right = node.right
            if isinstance(right, ast.Tuple):
                return left % tuple(self.value(item) for item in right.elts)
            return left % self.value(right)
        if isinstance(node, ast.JoinedStr):  # pragma: no cover - not used
            raise UnsupportedConstruct("f-strings are not supported")
        if isinstance(node, ast.Call):
            return self.call(node)
        raise UnsupportedConstruct("cannot evaluate %s" % ast.dump(node)[:80])

    def call(self, node: ast.Call) -> Any:
        name = self.call_name(node)
        if name in ("sa.text", "text"):
            return {"__sql__": self.value(node.args[0])}
        if name in ("_uuid",):
            return "UUID"
        if name in ("_timestamptz",):
            return "TIMESTAMP WITH TIME ZONE"
        if name in ("sa.String", "String"):
            length = self.keyword(node, "length")
            if length is None and node.args:
                length = self.value(node.args[0])
            return "VARCHAR(%d)" % length if length else "VARCHAR"
        if name in ("sa.Text", "Text"):
            return "TEXT"
        if name in ("sa.Integer", "Integer"):
            return "INTEGER"
        if name in ("sa.Boolean", "Boolean"):
            return "BOOLEAN"
        if name in ("postgresql.JSONB", "JSONB"):
            return "JSONB"
        if name in ("postgresql.UUID",):
            return "UUID"
        if name in ("postgresql.TIMESTAMP",):
            return "TIMESTAMP WITH TIME ZONE"
        raise UnsupportedConstruct("unsupported call %r" % name)

    @staticmethod
    def call_name(node: ast.Call) -> str:
        func = node.func
        if isinstance(func, ast.Name):
            return func.id
        parts = []
        while isinstance(func, ast.Attribute):
            parts.append(func.attr)
            func = func.value
        if isinstance(func, ast.Name):
            parts.append(func.id)
        return ".".join(reversed(parts))

    def keyword(self, node: ast.Call, name: str) -> Any:
        for keyword in node.keywords:
            if keyword.arg == name:
                return self.value(keyword.value)
        return None

    # -- schema element rendering ---------------------------------------

    def column(self, node: ast.Call) -> str:
        name = self.value(node.args[0])
        type_sql = self.value(node.args[1])
        pieces = ['    %s %s' % (name, type_sql)]
        nullable = self.keyword(node, "nullable")
        if nullable is False:
            pieces.append("NOT NULL")
        default = self.keyword(node, "server_default")
        if isinstance(default, dict) and "__sql__" in default:
            pieces.append("DEFAULT %s" % default["__sql__"])
        elif default is not None:
            pieces.append("DEFAULT %s" % default)
        return " ".join(pieces)

    def constraint(self, node: ast.Call) -> str:
        name = self.call_name(node).split(".")[-1]
        label = self.keyword(node, "name")
        if name == "PrimaryKeyConstraint":
            columns = [self.value(argument) for argument in node.args]
            return "    CONSTRAINT %s PRIMARY KEY (%s)" % (label, ", ".join(columns))
        if name == "UniqueConstraint":
            columns = [self.value(argument) for argument in node.args]
            return "    CONSTRAINT %s UNIQUE (%s)" % (label, ", ".join(columns))
        if name == "CheckConstraint":
            return "    CONSTRAINT %s CHECK (%s)" % (label, self.value(node.args[0]))
        if name == "ForeignKeyConstraint":
            local = [self.value(item) for item in node.args[0].elts]
            target = [self.value(item) for item in node.args[1].elts]
            table = target[0].split(".")[0]
            columns = [reference.split(".")[1] for reference in target]
            clause = "    CONSTRAINT %s FOREIGN KEY (%s) REFERENCES %s (%s)" % (
                label, ", ".join(local), table, ", ".join(columns))
            ondelete = self.keyword(node, "ondelete")
            if ondelete:
                clause += " ON DELETE %s" % ondelete
            return clause
        raise UnsupportedConstruct("unsupported constraint %r" % name)

    def render(self, module: ast.Module) -> List[str]:
        statements: List[str] = []
        for node in ast.walk(module):
            if not isinstance(node, ast.Call):
                continue
            name = self.call_name(node)
            if name == "op.create_table":
                table = self.value(node.args[0])
                body = []
                for element in node.args[1:]:
                    if not isinstance(element, ast.Call):
                        raise UnsupportedConstruct("unexpected table element")
                    element_name = self.call_name(element).split(".")[-1]
                    if element_name == "Column":
                        body.append(self.column(element))
                    else:
                        body.append(self.constraint(element))
                statements.append("CREATE TABLE %s (\n%s\n);" % (table, ",\n".join(body)))
            elif name == "op.create_index":
                index = self.value(node.args[0])
                table = self.value(node.args[1])
                columns = [self.value(item) for item in node.args[2].elts]
                unique = self.keyword(node, "unique")
                statements.append("CREATE%s INDEX %s ON %s (%s);" % (
                    " UNIQUE" if unique else "", index, table, ", ".join(columns)))
        return statements


def render_schema(migration_path: str = MIGRATION) -> str:
    """Return the SQL rendering of the migration's ``upgrade()``."""
    with io.open(migration_path, encoding="utf-8") as handle:
        module = ast.parse(handle.read(), filename=migration_path)
    upgrade = None
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == "upgrade":
            upgrade = node
    if upgrade is None:
        raise UnsupportedConstruct("no upgrade() function found")
    renderer = _Renderer(module)
    statements = renderer.render(ast.Module(body=[upgrade], type_ignores=[]))
    header = (
        "-- WP-02 foundation schema.\n"
        "-- GENERATED from migrations/versions/0001_wp02_foundation.py by\n"
        "-- scripts/render_wp02_schema.py. Do not edit by hand: the migration is\n"
        "-- authoritative and this file is regenerated from it.\n"
    )
    return header + "\n" + "\n\n".join(statements) + "\n"


def over_length_identifiers(sql: str) -> List[str]:
    """Return identifiers PostgreSQL would silently truncate."""
    import re

    names = set(re.findall(r"\b(?:pk|uq|fk|ck|ix)_[a-z0-9_]+", sql))
    return sorted(name for name in names if len(name) > POSTGRES_IDENTIFIER_LIMIT)


def main(argv: Optional[list] = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="render_wp02_schema.py",
        description="Render the WP-02 migration as executable PostgreSQL DDL.")
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
            "IDENTIFIER_TOO_LONG: PostgreSQL truncates identifiers at %d bytes, which "
            "would break downgrade(): %s\n" % (POSTGRES_IDENTIFIER_LIMIT, ", ".join(too_long)))
        if args.check_identifiers:
            return 1

    if args.out:
        directory = os.path.dirname(os.path.abspath(args.out))
        if directory:
            os.makedirs(directory, exist_ok=True)
        with io.open(args.out, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(sql)
        sys.stderr.write("wrote %s (%d statements)\n" % (args.out, sql.count(";")))
    else:
        sys.stdout.write(sql)
    return 0


if __name__ == "__main__":
    sys.exit(main())
