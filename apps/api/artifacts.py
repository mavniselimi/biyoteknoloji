"""Every WP-16 artifact, generated from the declarations that produce the API.

Six JSON documents under ``schemas/wp16/`` plus the OpenAPI document under
``schemas/openapi/`` and the gate status under ``data/api/``. All of them are
derived, none is maintained by hand, and
:mod:`tests.unit.api.test_artifacts` asserts that what is committed is
byte-for-byte what this module produces.

The reason to publish them at all is that a consumer should be able to
validate against this contract without running the application - and in this
repository, *nobody* can run the application, because the framework cannot be
installed here. An artifact generated from the same declaration the routers
register from is the strongest statement about the contract that this
environment can make, and it is a considerably stronger one than a document
somebody typed.

The gate status is the exception to "derived from declarations": it is derived
from *measurement* - imports attempted, directories walked, artifacts
compared - and so it changes when the environment changes rather than when the
code does. It is written here anyway so that one command refreshes everything
a reviewer reads.
"""

from __future__ import annotations

import io
import json
import os
from typing import Any, Dict, Mapping

from apps.api.contracts.spec import (CONTRACT_VERSION, CONTROL_CHARACTER_RANGES,
                                     LIMITS, MODELS, PROHIBITED_REQUEST_FIELDS)
from apps.api.errors import ENGINE_CODE_STATUS, ERROR_CATALOGUE
from apps.api.gate_status import (GATE_STATUS_SCHEMA_VERSION,
                                  OPENAPI_RELATIVE_PATH, build_gate_status)
from apps.api.openapi import build_document, canonical_json
from apps.api.readiness import (ADVISORY_COMPONENTS, BLOCKING_COMPONENTS,
                                DETAILS)
from apps.api.routes import ROUTES

__all__ = ["ARTIFACT_PATHS", "GATE_STATUS_PATH", "OPENAPI_PATH",
           "build_artifacts", "load_artifact", "load_artifact_text",
           "load_openapi_document", "main", "write_artifacts"]

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

#: The committed OpenAPI document. Named rather than spelled at call sites:
#: several modules wanted to read it and each had begun opening it by hand.
#: The string itself belongs to ``apps.api.gate_status``, which measures the
#: file and cannot import this module without a cycle; re-exported here so
#: callers have one name to use.
OPENAPI_PATH = OPENAPI_RELATIVE_PATH

#: Every path this module owns, relative to the repository root.
ARTIFACT_PATHS = (
    OPENAPI_PATH,
    "schemas/wp16/api-contract.schema.json",
    "schemas/wp16/prohibited-request-fields.schema.json",
    "schemas/wp16/error-contract.schema.json",
    "schemas/wp16/readiness.schema.json",
    "schemas/wp16/gate-status.schema.json",
    "schemas/wp16/route-surface.schema.json",
    "data/api/wp16-real-gate-status.json",
)

#: Written by `python -m apps.api.runtime_verification`, not by this module.
#: Named here so a reader of the artifact list can see it exists and see that
#: it is produced by a different command - a gate status that generated its
#: own evidence would be marking its own homework.
RUNTIME_VERIFICATION_EVIDENCE_PATH = "data/api/wp16-runtime-verification.json"

_BASE = "https://pgx.local/schemas/wp16/"


def _json(document: Mapping[str, Any]) -> str:
    """Canonical bytes: sorted keys, two-space indent, ASCII, one newline.

    The same rendering for every artifact, so a diff of any of them is a diff
    of content rather than of formatting.
    """
    return json.dumps(document, indent=2, sort_keys=True,
                      ensure_ascii=True) + "\n"


def _api_contract() -> Dict[str, Any]:
    from apps.api.openapi import _model_schema
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "api-contract.schema.json",
        "title": "PGx API transport contract (WP-16)",
        "description": (
            "Every request and response document this API exchanges, "
            "generated from apps/api/contracts/spec.py - the same declaration "
            "that produces the runtime validator, the Pydantic models and the "
            "OpenAPI document. Published so a consumer can validate against "
            "the contract without running the application."),
        "x-pgx-contract-version": CONTRACT_VERSION,
        "x-pgx-limits": dict(sorted(LIMITS.items())),
        "x-pgx-control-character-ranges": [list(pair) for pair
                                           in CONTROL_CHARACTER_RANGES],
        "$defs": {name: _model_schema(model)
                  for name, model in sorted(MODELS.items())},
    }


def _prohibited_fields() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "prohibited-request-fields.schema.json",
        "title": "Request field names this API refuses (WP-16)",
        "description": (
            "A field with any of these names refuses the whole request, at any "
            "depth, and its value is never echoed in the error. Three groups: "
            "raw genetic data this system does not interpret, identifiable or "
            "clinical text it has no reason to hold, and answers only the "
            "server may determine."),
        "type": "object",
        "propertyNames": {"not": {"enum": sorted(PROHIBITED_REQUEST_FIELDS)}},
        "x-pgx-prohibited-fields": {
            name: reason for name, reason
            in sorted(PROHIBITED_REQUEST_FIELDS.items())},
    }


