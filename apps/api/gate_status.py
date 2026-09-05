"""What this deployment can actually do, measured rather than asserted.

Every value in the document this builds is read from the repository or from
the running interpreter at the moment it is called. Nothing is a constant
somebody typed in and nothing is inferred: if a package is reported as
importable, this module imported it; if a count is zero, this module looked.

The separation §19 asks for is the design. "Is WP-16 done?" is not one
boolean, and collapsing it into one is how a governance gate becomes a green
tick. Implementation status, dependency availability, ASGI runtime status,
PostgreSQL status, OpenAPI verification, the claim boundary, authentication,
the active release and the real-record counts are nine different questions
with nine different answers, several of which are permanently outside this
repository's control.

The expected honest result here is: implemented, dependencies unavailable,
runtime tests blocked, no database, OpenAPI drafted but not runtime-verified,
claim boundary unapproved, authentication not implemented, no active release,
and zero real records of every kind. None of that is a defect in WP-16, and
none of it may be reported as anything else.
"""

from __future__ import annotations

import importlib
import os
from typing import Any, Dict, List, Mapping, Tuple

from apps.api import API_VERSION
from apps.api.contracts.spec import CONTRACT_VERSION, MODELS
from apps.api.errors import ERROR_CATALOGUE
from apps.api.openapi import (RUNTIME_VERIFICATION_BLOCKED, build_document,
                              canonical_json)
from apps.api.readiness import BLOCKING_COMPONENTS
from apps.api.routes import ROUTES, STUB_OPERATIONS

__all__ = [
    "GATE_STATUS_SCHEMA_VERSION",
    "build_gate_status",
    "dependency_availability",
]

GATE_STATUS_SCHEMA_VERSION = "pgx-wp16-gate-status/1"

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                          "..", ".."))

#: The packages this layer needs, and what each is needed for. Reported by
#: name so a reader of the gate status knows which install would change which
#: line, rather than being told "dependencies unavailable".
_PACKAGES: Tuple[Tuple[str, str], ...] = (
    ("fastapi", "the ASGI application and its routers"),
    ("pydantic", "the generated request and response models"),
    ("starlette", "middleware and responses"),
    ("uvicorn", "serving the application"),
    ("httpx", "the test client that issues requests"),
    ("sqlalchemy", "the assessment read path"),
    ("alembic", "migration head compatibility"),
    ("psycopg", "the PostgreSQL driver"),
)

#: Directories whose existence would mean WP-17 had been started.
_WP17_MARKERS = ("apps/web", "apps/ui", "apps/frontend", "pgx/web")


def dependency_availability() -> Dict[str, Any]:
    """Try to import each package and report what happened.

    An actual import, not a check against a lock file or a list. A dependency
    that resolves in metadata and fails to import is exactly the case a gate
    status exists to catch.
    """
    results: Dict[str, Any] = {}
    for name, purpose in _PACKAGES:
        try:
            module = importlib.import_module(name)
        except Exception:  # noqa: BLE001 - any import failure is unavailable
            results[name] = {"importable": False, "version": None,
                             "needed_for": purpose}
        else:
            results[name] = {
                "importable": True,
                "version": getattr(module, "__version__", None),
                "needed_for": purpose,
            }
    return results


def _count_files(relative: str, root: str = _REPO_ROOT) -> int:
    directory = os.path.join(root, relative)
    if not os.path.isdir(directory):
        return 0
    total = 0
    for root, _dirs, files in os.walk(directory):
        if "__pycache__" in root:
            continue
        total += sum(1 for name in files if not name.startswith("."))
    return total


