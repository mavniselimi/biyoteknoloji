# -*- coding: utf-8 -*-
"""Shared paths and small helpers for the WP-11 tests.

The fixtures themselves live in :mod:`tests.fixtures.wp11.synthetic`, which is
where the SYNTHETIC markers are declared. This module holds only what a test
needs to find a file or read a module's source.
"""

from __future__ import annotations

import ast
import io
import os
from typing import Set

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

RULES_DIR = os.path.join(REPO_ROOT, "pgx", "rules")
APPLICATION_DIR = os.path.join(REPO_ROOT, "pgx", "application")
MIGRATION_0008 = os.path.join(REPO_ROOT, "migrations", "versions",
                              "0008_wp11_rules_and_rulesets.py")
DEFAULT_REGISTRY_ROOT = os.path.join(REPO_ROOT, "data", "rulesets")
GATE_STATUS_JSON = os.path.join(DEFAULT_REGISTRY_ROOT,
                                "wp11-real-gate-status.json")
BUILD_ATTEMPT_JSON = os.path.join(DEFAULT_REGISTRY_ROOT,
                                  "wp11-real-build-attempt.json")
LEGACY_INVENTORY_JSON = os.path.join(REPO_ROOT, "data", "migration", "wp11",
                                     "legacy-rule-candidate-inventory.json")

#: WP-11's own application modules, which legitimately name rule concepts.
RULE_APPLICATION_MODULES = ("rule_gate_status.py", "rule_service.py",
                            "rules_cli.py", "rules_schema.py",
                            "ruleset_service.py")


def source(path: str) -> str:
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def tree(path: str) -> ast.Module:
    return ast.parse(source(path), filename=path)


def rules_modules():
    """Every module of ``pgx/rules``, sorted."""
    return [os.path.join(RULES_DIR, name)
            for name in sorted(os.listdir(RULES_DIR))
            if name.endswith(".py")]


def imports_of(path: str) -> Set[str]:
    found: Set[str] = set()
    for node in ast.walk(tree(path)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def identifiers_of(path: str) -> Set[str]:
    names: Set[str] = set()
    for node in ast.walk(tree(path)):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.name for alias in node.names)
    return names