def _error_contract() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "error-contract.schema.json",
        "title": "PGx API error envelope (WP-16)",
        "description": (
            "The one shape every 4xx and 5xx response takes. The message is "
            "always the catalogue's fixed text for the code; it is never built "
            "from an exception, and it never carries a value the caller sent."),
        "allOf": [{"$ref": "api-contract.schema.json#/$defs/ErrorEnvelope"}],
        "x-pgx-error-catalogue": {
            code: {"status": status, "message": message}
            for code, (status, message) in sorted(ERROR_CATALOGUE.items())},
        "x-pgx-engine-code-mapping": dict(sorted(ENGINE_CODE_STATUS.items())),
        "x-pgx-statuses": sorted({status for status, _
                                  in ERROR_CATALOGUE.values()}),
    }


def _readiness() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "readiness.schema.json",
        "title": "PGx API readiness report (WP-16)",
        "description": (
            "Independent component checks. READY only when every blocking "
            "component is ready. Details are drawn from a fixed catalogue: no "
            "connection string, path or exception text can appear here."),
        "allOf": [{"$ref": "api-contract.schema.json#/$defs/ReadinessResponse"}],
        "x-pgx-blocking-components": list(BLOCKING_COMPONENTS),
        "x-pgx-advisory-components": list(ADVISORY_COMPONENTS),
        "x-pgx-detail-catalogue": dict(sorted(DETAILS.items())),
        "x-pgx-external-services-excluded": (
            "No third-party service is a component. P0 readiness must not "
            "depend on anyone else's availability."),
    }


def _gate_status_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "gate-status.schema.json",
        "title": "WP-16 API gate status",
        "description": (
            "What this deployment can actually do, reported as separate "
            "answers. Implementation, dependency availability, ASGI runtime "
            "status, PostgreSQL status, OpenAPI verification, the claim "
            "boundary, authentication, the active release and the real-record "
            "counts are nine different questions and are never collapsed into "
            "one boolean."),
        "type": "object",
        "required": [
            "gate_status_schema_version", "work_package",
            "implementation_status", "api_dependencies_available",
            "asgi_runtime_tests_executed", "postgresql_runtime_available",
            "openapi", "claim_boundary_approved", "authentication_implemented",
            "asgi_runtime_test_status", "runtime_verification_reason",
            "active_release_available", "real_assessment_count",
            "real_api_assessment_count", "real_report_count",
            "synthetic_fixture_count", "wp17_started", "blockers",
            "may_serve_real_traffic"],
        "properties": {
            "gate_status_schema_version": {"const": GATE_STATUS_SCHEMA_VERSION},
            "work_package": {"const": "WP-16"},
            "implementation_status": {"enum": ["IMPLEMENTED", "PARTIAL",
                                               "NOT_STARTED"]},
            # Four words, not two, and none of them is "AVAILABLE". The old
            # pair could only say whether the packages were there; these say
            # what happened. "BLOCKED" is the no-evidence default,
            # "VERIFICATION_FAILED" is a run that did not pass, and
            # "STALE_EVIDENCE_REJECTED" is a passing run whose inputs have
            # since changed - three states a single boolean would merge into
            # "not verified" and a reader could not act on.
            "asgi_runtime_test_status": {
                "enum": ["VERIFIED", "BLOCKED", "VERIFICATION_FAILED",
                         "STALE_EVIDENCE_REJECTED"]},
            "asgi_runtime_tests_executed": {"type": "boolean"},
            "runtime_verification_evidence_path": {"type": "string"},
            "runtime_verification_reason": {"type": "string"},
            "runtime_verification_evidence": {
                "type": ["object", "null"],
                "description": (
                    "A summary of the recorded run: schema version, whether "
                    "it passed, when, the stack it ran on, and each check "
                    "with its result. Null when no evidence exists."),
            },
            "real_assessment_count": {"type": "integer", "minimum": 0},
            "real_api_assessment_count": {"type": "integer", "minimum": 0},
            "real_report_count": {"type": "integer", "minimum": 0},
            "synthetic_fixture_count": {"type": "integer", "minimum": 0},
            # A boolean, not a constant. It reported False while WP-16 was
            # the current work package; it reports True now that apps/web
            # exists. A schema pinning it would have made the gate status
            # invalid the moment the next package started.
            "wp17_started": {"type": "boolean"},
            "may_serve_real_traffic": {"type": "boolean"},
        },
    }


def _route_surface() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE + "route-surface.schema.json",
        "title": "PGx API P0 route surface (WP-16)",
        "description": (
            "The closed list of operations. A route not on this list does not "
            "exist, and adding one means changing this artifact."),
        "type": "array",
        "x-pgx-routes": [
            {"operation_id": route.operation_id, "method": route.method,
             "path": route.path, "success_status": route.success_status,
             "public": route.access.public,
             "permitted_roles": list(route.access.role_names),
             "request_model": route.request_model,
             "response_model": route.response_model,
             "implemented": route.implemented,
             "superseded_by": route.superseded_by,
             "error_codes": list(route.all_error_codes)}
            for route in ROUTES],
    }