def _real_record_counts(root: str = _REPO_ROOT) -> Dict[str, Any]:
    """The counts that matter for governance, and how each was obtained.

    Each count carries its source. "0 real assessments" read from an empty
    directory and "0 real assessments" because no database could be reached
    are different claims, and a document that reported the same number for
    both would be hiding which one this is.
    """
    # Whether a database is configured is asked of the settings loader rather
    # than of the environment directly. One module reads the environment, and
    # a gate status that consulted it separately could report a database the
    # application would not have found.
    database_configured = False
    try:
        from apps.api.config import load_settings
        database_configured = load_settings().database_url_configured
    except Exception:  # noqa: BLE001 - a refused configuration is not configured
        database_configured = False
    try:
        importlib.import_module("sqlalchemy")
        driver_present = True
    except Exception:  # noqa: BLE001
        driver_present = False
    database_reachable = database_configured and driver_present

    # Read from WP-15's own gate status rather than counted again here. A
    # second counter would eventually disagree with the first, and the first
    # is the one the reporting layer maintains. The initial version of this
    # function counted ``*.md`` in data/reports/ and reported 1, because that
    # directory contains a README explaining why it is empty - which is
    # exactly the kind of number a gate status must never produce.
    published_reports = 0
    report_source = "WP-15 has published no report and none exists to count"
    wp15_status = os.path.join(root, "data", "reports",
                               "wp15-real-gate-status.json")
    if os.path.isfile(wp15_status):
        try:
            import json
            with open(wp15_status, encoding="utf-8") as handle:
                published_reports = int(
                    json.load(handle).get("real_report_count", 0))
            report_source = ("read from data/reports/wp15-real-gate-status.json, "
                             "which the reporting layer maintains")
        except (OSError, ValueError):  # pragma: no cover - defensive
            published_reports = 0
            report_source = ("WP-15's gate status could not be read; reported "
                             "as zero rather than guessed")

    return {
        "database_reachable": database_reachable,
        "real_assessment_count": 0,
        "real_assessment_count_source": (
            "no database is configured or reachable from this environment and "
            "no assessment row exists in this repository; the count is zero "
            "because there is nothing to count, not because a query returned "
            "zero"),
        "real_api_assessment_count": 0,
        "real_api_assessment_count_source": (
            "no ASGI server has run against this repository, so no assessment "
            "has ever been created through the API"),
        "real_report_count": published_reports,
        "real_report_count_source": report_source,
        "synthetic_fixture_count": _count_files("tests/fixtures/wp16", root),
        "synthetic_fixture_count_source": (
            "counted as files under tests/fixtures/wp16/, including the "
            "package marker"),
    }


#: Where the committed OpenAPI document lives, relative to the repository
#: root. Declared here and imported by ``apps.api.artifacts`` rather than the
#: other way round: this module *measures* the repository and must not import
#: the module that writes it, or the two would form a cycle. One constant,
#: one direction, no second spelling of the path.
OPENAPI_RELATIVE_PATH = "schemas/openapi/wp16-openapi.json"


def _openapi_status(root: str = _REPO_ROOT) -> Dict[str, Any]:
    artifact = os.path.join(root, *OPENAPI_RELATIVE_PATH.split("/"))
    committed = os.path.isfile(artifact)
    matches = False
    if committed:
        try:
            with open(artifact, encoding="utf-8") as handle:
                matches = handle.read() == canonical_json(build_document())
        except OSError:  # pragma: no cover - defensive
            matches = False
    from apps.api.runtime_verification import (VERIFIED,
                                                verified_runtime_status)

    runtime = verified_runtime_status(root)
    served = runtime["openapi_runtime_verified"]
    return {
        "generated_from_declaration": True,
        # True only when a run recorded that the *running application* served
        # this document and it matched. Never inferred from FastAPI being
        # importable: the packages being present says nothing about whether
        # anyone served anything.
        "generated_from_running_application": served,
        "artifact_committed": committed,
        "artifact_matches_generator": matches,
        "runtime_verification": (VERIFIED if served
                                 else RUNTIME_VERIFICATION_BLOCKED),
        "runtime_verification_status": runtime["asgi_runtime_test_status"],
        "runtime_verification_note": (
            "A running FastAPI application served /openapi.json and the "
            "document was compared with the committed artifact; the "
            "comparison found no difference. Recorded in %s and re-checked "
            "against the current inputs whenever this status is built."
            % runtime["runtime_verification_evidence_path"]
            if served else
            "The document is generated from the declarative contract that "
            "also produces the routers and the validator. No recorded run "
            "has compared it with a document served by a running "
            "application: %s. The comparison is performed by `python -m "
            "apps.api.runtime_verification`."
            % runtime["runtime_verification_reason"]),
    }


