"""Every WP-17 artifact, generated from the declarations that produce the UI.

Three schemas under ``schemas/wp17/``, the sealed case catalogue and its
manifest under ``data/demo/``, the gate status under ``data/web/``, and
deterministic HTML snapshots under ``tests/fixtures/wp17/``.

**The snapshots are rendered template output, not browser captures.** They are
produced by the same Jinja environment the application uses, over synthetic
fixtures, and each one carries a header declaring what it is. No browser has
run in this environment; nothing here is a screenshot and nothing claims to
be.

The gate status is written last, for the reason the API's is: it measures the
tree, including whether the sealed catalogue is present, so producing it
before the catalogue exists would make it report an absence the same call was
about to fill.
"""

from __future__ import annotations

import io
import json
import os
from typing import Any, Dict, Mapping, Optional, Tuple

from apps.web.claim_gate import gate_contract
from apps.web.config import WebSettings
from apps.web.demo_cases import CASE_CATALOG_SCHEMA_VERSION, FORBIDDEN_CASE_FIELDS
from apps.web.demo_migration import MIGRATION_VERSION, build_catalog, build_manifest
from apps.web.gate_status import (SCREENSHOT_EVIDENCE_STATUSES,
                                  UI_GATE_STATUS_SCHEMA_VERSION,
                                  build_ui_gate_status)
from apps.web.render import TEMPLATE_NAMES
from apps.web.routes import NAVIGATION, WEB_ROUTES
from apps.web.security import SECURITY_HEADERS

__all__ = ["ARTIFACT_PATHS", "GATE_STATUS_PATH", "build_artifacts", "main",
           "write_artifacts"]

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

GATE_STATUS_PATH = "data/web/wp17-real-gate-status.json"

ARTIFACT_PATHS = (
    "schemas/wp17/web-route-surface.schema.json",
    "schemas/wp17/demo-case-catalog.schema.json",
    "schemas/wp17/ui-gate-status.schema.json",
    "data/demo/wp17-development-cases.json",
    "data/demo/wp17-demo-case-manifest.json",
    GATE_STATUS_PATH,
)

_BASE = "https://pgx.local/schemas/wp17/"


def _json(document: Mapping[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True,
                      ensure_ascii=True) + "\n"


def _route_surface() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "web-route-surface.schema.json",
        "title": "PGx server-rendered web route surface (WP-17)",
        "description": (
            "The closed list of pages. A route not on this list does not "
            "exist. These are HTML pages and are deliberately absent from the "
            "API's OpenAPI document, which is generated from the API route "
            "table alone."),
        "type": "array",
        "x-pgx-artifact-kind": "SOURCE_DERIVED",
        "x-pgx-navigation": list(NAVIGATION),
        "x-pgx-template-allowlist": list(TEMPLATE_NAMES),
        "x-pgx-security-headers": dict(sorted(SECURITY_HEADERS.items())),
        "x-pgx-html-gate": gate_contract(),
        "x-pgx-routes": [
            {"name": route.name, "method": route.method, "path": route.path,
             "template": route.template, "public": route.access.public,
             "permitted_roles": list(route.access.role_names),
             "requires_csrf": route.requires_csrf,
             "success_status": route.success_status,
             "title_key": route.title_key,
             "navigation_key": route.nav_key,
             "parameters": [
                 {"name": parameter.name, "in": parameter.location,
                  "kind": parameter.kind, "required": parameter.required,
                  "pattern": parameter.pattern,
                  "max_length": parameter.max_length,
                  "minimum": parameter.minimum, "maximum": parameter.maximum}
                 for parameter in route.parameters],
             "description": route.description}
            for route in WEB_ROUTES],
    }


def _case_catalog_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "demo-case-catalog.schema.json",
        "title": "WP-17 development case catalogue",
        "description": (
            "Synthetic development cases for demonstration. Every case is "
            "DEVELOPMENT, synthetic, and explicitly not validation evidence "
            "and not holdout data. There is no property in which an expected "
            "result could be recorded, so a catalogue of these cases cannot "
            "be scored and cannot become a pass rate."),
        "type": "object",
        "x-pgx-artifact-kind": "SOURCE_DERIVED_AND_AUTHORED",
        "x-pgx-forbidden-properties": sorted(FORBIDDEN_CASE_FIELDS),
        "required": ["schema_version", "migration_version", "case_role",
                     "is_validation_evidence", "contains_holdout",
                     "case_count", "source", "cases"],
        "properties": {
            "schema_version": {"const": CASE_CATALOG_SCHEMA_VERSION},
            "migration_version": {"const": MIGRATION_VERSION},
            "case_role": {"const": "DEVELOPMENT"},
            "is_validation_evidence": {"const": False},
            "contains_holdout": {"const": False},
            "case_count": {"type": "integer", "minimum": 1},
            "migrated_case_count": {"type": "integer", "minimum": 0},
            "authored_case_count": {"type": "integer", "minimum": 0},
            "cases": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["schema_version", "case_id", "label",
                                 "case_role", "is_synthetic",
                                 "is_validation_evidence", "is_holdout",
                                 "observations", "no_pii_assertion"],
                    "properties": {
                        "schema_version": {
                            "const": CASE_CATALOG_SCHEMA_VERSION},
                        "case_id": {"type": "string",
                                    "pattern": r"^WP17-CASE-[A-Z0-9][A-Z0-9-]{0,31}$"},
                        "label": {"type": "string", "maxLength": 256},
                        "case_role": {"const": "DEVELOPMENT"},
                        "is_synthetic": {"const": True},
                        "is_validation_evidence": {"const": False},
                        "is_holdout": {"const": False},
                        "legacy_profile_key": {
                            "anyOf": [{"type": "string"}, {"type": "null"}]},
                        "source_file": {
                            "anyOf": [{"type": "string"}, {"type": "null"}]},
                        "source_file_sha256": {
                            "anyOf": [{"type": "string",
                                       "pattern": r"^sha256:[0-9a-f]{64}$"},
                                      {"type": "null"}]},
                        "migration_note": {"type": "string"},
                        "demonstrates": {"type": "string"},
                        "no_pii_assertion": {"type": "string"},
                        "observation_count": {"type": "integer", "minimum": 1},
                        "observations": {
                            "type": "array", "minItems": 1,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["gene", "value"],
                                "properties": {
                                    "gene": {"type": "string",
                                             "pattern": r"^GENE:[A-Z0-9][A-Z0-9\-.@_]{0,48}$"},
                                    "value": {"type": "string",
                                              "pattern": r"^[A-Z][A-Z_]{0,31}$"},
                                }}},
                    }}},
        },
    }


