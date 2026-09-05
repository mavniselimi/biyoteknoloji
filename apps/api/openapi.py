"""The OpenAPI document, built from the same declarations the API is built from.

There is one description of this API - :mod:`apps.api.contracts.spec` for the
schemas and :mod:`apps.api.routes` for the surface - and three things read it:
the runtime validator, the FastAPI routers, and this generator. A hand-written
document would be a fourth description, and the first thing to notice that it
had drifted would be a client.

Determinism is the property this module has to have. Every mapping is written
in sorted key order and every list in a defined order, so regenerating the
document on an unchanged tree produces identical bytes. That is what makes the
committed artifact reviewable in a diff and what lets the contract test compare
runtime output to it byte for byte.

**Runtime verification status.** The committed artifact records in
``x-pgx-runtime-verification`` whether a running FastAPI application has served
this document and been compared with it, and
:func:`runtime_verification_status` is the single place that value comes from.

The value is *not* decided here and is not decided by whether FastAPI imports.
It is read from evidence written by ``python -m apps.api.runtime_verification``,
which performs the comparison with :func:`compare_documents` and records the
result. Absent evidence, failed evidence, and evidence whose inputs no longer
match the repository all read as ``BLOCKED``. That is why this module takes
``runtime_verified`` as an argument defaulting to ``False`` rather than
computing it: a document generator that decided it had been verified would be
attesting to its own verification.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from apps.api import API_TITLE, API_VERSION
from apps.api.contracts.spec import (CONTRACT_VERSION, LIMITS, MODELS,
                                     ModelSpec, FieldSpec)
from apps.api.errors import ERROR_CATALOGUE
from apps.api.routes import ROUTES, ParameterSpec, RouteSpec

__all__ = [
    "OPENAPI_VERSION",
    "RUNTIME_VERIFICATION_BLOCKED",
    "build_document",
    "canonical_json",
    "compare_documents",
    "runtime_verification_status",
]

OPENAPI_VERSION = "3.1.0"

#: The value ``x-pgx-runtime-verification`` carries while the framework cannot
#: be installed. A word, not a boolean, so a reader of the artifact cannot mistake
#: "not verified" for "verified false".
RUNTIME_VERIFICATION_BLOCKED = "BLOCKED"

_SECURITY_SCHEME = "PgxPrincipal"

_DESCRIPTION = (
    "Structured pharmacogenomic coverage and attention facts.\n"
    "\n"
    "This API reports what governed rules said about the axes that could be "
    "evaluated (attention) and how much of the question could be evaluated "
    "(coverage). It reports the two together and neither summarises the "
    "other.\n"
    "\n"
    "It does not diagnose, does not prescribe, does not calculate a dose, "
    "does not select or rank a medicine, and does not tell anyone to change "
    "a medicine. Every example in this document is synthetic: no example "
    "here is a real case, a real assessment, a real evidence record or a real "
    "credential."
)


def _scalar_schema(kind: str, *, pattern: Optional[str] = None,
                   min_length: Optional[int] = None,
                   max_length: Optional[int] = None,
                   enum_values: Sequence[str] = (),
                   minimum: Optional[int] = None,
                   maximum: Optional[int] = None) -> Dict[str, Any]:
    """One scalar kind as a JSON Schema fragment.

    Shared by fields and by array items. Written once because the first
    version of this module built item schemas inline from ``item_kind``, which
    emitted ``{"type": "enum"}`` and ``{"type": "uuid"}`` - not valid types,
    and worse, a document that told a generated client the coverage reason
    codes were unconstrained strings.
    """
    if kind == "string":
        schema: Dict[str, Any] = {"type": "string"}
        if pattern:
            schema["pattern"] = pattern
        if min_length is not None:
            schema["minLength"] = min_length
        if max_length is not None:
            schema["maxLength"] = max_length
        return schema
    if kind == "integer":
        schema = {"type": "integer"}
        if minimum is not None:
            schema["minimum"] = minimum
        if maximum is not None:
            schema["maximum"] = maximum
        return schema
    if kind == "boolean":
        return {"type": "boolean"}
    if kind == "enum":
        return {"type": "string", "enum": list(enum_values)}
    if kind == "uuid":
        return {"type": "string", "format": "uuid", "maxLength": 36}
    if kind == "digest":
        return {"type": "string", "pattern": r"^sha256:[0-9a-f]{64}$",
                "maxLength": 71}
    raise ValueError("no schema for kind %r" % kind)  # pragma: no cover


def _field_schema(field: FieldSpec) -> Dict[str, Any]:
    """One field as an OpenAPI 3.1 schema, bounds included.

    Every bound the validator enforces is written into the document. A schema
    that omitted them would describe an API that accepts more than this one
    does, and a generated client built from it would send requests this API
    refuses.
    """
    schema: Dict[str, Any] = {}
    if field.kind == "object":
        schema["$ref"] = "#/components/schemas/" + field.model
    elif field.kind == "array":
        schema["type"] = "array"
        if field.item_model:
            schema["items"] = {
                "$ref": "#/components/schemas/" + field.item_model}
        else:
            schema["items"] = _scalar_schema(
                field.item_kind or "string", pattern=field.item_pattern,
                max_length=field.item_max_length,
                enum_values=field.item_enum_values)
        if field.min_items is not None:
            schema["minItems"] = field.min_items
        if field.max_items is not None:
            schema["maxItems"] = field.max_items
        if field.unique_items:
            schema["uniqueItems"] = True
    else:
        schema = _scalar_schema(
            field.kind, pattern=field.pattern, min_length=field.min_length,
            max_length=field.max_length, enum_values=field.enum_values,
            minimum=field.minimum, maximum=field.maximum)

    if field.nullable and "$ref" not in schema:
        # 3.1 has no `nullable`; a nullable value is a union with null.
        schema = {"anyOf": [schema, {"type": "null"}]}
    elif field.nullable:
        schema = {"anyOf": [{"$ref": schema["$ref"]}, {"type": "null"}]}
    if field.description:
        schema["description"] = field.description
    return schema


def _model_schema(model: ModelSpec) -> Dict[str, Any]:
    required = [field.name for field in model.fields if field.required]
    return {
        "type": "object",
        "title": model.name,
        "description": model.description,
        # Mirrors ``extra="forbid"``. A document that allowed extra properties
        # would tell a client the API accepts fields it refuses.
        "additionalProperties": False,
        "properties": {field.name: _field_schema(field)
                       for field in sorted(model.fields,
                                           key=lambda item: item.name)},
        "required": sorted(required),
    }


def _parameter(parameter: ParameterSpec) -> Dict[str, Any]:
    schema: Dict[str, Any] = {"type": parameter.kind}
    if parameter.pattern:
        schema["pattern"] = parameter.pattern
    if parameter.max_length is not None:
        schema["maxLength"] = parameter.max_length
    if parameter.minimum is not None:
        schema["minimum"] = parameter.minimum
    if parameter.maximum is not None:
        schema["maximum"] = parameter.maximum
    if parameter.default is not None:
        schema["default"] = parameter.default
    return {
        "name": parameter.name,
        "in": parameter.location,
        "required": parameter.required,
        "description": parameter.description,
        "schema": schema,
    }


def _error_response(code: str) -> Dict[str, Any]:
    status, message = ERROR_CATALOGUE[code]
    return {
        "description": "%s - %s" % (code, message),
        "content": {"application/json": {
            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
            "example": {"error": {
                "code": code,
                "message": message,
                "details": {},
                "request_id": "00000000-0000-4000-8000-000000000000"}}}},
    }


def _responses(route: RouteSpec) -> Dict[str, Any]:
    responses: Dict[str, Any] = {}
    if route.implemented:
        responses[str(route.success_status)] = {
            "description": route.summary,
            "content": {"application/json": {"schema": {
                "$ref": "#/components/schemas/" + route.response_model}}},
        }
    by_status: Dict[int, List[str]] = {}
    for code in route.all_error_codes:
        by_status.setdefault(ERROR_CATALOGUE[code][0], []).append(code)
    for status, codes in sorted(by_status.items()):
        # One representative example per status, and every code for that
        # status named in the description: a client handling 4xx needs the
        # full code list, and repeating the envelope schema per code would
        # make the document unreadable without adding information.
        primary = sorted(codes)[0]
        response = _error_response(primary)
        response["description"] = "%s. Codes: %s" % (
            response["description"].split(" - ", 1)[1].rstrip("."),
            ", ".join(sorted(codes)))
        responses[str(status)] = response
    return responses


def _operation(route: RouteSpec) -> Dict[str, Any]:
    operation: Dict[str, Any] = {
        "operationId": route.operation_id,
        "summary": route.summary,
        "description": route.description,
        "tags": [route.tag],
        "responses": _responses(route),
    }
    if route.parameters:
        operation["parameters"] = [_parameter(item)
                                   for item in route.parameters]
    if route.request_model:
        operation["requestBody"] = {
            "required": True,
            "content": {"application/json": {"schema": {
                "$ref": "#/components/schemas/" + route.request_model}}},
        }
    if not route.access.public:
        operation["security"] = [{_SECURITY_SCHEME: []}]
        operation["x-pgx-required-roles"] = list(route.access.role_names)
    else:
        operation["security"] = []
    if not route.implemented:
        operation["deprecated"] = False
        operation["x-pgx-not-implemented"] = True
        operation["x-pgx-superseded-by"] = route.superseded_by
    return operation


def build_document(*, runtime_verified: bool = False) -> Dict[str, Any]:
    """Build the whole document.

    Args:
        runtime_verified: whether this document has been compared against
            one served by a running FastAPI application. Defaults to
            ``False``, which is the only honest value for a caller that has
            not consulted the evidence. Callers that should - the application
            factory and the artifact writer - pass
            ``verified_runtime_status()["openapi_runtime_verified"]``, so both
            the served document and the committed artifact carry the same
            answer and the byte-for-byte comparison between them stays
            meaningful.
    """
    paths: Dict[str, Dict[str, Any]] = {}
    for route in ROUTES:
        paths.setdefault(route.path, {})[route.method.lower()] = \
            _operation(route)

    return {
        "openapi": OPENAPI_VERSION,
        "info": {
            "title": API_TITLE,
            "version": API_VERSION,
            "description": _DESCRIPTION,
            "x-pgx-contract-version": CONTRACT_VERSION,
        },
        "x-pgx-runtime-verification": runtime_verification_status(
            runtime_verified),
        "x-pgx-limits": dict(sorted(LIMITS.items())),
        "tags": [
            {"name": "assessments", "description":
                "Execute and read structured assessments."},
            {"name": "catalogue", "description":
                "What the pinned release covers. Ordered by canonical key, "
                "never ranked."},
            {"name": "evidence", "description":
                "Immutable evidence provenance by record identity."},
            {"name": "expert-review", "description":
                "Reserved for WP-22. Every operation here refuses."},
            {"name": "health", "description":
                "Liveness and readiness."},
            {"name": "system", "description":
                "The active release and the versions it pins."},
        ],
        "paths": {path: dict(sorted(operations.items()))
                  for path, operations in sorted(paths.items())},
        "components": {
            "schemas": {name: _model_schema(model)
                        for name, model in sorted(MODELS.items())},
            "securitySchemes": {
                _SECURITY_SCHEME: {
                    "type": "http",
                    "scheme": "bearer",
                    "description": (
                        "A stub contract, not an implemented scheme. WP-23 "
                        "owns authentication; this deployment establishes a "
                        "principal through a configured provider and refuses "
                        "with 503 when none is configured. No token is issued "
                        "by this API and no login endpoint exists."),
                    "x-pgx-implemented": False,
                    "x-pgx-owned-by": "WP-23",
                },
            },
        },
    }


def runtime_verification_status(verified: bool) -> Dict[str, Any]:
    """How this document was produced, stated in the document itself."""
    if verified:
        return {
            "status": "VERIFIED",
            "note": ("Generated by the running FastAPI application and "
                     "compared byte for byte with the committed artifact."),
        }
    return {
        "status": RUNTIME_VERIFICATION_BLOCKED,
        "note": ("Generated from the declarative contract, not attested by a "
                 "running FastAPI application. No current evidence of a "
                 "successful runtime comparison exists: either none has been "
                 "recorded, the last run did not pass, or the inputs have "
                 "changed since it did. Run "
                 "`python -m apps.api.runtime_verification` to perform the "
                 "comparison and record the result."),
        "blocked_on": ["fastapi", "pydantic"],
    }


def canonical_json(document: Mapping[str, Any]) -> str:
    """The document as bytes that a diff can be trusted on.

    Sorted keys, fixed separators, ASCII-escaped, one trailing newline. The
    comparison test compares these strings rather than parsed objects, because
    a comparison of parsed objects would pass on a document whose key order
    changes on every regeneration - and a committed artifact nobody can review
    in a diff is a committed artifact nobody reviews.
    """
    return json.dumps(document, sort_keys=True, indent=2,
                      ensure_ascii=True, separators=(",", ": ")) + "\n"


def compare_documents(generated: Mapping[str, Any],
                      committed: Mapping[str, Any]) -> Tuple[bool, List[str]]:
    """Compare a runtime-generated document with the committed artifact.

    Ignores only ``x-pgx-runtime-verification``, which by construction differs
    between the two: the committed artifact records that it was not runtime
    verified, and a document generated by a running application is the
    evidence that it now can be. Everything else - every path, every operation
    id, every schema, every bound - must match exactly.

    Returns:
        ``(identical, differences)`` where each difference is a JSON pointer.
        Pointers rather than a diff of values: this runs in a test whose
        failure output should say *where* to look without reproducing a
        thousand-line document into a log.
    """
    def strip(document: Mapping[str, Any]) -> Dict[str, Any]:
        copy = dict(document)
        copy.pop("x-pgx-runtime-verification", None)
        return copy

    left, right = strip(generated), strip(committed)
    differences: List[str] = []

    def walk(a: Any, b: Any, pointer: str) -> None:
        if isinstance(a, Mapping) and isinstance(b, Mapping):
            for key in sorted(set(a) | set(b)):
                if key not in a or key not in b:
                    differences.append("%s/%s" % (pointer, key))
                else:
                    walk(a[key], b[key], "%s/%s" % (pointer, key))
        elif isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                differences.append(pointer)
                return
            for index, (one, two) in enumerate(zip(a, b)):
                walk(one, two, "%s/%d" % (pointer, index))
        elif a != b:
            differences.append(pointer)

    walk(left, right, "")
    return (not differences), differences[:50]