#: The one artifact that is *measured* rather than derived, and therefore the
#: one that must be produced last. See :func:`write_artifacts`.
GATE_STATUS_PATH = "data/api/wp16-real-gate-status.json"


# The committed OpenAPI artifact is written with ``runtime_verified=False``,
# always, and that is deliberate.
#
# The obvious alternative - stamp VERIFIED into the file once verification
# passes - makes the artifact a function of the evidence, and the evidence a
# function of the artifact, because verification compares the served document
# with this file. The loop is not theoretical: it produces a state where any
# edit under ``apps/api`` invalidates the evidence, which changes what the
# application serves, which makes the byte comparison fail, which fails
# verification - so the only way out is to regenerate, verify, regenerate.
#
# The artifact is a *declaration*: this is the API the contract describes.
# Whether a running application was observed serving it is an *attestation*,
# and attestations live in ``data/api/wp16-runtime-verification.json`` and in
# the gate status that reads it. Keeping them apart is what lets each be
# checked without the other moving.


def _derived_artifacts() -> Dict[str, str]:
    """The artifacts that come from declarations alone."""
    return {
        "schemas/openapi/wp16-openapi.json": canonical_json(build_document()),
        "schemas/wp16/api-contract.schema.json": _json(_api_contract()),
        "schemas/wp16/prohibited-request-fields.schema.json":
            _json(_prohibited_fields()),
        "schemas/wp16/error-contract.schema.json": _json(_error_contract()),
        "schemas/wp16/readiness.schema.json": _json(_readiness()),
        "schemas/wp16/gate-status.schema.json": _json(_gate_status_schema()),
        "schemas/wp16/route-surface.schema.json": _json(_route_surface()),
    }


def load_artifact_text(relative_path: str, root: str = _ROOT) -> str:
    """The committed bytes of one artifact this module owns, as text.

    The reading counterpart of :func:`write_artifacts`, and the only one. It
    exists because the alternative had already started: a test opened
    ``schemas/openapi/wp16-openapi.json`` with its own ``io.open`` and its own
    ``json.load``, the gate status opened the same file a second way, and a
    third caller was about to. Every hand-rolled reader is a chance to differ
    on encoding, on newline handling, or on which path is canonical - and the
    thing being compared is an artifact whose whole purpose is that two
    parties agree on it byte for byte.

    Raises:
        KeyError: the path is not one this module owns. Guarded rather than
            permitted, so this does not quietly become a general-purpose file
            reader pointed at whatever a caller likes.
    """
    if relative_path not in ARTIFACT_PATHS:
        raise KeyError("%s is not an artifact this module owns"
                       % relative_path)
    with io.open(os.path.join(root, *relative_path.split("/")),
                 encoding="utf-8") as handle:
        return handle.read()


def load_artifact(relative_path: str, root: str = _ROOT) -> Dict[str, Any]:
    """One committed artifact, parsed. Every artifact here is JSON."""
    return json.loads(load_artifact_text(relative_path, root=root))


def load_openapi_document(root: str = _ROOT) -> Dict[str, Any]:
    """The committed OpenAPI document.

    What a served document is compared against. The comparison stays
    canonical because both sides go through one loader and one renderer:
    :func:`~apps.api.openapi.canonical_json` produced the file, and callers
    compare either the parsed documents or their canonical renderings - never
    two different hand-made readings of the same file.
    """
    return load_artifact(OPENAPI_PATH, root=root)


def build_artifacts() -> Dict[str, str]:
    """Every artifact, as rendered text, keyed by repository-relative path.

    The gate status is built last and reflects the repository **as it is on
    disk at call time** - including whether the committed OpenAPI artifact
    matches the generator. That is why :func:`write_artifacts` does not simply
    call this and write the result: see its docstring.
    """
    rendered = _derived_artifacts()
    rendered[GATE_STATUS_PATH] = _json(build_gate_status())
    return rendered


def write_artifacts(root: str = _ROOT) -> Dict[str, str]:
    """Write every artifact under ``root``. Returns what was written.

    In two passes, and the order is load-bearing. The gate status *measures*
    the repository - it reads the committed OpenAPI artifact and compares it
    with what the generator produces - so it has to be built after the
    repository is in its final state.

    Building everything first and writing it all at once looked equivalent and
    was not: the gate status was rendered while the OpenAPI file on disk was
    still the previous version, so it recorded
    ``artifact_matches_generator: false`` about a mismatch that the very same
    call was about to fix. The regenerated tree then failed its own freshness
    test, which is exactly the symptom a measured artifact should produce when
    it is measured at the wrong moment.
    """
    rendered = _derived_artifacts()
    for relative, text in sorted(rendered.items()):
        path = os.path.join(root, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    gate_status = _json(build_gate_status(root=root))
    path = os.path.join(root, GATE_STATUS_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as handle:
        handle.write(gate_status)
    rendered[GATE_STATUS_PATH] = gate_status
    return rendered


def main(argv=None) -> int:
    """Regenerate every WP-16 artifact in place."""
    written = write_artifacts()
    for relative in sorted(written):
        print("%8d  %s" % (len(written[relative]), relative))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
