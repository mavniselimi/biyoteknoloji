# -*- coding: utf-8 -*-
"""Shared paths and small helpers for the WP-12 tests."""

from __future__ import annotations

import ast
import io
import os
from typing import Set

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

ENGINE_DIR = os.path.join(REPO_ROOT, "pgx", "engine")
APPLICATION_DIR = os.path.join(REPO_ROOT, "pgx", "application")
LEGACY_PROFILES = os.path.join(REPO_ROOT, "clinpgx_mvp_seed",
                               "mvp_demo_profiles.json")
REGRESSION_REPORT = os.path.join(REPO_ROOT, "data", "migration", "wp12",
                                 "phenotype-regression-report.json")
REGRESSION_ALLOWLIST = os.path.join(REPO_ROOT, "data", "migration", "wp12",
                                    "phenotype-regression-allowlist.json")

#: WP-12's application modules, which legitimately name engine concepts.
ENGINE_APPLICATION_MODULES = ("phenotype_cli.py", "phenotype_schema.py")

#: WP-13's application modules. Listed separately from WP-12's because the
#: boundary tests are per-work-package: a check that WP-12 names no coverage
#: concept is meaningless if it is run over WP-13's coverage modules, and
#: merging the lists is how a per-package boundary quietly becomes a
#: package-wide one that asserts nothing.
COVERAGE_APPLICATION_MODULES = ("coverage_cli.py", "coverage_gate_status.py",
                                "coverage_schema.py")

#: The engine modules WP-12 owns. Enumerated rather than derived, so a module
#: added to ``pgx/engine`` by a later work package is not silently absorbed
#: into WP-12's boundary checks and does not silently escape its own.
WP12_ENGINE_MODULES = ("phenotype.py", "phenotype_errors.py",
                       "phenotype_legacy.py", "phenotype_models.py",
                       "phenotype_normalization.py")

#: The engine modules WP-13 owns, on the same terms.
WP13_ENGINE_MODULES = ("coverage.py", "coverage_errors.py",
                       "coverage_legacy.py", "coverage_manifest.py",
                       "coverage_models.py", "coverage_validator.py")

#: The engine modules WP-14 owns, on the same terms. These are the ones that
#: legitimately name attention, risk and assessment concepts - which is why
#: the per-work-package lists exist at all: a check that WP-12 names no
#: assessment type is meaningless run over the assessment engine.
WP14_ENGINE_MODULES = ("candidate_evaluation.py", "risk.py",
                       "risk_errors.py", "risk_legacy.py",
                       "risk_models.py")

#: WP-14's application modules.
#: ``candidate_assessment_service.py`` and ``candidate_release.py`` are here
#: for the same reason the rest are: they are the application side of the
#: assessment engine. They execute a candidate release, which
#: ``assessment_service.py`` cannot - a candidate rule carries no WP-10
#: approval envelope, and ``evaluate_axis_finding`` verifies one - so they read
#: the engine directly, which is the dependency running in the correct
#: direction.
ASSESSMENT_APPLICATION_MODULES = ("assessment_cli.py", "assessment_models.py",
                                  "assessment_gate_status.py",
                                  "assessment_read_model.py",
                                  "assessment_schema.py",
                                  "assessment_service.py",
                                  "assessment_snapshot.py",
                                  "candidate_assessment_service.py",
                                  "candidate_release.py")


def source(path: str) -> str:
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def tree(path: str) -> ast.Module:
    return ast.parse(source(path), filename=path)


def engine_modules():
    """Every Python module physically present in ``pgx/engine``.

    Used by the checks that apply to the whole package whoever wrote it - the
    layer direction, the absence of a clock, of a network and of a mutable
    CSV - and deliberately read from the filesystem rather than from a list,
    so a new module is covered by them the moment it appears.
    """
    return [os.path.join(ENGINE_DIR, name)
            for name in sorted(os.listdir(ENGINE_DIR))
            if name.endswith(".py")]


def modules_of(names, directory=None):
    """Absolute paths for an explicitly enumerated set of module names."""
    root = ENGINE_DIR if directory is None else directory
    return [os.path.join(root, name) for name in names]


def wp12_modules():
    """WP-12's own modules: engine and application."""
    return (modules_of(WP12_ENGINE_MODULES)
            + modules_of(ENGINE_APPLICATION_MODULES, APPLICATION_DIR))


def wp13_modules():
    """WP-13's own modules: engine and application."""
    return (modules_of(WP13_ENGINE_MODULES)
            + modules_of(COVERAGE_APPLICATION_MODULES, APPLICATION_DIR))


def wp14_modules():
    """WP-14's own modules: engine and application."""
    return (modules_of(WP14_ENGINE_MODULES)
            + modules_of(ASSESSMENT_APPLICATION_MODULES, APPLICATION_DIR))


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
