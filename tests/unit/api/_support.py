# -*- coding: utf-8 -*-
"""Shared helpers for the WP-16 tests.

Two things live here: the paths and AST utilities the boundary tests read
source with, and one factory for a synthetic API world.

The AST utilities exist because most of :mod:`apps.api` cannot be imported in
this environment - FastAPI and Pydantic are not installable - so the tests
that cover the framework-bound half read it as a syntax tree. Reading
identifiers rather than prose is deliberate: a check that searched source text
for the word ``genotype`` would fail on the module whose docstring explains
why a genotype is refused.
"""

from __future__ import annotations

import ast
import io
import os
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", ".."))
APPS_DIR = os.path.join(REPO_ROOT, "apps")
API_DIR = os.path.join(APPS_DIR, "api")

#: The half that holds every decision and imports no web framework. All of it
#: executes in this environment and all of it is tested by execution.
FRAMEWORK_FREE_MODULES: Tuple[str, ...] = (
    "__init__.py",
    "artifacts.py",
    # WP-23. The session-backed principal resolver. Framework-free on purpose:
    # it converts an already-validated session into the immutable Principal
    # the API speaks, and imports no request, no response and no framework -
    # so it is testable without one.
    "auth.py",
    "catalog.py",
    "config.py",
    # WP-24. The deployment wiring: a request-scope middleware, a
    # request-scoped principal resolver, real readiness probes and the
    # provider they go into. Framework-free on purpose - the middleware is a
    # plain ASGI callable rather than a BaseHTTPMiddleware, because the latter
    # runs the handler in a separate task and the ContextVar the whole
    # composition resolves through would not be visible there.
    "deployment.py",
    "errors.py",
    "gate_status.py",
    "openapi.py",
    "provider.py",
    "readiness.py",
    "request_id.py",
    "routes.py",
    "runtime_verification.py",
    "security.py",
    os.path.join("adapters", "__init__.py"),
    os.path.join("adapters", "assessment.py"),
    os.path.join("adapters", "catalog.py"),
    os.path.join("adapters", "evidence.py"),
    os.path.join("adapters", "request.py"),
    os.path.join("adapters", "version.py"),
    os.path.join("contracts", "__init__.py"),
    os.path.join("contracts", "spec.py"),
    os.path.join("contracts", "validate.py"),
)

#: The half that holds no decisions and only wires. None of it can be imported
#: where the framework is absent, so it is covered by reading it.
FRAMEWORK_BOUND_MODULES: Tuple[str, ...] = (
    "dependencies.py",
    "factory.py",
    "main.py",
    "middleware.py",
    os.path.join("contracts", "models.py"),
    os.path.join("routers", "__init__.py"),
    os.path.join("routers", "assessments.py"),
    os.path.join("routers", "catalogue.py"),
    os.path.join("routers", "evidence.py"),
    os.path.join("routers", "expert_review.py"),
    os.path.join("routers", "health.py"),
    os.path.join("routers", "system.py"),
)

#: Packages the whole API layer may never import. ``pgx.infrastructure`` is
#: absent from this list on purpose: composing an application means naming a
#: repository, and the rule that matters is that no *router* or *adapter*
#: reaches into infrastructure, which is checked separately.
FORBIDDEN_IMPORTS: Tuple[str, ...] = (
    "risk_engine",
    "gemini_report_generator",
    "alternative_ranker",
    "candidate_onboarding",
    "clinpgx_probe",
    "clinpgx_probe_v2",
    "google",
    "openai",
    "anthropic",
    "requests",
    "urllib",
    "httpx",
    "socket",
)


def module_path(relative: str) -> str:
    return os.path.join(API_DIR, relative)


def api_modules() -> List[str]:
    """Every Python module of the API package, plus the ``apps`` marker.

    Walked rather than listed, so a module added without being classified is
    caught by the test that asserts the two lists cover the package.

    Scoped to ``apps/api`` since WP-17 added ``apps/web`` beside it. The web
    package has its own boundary tests with its own rules - it may import
    Jinja2, which the API may not, and it may not import an engine, which the
    API's adapters must. One walk over both would have to weaken whichever
    rule the other violates.
    """
    found: List[str] = [os.path.join(APPS_DIR, "__init__.py")]
    for root, _dirs, files in os.walk(API_DIR):
        if "__pycache__" in root:
            continue
        for name in sorted(files):
            if name.endswith(".py"):
                found.append(os.path.join(root, name))
    return sorted(found)


def source(path: str) -> str:
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def tree(path: str) -> ast.Module:
    return ast.parse(source(path), filename=path)


def imports_of(path: str) -> Set[str]:
    """Every module name imported, including inside functions."""
    found: Set[str] = set()
    for node in ast.walk(tree(path)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def identifiers_of(path: str) -> Set[str]:
    """Every name, attribute and definition, ignoring strings and comments."""
    names: Set[str] = set()
    for node in ast.walk(tree(path)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.add((node.asname or node.name).split(".")[0])
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.keyword) and node.arg:
            names.add(node.arg)
    return names


def route_decorators(path: str) -> List[Dict[str, Any]]:
    """Every ``@router.<method>(...)`` in one module, read as data.

    Returns the HTTP method, the first positional argument's source, and the
    literal keyword arguments. Enough to assert that a router registers
    exactly the declared routes without importing FastAPI.
    """
    found: List[Dict[str, Any]] = []
    for node in ast.walk(tree(path)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            target = decorator.func
            if not isinstance(target, ast.Attribute):
                continue
            if not (isinstance(target.value, ast.Name)
                    and target.value.id == "router"):
                continue
            entry: Dict[str, Any] = {
                "handler": node.name,
                "method": target.attr.upper(),
                "path_expression": (ast.unparse(decorator.args[0])
                                    if decorator.args else None),
                "keywords": {},
            }
            for keyword in decorator.keywords:
                if keyword.arg:
                    entry["keywords"][keyword.arg] = ast.unparse(keyword.value)
            found.append(entry)
    return found


def synthetic_world(**kwargs: Any):
    """The WP-14 synthetic world, imported lazily.

    Lazy because importing it builds a frozen ruleset on disk, and the
    boundary tests that only read source should not pay for that.
    """
    from tests.unit.application._assessment_support import (
        SyntheticAssessmentWorld)
    return SyntheticAssessmentWorld(**kwargs)


def test_settings(**overrides: Any):
    """Settings for a test application: never production, never connected."""
    from apps.api.config import ApiSettings, Environment
    from apps.api.security import AuthMode
    values: Dict[str, Any] = {
        "environment": Environment.TEST,
        "auth_mode": AuthMode.STATIC_TOKEN,
        "docs_enabled": True,
        "database_url_configured": True,
    }
    values.update(overrides)
    return ApiSettings(**values)