def _ui_gate_status_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "ui-gate-status.schema.json",
        "title": "WP-17 interface gate status",
        "description": (
            "What the interface can actually do, reported as separate "
            "answers. Template runtime, ASGI runtime, browser runtime, "
            "screenshot evidence, accessibility testing, claim scanning, the "
            "inherited API status, PostgreSQL, authentication, CSRF, the "
            "claim boundary, the active release and every count are distinct "
            "questions and are never collapsed into one boolean."),
        "type": "object",
        "x-pgx-artifact-kind": "RUNTIME_MEASURED",
        "required": [
            "gate_status_schema_version", "work_package",
            "implementation_status", "template_runtime_available",
            "asgi_runtime_available", "asgi_runtime_tests_executed",
            "browser_runtime_available", "screenshot_evidence_status",
            "accessibility_structural_tests_available", "claim_scan_executed",
            "claim_scan_clean", "api_runtime_verification",
            "postgresql_runtime_available", "authentication_implemented",
            "csrf_implemented", "session_management_implemented",
            "claim_boundary_approved", "active_release_available",
            "real_assessment_count", "real_report_count",
            "real_validation_case_count", "development_case_count",
            "expert_review_workflow_status", "validation_dashboard_status",
            "wp18_started", "blockers", "may_serve_real_traffic"],
        "properties": {
            "gate_status_schema_version": {
                "const": UI_GATE_STATUS_SCHEMA_VERSION},
            "work_package": {"const": "WP-17"},
            "implementation_status": {"enum": ["IMPLEMENTED", "PARTIAL",
                                               "NOT_STARTED"]},
            "screenshot_evidence_status": {
                "enum": list(SCREENSHOT_EVIDENCE_STATUSES),
                "description": (
                    "NONE means no screenshot exists. A rendered HTML "
                    "snapshot is never BROWSER_CAPTURED.")},
            "expert_review_workflow_status": {
                "enum": ["NOT_IMPLEMENTED", "IMPLEMENTED"]},
            "validation_dashboard_status": {
                "enum": ["EMPTY_STATE_ONLY", "POPULATED"]},
            "real_assessment_count": {"type": "integer", "minimum": 0},
            "real_report_count": {"type": "integer", "minimum": 0},
            "real_validation_case_count": {"type": "integer", "minimum": 0},
            "development_case_count": {"type": "integer", "minimum": 0},
            "holdout_case_count": {
                "anyOf": [{"type": "integer", "minimum": 0},
                          {"type": "null"}],
                "description": (
                    "null while holdout storage is not implemented. Never 0: "
                    "a zero would say a count was taken.")},
            "wp18_started": {"type": "boolean"},
            "may_serve_real_traffic": {"type": "boolean"},
        },
    }


def _derived_artifacts() -> Dict[str, str]:
    catalog = build_catalog()
    # Rendered first, then handed to the manifest, so the manifest can state
    # the hash of the bytes that are actually written rather than of a
    # serialisation nobody has on disk.
    catalog_text = _json(catalog)
    return {
        "schemas/wp17/web-route-surface.schema.json": _json(_route_surface()),
        "schemas/wp17/demo-case-catalog.schema.json":
            _json(_case_catalog_schema()),
        "schemas/wp17/ui-gate-status.schema.json":
            _json(_ui_gate_status_schema()),
        "data/demo/wp17-development-cases.json": catalog_text,
        "data/demo/wp17-demo-case-manifest.json":
            _json(build_manifest(catalog, rendered=catalog_text)),
    }


def build_artifacts() -> Dict[str, str]:
    """Every artifact, as rendered text, keyed by repository-relative path."""
    rendered = _derived_artifacts()
    rendered[GATE_STATUS_PATH] = _json(build_ui_gate_status())
    return rendered


def write_artifacts(root: str = _ROOT) -> Dict[str, str]:
    """Write every artifact under ``root``, catalogue before gate status.

    The order matters for the same reason it does in the API's generator: the
    gate status *measures* the tree - including whether the sealed catalogue
    is readable - so it has to be produced after the catalogue is on disk.
    """
    rendered = _derived_artifacts()
    for relative, text in sorted(rendered.items()):
        path = os.path.join(root, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    gate_status = _json(build_ui_gate_status())
    path = os.path.join(root, GATE_STATUS_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as handle:
        handle.write(gate_status)
    rendered[GATE_STATUS_PATH] = gate_status
    return rendered


def main(argv=None) -> int:
    """Regenerate every WP-17 artifact in place."""
    written = write_artifacts()
    for relative in sorted(written):
        print("%8d  %s" % (len(written[relative]), relative))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
