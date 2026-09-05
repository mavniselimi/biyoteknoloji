# -*- coding: utf-8 -*-
"""Loading and applying the raw snapshot manifest JSON Schema (WP-06).

Standard library only. Lives in the application layer for the same reason
:mod:`pgx.application.release_schema` does: reading a file is an environment
concern, and neither the domain nor the ingestion package grows a filesystem
dependency for it.

**Why a validator here rather than a library.** No JSON Schema package can be
installed in this environment, and a manifest whose schema is published but
never applied is a schema nobody is bound by. So this module implements the
subset the snapshot schema actually uses - ``type``, ``const``, ``enum``,
``required``, ``additionalProperties: false``, ``pattern``, ``minimum``,
``minLength``, ``maxLength``, ``items``, ``anyOf`` and local ``$ref`` - and
refuses any keyword it does not implement.

That last rule is the important one. A validator that silently ignored an
unknown keyword would report a manifest as valid while quietly not checking the
constraint the schema author wrote, which is worse than having no validator:
the schema would look enforced and would not be. Adding a keyword to the schema
without teaching it to this module therefore fails loudly here.
"""

from __future__ import annotations

import io
import json
import os
import re
from typing import Any, Dict, List, Mapping, Tuple

__all__ = [
    "SNAPSHOT_MANIFEST_SCHEMA_PATH",
    "SchemaSupportError",
    "load_snapshot_manifest_schema",
    "validate_against_schema",
    "validate_snapshot_manifest",
]

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

SNAPSHOT_MANIFEST_SCHEMA_PATH = os.path.join(
    _REPO_ROOT, "schemas", "raw-snapshot-manifest.schema.json")

#: Keywords this validator implements. Anything else in a schema raises.
_SUPPORTED = frozenset({
    "$schema", "$id", "$defs", "$ref", "title", "description", "type", "const",
    "enum", "required", "additionalProperties", "properties", "pattern",
    "minimum", "maximum", "minLength", "maxLength", "items", "anyOf", "oneOf",
    "not", "minItems", "maxItems", "uniqueItems", "minProperties",
    # Added for WP-10, which needs to say things the earlier schemas did not:
    # "a RAW work item names no submitted revision, a CURATED one does"
    # (if/then), "all of these hold at once" (allOf), and "every key of this
    # object is namespaced" (propertyNames). Implemented rather than admitted:
    # this validator's whole contract is that a keyword it accepts is a
    # keyword it checks.
    "allOf", "if", "then", "else", "propertyNames",
})

_TYPE_CHECKS = {
    "object": lambda value: isinstance(value, Mapping),
    "array": lambda value: isinstance(value, list),
    "string": lambda value: isinstance(value, str),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "number": lambda value: (isinstance(value, (int, float))
                             and not isinstance(value, bool)),
    "boolean": lambda value: isinstance(value, bool),
    "null": lambda value: value is None,
}


class SchemaSupportError(Exception):
    """The schema uses a keyword this validator does not implement.

    Raised rather than ignored: a constraint that is published and unchecked is
    a false assurance.
    """


def load_snapshot_manifest_schema(
    path: str = SNAPSHOT_MANIFEST_SCHEMA_PATH,
) -> Mapping[str, Any]:
    """Read the published snapshot manifest schema."""
    with io.open(path, encoding="utf-8") as handle:
        return json.loads(handle.read())


def validate_snapshot_manifest(
    payload: Mapping[str, Any],
    schema: Mapping[str, Any] = None,
) -> Tuple[str, ...]:
    """Return every way ``payload`` fails the published schema.

    An empty tuple means it validates. Problems are collected rather than
    raised on the first one, because a manifest under repair should show the
    whole list.
    """
    return validate_against_schema(
        payload, schema if schema is not None else load_snapshot_manifest_schema())


def validate_against_schema(
    payload: Any, schema: Mapping[str, Any]
) -> Tuple[str, ...]:
    """Validate a document against a supported subset of JSON Schema."""
    problems: List[str] = []
    _check(payload, schema, schema, "$", problems)
    return tuple(problems)