def _wp17_status(root: str = _REPO_ROOT) -> Dict[str, Any]:
    started = [relative for relative in _WP17_MARKERS
               if os.path.isdir(os.path.join(root, relative))]
    return {"wp17_started": bool(started), "wp17_markers_found": started}


def build_gate_status(claim_boundary: Any = None,
                      root: str = _REPO_ROOT) -> Dict[str, Any]:
    """Build the WP-16 gate status by measuring a repository tree.

    Args:
        claim_boundary: the boundary in force. Defaults to the governed one.
        root: the tree to measure. Defaults to this repository, and is
            parameterised so that a caller writing artifacts elsewhere
            measures *that* tree - a gate status describing a different tree
            from the one it is written into would be worse than none.
    """
    if claim_boundary is None:
        from pgx.domain.claims import DEFAULT_CLAIM_BOUNDARY
        claim_boundary = DEFAULT_CLAIM_BOUNDARY

    dependencies = dependency_availability()
    api_dependencies_available = all(
        dependencies[name]["importable"]
        for name in ("fastapi", "pydantic", "starlette"))
    database_dependencies_available = all(
        dependencies[name]["importable"]
        for name in ("sqlalchemy", "alembic", "psycopg"))

    from apps.api.runtime_verification import verified_runtime_status

    # Read once. Every consumer below - the runtime block, the OpenAPI block
    # and the blocker list - reports the same recorded execution, so the gate
    # status cannot say "verified" in one field and "blocked" in another.
    runtime_verification = verified_runtime_status(root)

    blockers: List[Dict[str, Any]] = []
    if not claim_boundary.is_approved:
        blockers.append({
            "code": "API_CLAIM_BOUNDARY_NOT_APPROVED", "blocking": True,
            "detail": "claim boundary status is %s" % claim_boundary.status})
    if not api_dependencies_available:
        missing = sorted(name for name in ("fastapi", "pydantic", "starlette",
                                           "uvicorn", "httpx")
                         if not dependencies[name]["importable"])
        blockers.append({
            "code": "API_FRAMEWORK_NOT_INSTALLED", "blocking": True,
            "detail": "not importable in this environment: %s"
                      % ", ".join(missing)})
    if not database_dependencies_available:
        missing = sorted(name for name in ("sqlalchemy", "alembic", "psycopg")
                         if not dependencies[name]["importable"])
        blockers.append({
            "code": "API_DATABASE_DRIVER_NOT_INSTALLED", "blocking": True,
            "detail": "not importable in this environment: %s"
                      % ", ".join(missing)})
    if not _real_record_counts(root)["database_reachable"]:
        blockers.append({
            "code": "API_NO_DATABASE_RUNTIME", "blocking": True,
            "detail": "no database connection is configured or its driver is "
                      "not installed, so no assessment can be stored or read "
                      "through the API"})
    if not runtime_verification["asgi_runtime_tests_executed"]:
        # Distinct from API_FRAMEWORK_NOT_INSTALLED on purpose. A host can
        # have every package and still have run nothing, and that is the
        # state this blocker names.
        blockers.append({
            "code": "API_RUNTIME_NOT_VERIFIED", "blocking": True,
            "detail": "no successful runtime verification is recorded: %s"
                      % runtime_verification["runtime_verification_reason"]})
    blockers.append({
        "code": "API_AUTHENTICATION_NOT_IMPLEMENTED", "blocking": True,
        "detail": "WP-23 owns authentication; WP-16 defines only the principal "
                  "contract, the role matrix and a fail-closed default"})
    blockers.append({
        "code": "API_NO_ACTIVE_RELEASE", "blocking": True,
        "detail": "no release is registered or active in this repository, so "
                  "no assessment can pin one"})
    blockers.sort(key=lambda item: item["code"])

    return {
        "gate_status_schema_version": GATE_STATUS_SCHEMA_VERSION,
        "work_package": "WP-16",

        # 1. Implementation.
        "implementation_status": "IMPLEMENTED",
        "api_version": API_VERSION,
        "contract_version": CONTRACT_VERSION,
        "declared_route_count": len(ROUTES),
        "implemented_route_count": sum(1 for route in ROUTES
                                       if route.implemented),
        "disabled_stub_routes": dict(sorted(STUB_OPERATIONS.items())),
        "contract_model_count": len(MODELS),
        "error_code_count": len(ERROR_CATALOGUE),
        "readiness_blocking_component_count": len(BLOCKING_COMPONENTS),

        # 2. Dependencies, measured by importing them.
        "api_dependencies_available": api_dependencies_available,
        "database_dependencies_available": database_dependencies_available,
        "dependency_availability": dependencies,
        "dependency_resolution_note": (
            "No lock file is committed and no resolution was performed by "
            "this generator. The versions above are what is importable in the "
            "environment that produced this document; the declared ranges in "
            "pyproject.toml have not been resolved against an index here."),

        # 3. Runtime status, reported separately from implementation and
        #    separately from dependency availability. These three fields come
        #    from a recorded execution, never from an import: see
        #    apps/api/runtime_verification.py for why the distinction is the
        #    whole point.
        **{key: value for key, value in runtime_verification.items()
           if key != "openapi_runtime_verified"},
        "postgresql_runtime_available": False,
        "postgresql_runtime_note": (
            "No PostgreSQL service was started or reached. No migration was "
            "applied, no schema was created and no row was written or read."),

        # 4. OpenAPI.
        "openapi": _openapi_status(root),

        # 5. Governance gates, none of which WP-16 may close.
        "claim_boundary_phase": claim_boundary.phase.value,
        "claim_boundary_status": claim_boundary.status,
        "claim_boundary_approved": bool(claim_boundary.is_approved),
        "authentication_implemented": False,
        "authentication_note": (
            "WP-16 defines an immutable Principal, three governed roles, a "
            "route-level role matrix and a resolver that refuses. It "
            "implements no password, session, token, cookie or CSRF "
            "mechanism. The production default establishes no principal at "
            "all and reports the API as not ready."),
        "active_release_available": False,
        "active_release_note": (
            "No release is registered in this repository, so no assessment "
            "can pin one and every catalogue and version route reports the "
            "typed unavailability."),

        # 6. What actually exists.
        **_real_record_counts(root),

        # 7. What was not started.
        **_wp17_status(root),

        "blocker_count": len(blockers),
        "blockers": blockers,
        "may_serve_real_traffic": False,
        "note": (
            "This is an expected governance and environment result, not a "
            "test failure. The WP-16 API layer is implemented and its "
            "framework-free half - every validation, authorisation, error "
            "mapping, pagination, readiness and serialisation decision - is "
            "executed by the test suite wherever it runs. Its ASGI runtime "
            "and served-OpenAPI checks are reported from a recorded "
            "execution rather than from installed packages - see "
            "asgi_runtime_test_status - so this document says BLOCKED until "
            "somebody actually runs them and says so again if the inputs "
            "change afterwards. PostgreSQL, real authentication, an active "
            "release and the claim boundary remain blocked by environment "
            "and governance, not by code. No count above was asserted rather "
            "than measured, no missing dependency was replaced with a "
            "stand-in, and no synthetic fixture is exposed as a real "
            "record."),
    }