def _resolve(schema: Mapping[str, Any], root: Mapping[str, Any],
             path: str) -> Mapping[str, Any]:
    """Follow a local ``$ref``. Remote references are deliberately unsupported.

    A schema that reached across the network to validate a manifest would make
    verification depend on connectivity, which is exactly what a snapshot must
    not need.
    """
    reference = schema.get("$ref")
    if reference is None:
        return schema
    if not isinstance(reference, str) or not reference.startswith("#/"):
        raise SchemaSupportError(
            "only local '#/...' references are supported, got %r at %s"
            % (reference, path))
    node: Any = root
    for step in reference[2:].split("/"):
        if not isinstance(node, Mapping) or step not in node:
            raise SchemaSupportError("cannot resolve %r at %s" % (reference, path))
        node = node[step]
    merged: Dict[str, Any] = dict(node)
    for key, value in schema.items():
        if key != "$ref":
            merged.setdefault(key, value)
    return merged


def _check(value: Any, schema: Mapping[str, Any], root: Mapping[str, Any],
           path: str, problems: List[str]) -> None:
    if not isinstance(schema, Mapping):
        raise SchemaSupportError("schema at %s is not an object" % path)
    unsupported = sorted(set(schema) - _SUPPORTED)
    if unsupported:
        raise SchemaSupportError(
            "schema at %s uses unimplemented keyword(s): %s. A published "
            "constraint that is not checked is a false assurance."
            % (path, ", ".join(unsupported)))

    schema = _resolve(schema, root, path)

    if "const" in schema and value != schema["const"]:
        problems.append("%s: expected %r, got %r" % (path, schema["const"], value))
        return

    if "enum" in schema and value not in schema["enum"]:
        problems.append("%s: %r is not one of %s"
                        % (path, value, ", ".join(map(repr, schema["enum"]))))
        return

    # ``not`` is checked before the branch keywords and before type, because
    # it is a whole-schema refusal: a value that matches the forbidden shape is
    # wrong however well it satisfies everything else. This is what lets a
    # published schema say "this object must not carry a project risk field"
    # rather than only saying so in its description.
    if "not" in schema:
        collected: List[str] = []
        _check(value, schema["not"], root, path, collected)
        if not collected:
            problems.append("%s: %r matches a forbidden form"
                            % (path, _abbrev(value)))
            return

    # ``allOf`` is not a branch: every subschema must hold, so each one's
    # problems are the value's problems. Checked before the branch keywords so
    # a schema combining both reports the definite failures rather than only
    # "matches none of the permitted forms".
    if "allOf" in schema:
        for index, branch in enumerate(schema["allOf"]):
            _check(value, branch, root, "%s/allOf[%d]" % (path, index),
                   problems)

    # ``if``/``then``/``else``. The condition's own failures are never
    # reported: a value that does not match ``if`` has not done anything
    # wrong, it has selected the other branch.
    if "if" in schema:
        condition: List[str] = []
        _check(value, schema["if"], root, path, condition)
        chosen = "then" if not condition else "else"
        if chosen in schema:
            _check(value, schema[chosen], root, path, problems)

    if "anyOf" in schema or "oneOf" in schema:
        branches = schema.get("anyOf") or schema.get("oneOf")
        for branch in branches:
            collected: List[str] = []
            _check(value, branch, root, path, collected)
            if not collected:
                break
        else:
            problems.append("%s: %r matches none of the %d permitted forms"
                            % (path, _abbrev(value), len(branches)))
        return

    declared = schema.get("type")
    if declared is not None:
        names = [declared] if isinstance(declared, str) else list(declared)
        for name in names:
            if name not in _TYPE_CHECKS:
                raise SchemaSupportError("unknown type %r at %s" % (name, path))
        if not any(_TYPE_CHECKS[name](value) for name in names):
            problems.append("%s: expected %s, got %s"
                            % (path, " or ".join(names), _type_name(value)))
            return

    if isinstance(value, str):
        pattern = schema.get("pattern")
        if pattern is not None and not re.search(pattern, value):
            problems.append("%s: %r does not match %s"
                            % (path, _abbrev(value), pattern))
        maximum = schema.get("maxLength")
        if maximum is not None and len(value) > maximum:
            problems.append("%s: %d characters exceeds the limit of %d"
                            % (path, len(value), maximum))
        minimum = schema.get("minLength")
        if minimum is not None and len(value) < minimum:
            problems.append("%s: %d characters is below the minimum of %d"
                            % (path, len(value), minimum))

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        if minimum is not None and value < minimum:
            problems.append("%s: %r is below the minimum of %r"
                            % (path, value, minimum))
        maximum = schema.get("maximum")
        if maximum is not None and value > maximum:
            problems.append("%s: %r is above the maximum of %r"
                            % (path, value, maximum))

    if isinstance(value, list):
        minimum = schema.get("minItems")
        if minimum is not None and len(value) < minimum:
            problems.append("%s: %d items is below the minimum of %d"
                            % (path, len(value), minimum))
        maximum = schema.get("maxItems")
        if maximum is not None and len(value) > maximum:
            problems.append("%s: %d items exceeds the limit of %d"
                            % (path, len(value), maximum))
        if schema.get("uniqueItems"):
            seen: List[Any] = []
            for item in value:
                # Compared by equality rather than hashed: JSON arrays may hold
                # dicts and lists, which are unhashable, and silently skipping
                # those would make uniqueItems a constraint that holds only for
                # the easy cases.
                if item in seen:
                    problems.append("%s: %r appears more than once"
                                    % (path, _abbrev(item)))
                    break
                seen.append(item)

    if isinstance(value, Mapping) and "propertyNames" in schema:
        for name in sorted(value):
            collected: List[str] = []
            _check(name, schema["propertyNames"], root,
                   "%s (key %r)" % (path, name), collected)
            problems.extend(collected)

    if isinstance(value, Mapping):
        _check_object(value, schema, root, path, problems)

    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            _check(item, schema["items"], root, "%s[%d]" % (path, index), problems)


def _check_object(value: Mapping[str, Any], schema: Mapping[str, Any],
                  root: Mapping[str, Any], path: str,
                  problems: List[str]) -> None:
    properties = schema.get("properties") or {}
    minimum = schema.get("minProperties")
    if minimum is not None and len(value) < minimum:
        problems.append("%s: %d properties is below the minimum of %d"
                        % (path, len(value), minimum))
    for name in schema.get("required") or ():
        if name not in value:
            problems.append("%s: required property %r is missing" % (path, name))
    # ``additionalProperties`` is either False - no unlisted key is allowed -
    # or a schema every unlisted value must satisfy. The second form was
    # accepted and ignored before WP-10, which is the false assurance this
    # validator exists to prevent: a schema saying "every source version is a
    # non-empty string" checked nothing.
    additional = schema.get("additionalProperties")
    if additional is False:
        for name in sorted(set(value) - set(properties)):
            problems.append("%s: unexpected property %r" % (path, name))
    elif isinstance(additional, Mapping):
        for name in sorted(set(value) - set(properties)):
            _check(value[name], additional, root, "%s.%s" % (path, name),
                   problems)
    elif additional is not None and additional is not True:
        raise SchemaSupportError(
            "%s: additionalProperties must be a boolean or a schema, got %s"
            % (path, _type_name(additional)))
    for name, sub_schema in properties.items():
        if name in value:
            _check(value[name], sub_schema, root, "%s.%s" % (path, name),
                   problems)


def _type_name(value: Any) -> str:
    for name, check in _TYPE_CHECKS.items():
        if check(value):
            return name
    return type(value).__name__


def _abbrev(value: Any, limit: int = 60) -> Any:
    text = value if isinstance(value, str) else repr(value)
    return text if len(text) <= limit else text[:limit] + "..."
