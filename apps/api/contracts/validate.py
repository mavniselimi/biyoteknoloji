# -*- coding: utf-8 -*-
"""Enforcing the declared contract, with the standard library alone (WP-16).

Pydantic is the validator in a running deployment. This is the same contract
executed without it: it is what the OpenAPI builder, the adapters and the tests
check against, and in an environment with no Pydantic it is
what proves the contract is enforceable at all.

**The prohibited-field scan runs first, and it runs everywhere.** Before any
shape is checked, the whole document is walked to any depth looking for the
names in :data:`~apps.api.contracts.spec.PROHIBITED_REQUEST_FIELDS`. A
``genotype`` nested three objects down is refused exactly like one at the top,
and a request carrying one is refused whole rather than partly used.

**No rejected value is ever echoed.** An issue carries a normalised location
and a stable code, and nothing else. Echoing the value back is how a rejected
genotype ends up in a log, a browser history and a screenshot, having been
refused.

**Issue order is deterministic.** Sorted by location then code, so two runs of
one bad request produce the same response and a client can write an assertion
against it.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from apps.api.contracts.spec import (CONTROL_CHARACTER_RANGES, LIMITS, MODELS,
                                     PROHIBITED_REQUEST_FIELDS, FieldSpec,
                                     ModelSpec)

__all__ = [
    "ISSUE_CODES",
    "ContractViolation",
    "Issue",
    "contains_control_character",
    "find_prohibited_fields",
    "validate_document",
]

#: Every violation code this validator can report, with what it means. Stable:
#: a client may branch on these.
ISSUE_CODES: Mapping[str, str] = {
    "UNKNOWN_FIELD": "the document carries a field this contract does not "
                     "name",
    "PROHIBITED_FIELD": "the document carries a field this product refuses to "
                        "accept at any depth",
    "FIELD_REQUIRED": "a required field is absent",
    "NULL_NOT_ALLOWED": "a field that may not be null is null",
    "TYPE_INVALID": "a field is not of the declared type",
    "VALUE_TOO_LONG": "a string exceeds its declared maximum length",
    "VALUE_TOO_SHORT": "a string is shorter than its declared minimum length",
    "PATTERN_MISMATCH": "a string does not match its declared format",
    "ENUM_INVALID": "a value is not one of the governed values",
    "OUT_OF_RANGE": "an integer is outside its declared range",
    "TOO_MANY_ITEMS": "a collection exceeds its declared maximum size",
    "TOO_FEW_ITEMS": "a collection is smaller than its declared minimum size",
    "DUPLICATE_ITEM": "a collection declared unique carries a value twice",
    "CONTROL_CHARACTER": "a string carries a control character",
    "UUID_INVALID": "a value is not a canonical UUID",
    "DIGEST_INVALID": "a value is not a canonical sha256:<hex> digest",
    "UNKNOWN_MODEL": "the document was checked against a model that is not "
                     "declared",
}

_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
                   r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class Issue:
    """One contract violation: where, and which rule. Never the value."""

    location: str
    code: str

    def to_json(self) -> Dict[str, str]:
        return {"location": self.location, "code": self.code}


class ContractViolation(Exception):
    """The document does not satisfy its declared contract.

    Carries every issue found rather than the first, so a caller fixing a
    request does not have to discover its problems one round trip at a time.
    """

    def __init__(self, model_name: str, issues: Sequence[Issue]) -> None:
        super().__init__("%s: %d contract violation(s)"
                         % (model_name, len(issues)))
        self.model_name = model_name
        self.issues: Tuple[Issue, ...] = tuple(
            sorted(issues, key=lambda item: (item.location, item.code)))

    @property
    def codes(self) -> Tuple[str, ...]:
        seen: List[str] = []
        for issue in self.issues:
            if issue.code not in seen:
                seen.append(issue.code)
        return tuple(seen)

    def to_json(self) -> Dict[str, Any]:
        return {"issues": [issue.to_json()
                           for issue in self.issues[:LIMITS[
                               "max_detail_entries"]]]}


def contains_control_character(value: str) -> bool:
    """True when a string carries a character no API value may contain."""
    for character in value:
        point = ord(character)
        for low, high in CONTROL_CHARACTER_RANGES:
            if low <= point <= high:
                return True
    return False


def find_prohibited_fields(payload: Any, path: str = "$") -> Tuple[str, ...]:
    """Every prohibited field name present anywhere in a document.

    Returns locations, sorted, and never values. Walks mappings and sequences
    to any depth: a refusal that only looked at the top level would be
    satisfied by one extra layer of nesting.
    """
    found: List[str] = []
    if isinstance(payload, Mapping):
        for key in payload:
            here = "%s.%s" % (path, key)
            if isinstance(key, str) and \
                    key.strip().lower() in PROHIBITED_REQUEST_FIELDS:
                found.append(here)
            found.extend(find_prohibited_fields(payload[key], here))
    elif isinstance(payload, (list, tuple)):
        for index, item in enumerate(payload):
            found.extend(find_prohibited_fields(item, "%s[%d]" % (path,
                                                                 index)))
    return tuple(sorted(found))


def _check_string(value: Any, spec: FieldSpec, location: str,
                  issues: List[Issue], *, max_length: Optional[int] = None,
                  pattern: Optional[str] = None) -> None:
    if not isinstance(value, str):
        issues.append(Issue(location, "TYPE_INVALID"))
        return
    if contains_control_character(value):
        issues.append(Issue(location, "CONTROL_CHARACTER"))
        return
    limit = max_length if max_length is not None else spec.max_length
    if limit is not None and len(value) > limit:
        issues.append(Issue(location, "VALUE_TOO_LONG"))
    if spec.min_length is not None and len(value) < spec.min_length:
        issues.append(Issue(location, "VALUE_TOO_SHORT"))
    expression = pattern if pattern is not None else spec.pattern
    if expression is not None and not re.match(expression, value):
        issues.append(Issue(location, "PATTERN_MISMATCH"))


def _check_scalar(value: Any, kind: str, spec: FieldSpec, location: str,
                  issues: List[Issue], *, max_length: Optional[int] = None,
                  pattern: Optional[str] = None,
                  enum_values: Optional[Sequence[str]] = None) -> None:
    """Check one scalar, which may be a field's value or one array item.

    ``max_length``, ``pattern`` and ``enum_values`` are passed explicitly so
    that an array item is checked against the *item's* constraints rather than
    the array field's. Reading them off ``spec`` for items would silently skip
    every item check, because an array field's own ``enum_values`` and
    ``pattern`` are empty by construction.
    """
    if kind == "string":
        _check_string(value, spec, location, issues, max_length=max_length,
                      pattern=pattern)
    elif kind == "uuid":
        if not isinstance(value, str):
            issues.append(Issue(location, "TYPE_INVALID"))
        elif not _UUID.match(value):
            issues.append(Issue(location, "UUID_INVALID"))
    elif kind == "digest":
        if not isinstance(value, str):
            issues.append(Issue(location, "TYPE_INVALID"))
        elif not _DIGEST.match(value):
            issues.append(Issue(location, "DIGEST_INVALID"))
    elif kind == "enum":
        permitted = spec.enum_values if enum_values is None else enum_values
        if not isinstance(value, str):
            issues.append(Issue(location, "TYPE_INVALID"))
        elif permitted and value not in permitted:
            issues.append(Issue(location, "ENUM_INVALID"))
    elif kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            issues.append(Issue(location, "TYPE_INVALID"))
        else:
            if spec.minimum is not None and value < spec.minimum:
                issues.append(Issue(location, "OUT_OF_RANGE"))
            if spec.maximum is not None and value > spec.maximum:
                issues.append(Issue(location, "OUT_OF_RANGE"))
    elif kind == "boolean":
        if not isinstance(value, bool):
            issues.append(Issue(location, "TYPE_INVALID"))


def _check_field(value: Any, spec: FieldSpec, location: str,
                 issues: List[Issue]) -> None:
    if value is None:
        if not spec.nullable:
            issues.append(Issue(location, "NULL_NOT_ALLOWED"))
        return
    if spec.kind == "object":
        _check_model(value, MODELS[spec.model], location, issues)
        return
    if spec.kind == "array":
        if isinstance(value, (str, bytes)) or not isinstance(value,
                                                             (list, tuple)):
            issues.append(Issue(location, "TYPE_INVALID"))
            return
        if spec.max_items is not None and len(value) > spec.max_items:
            issues.append(Issue(location, "TOO_MANY_ITEMS"))
        if spec.min_items is not None and len(value) < spec.min_items:
            issues.append(Issue(location, "TOO_FEW_ITEMS"))
        if spec.unique_items:
            seen: List[Any] = []
            for item in value:
                key = item if isinstance(item, (str, int, bool)) else repr(
                    item)
                if key in seen:
                    issues.append(Issue(location, "DUPLICATE_ITEM"))
                    break
                seen.append(key)
        for index, item in enumerate(value):
            here = "%s[%d]" % (location, index)
            if spec.item_model:
                if item is None:
                    issues.append(Issue(here, "NULL_NOT_ALLOWED"))
                else:
                    _check_model(item, MODELS[spec.item_model], here, issues)
            else:
                if item is None:
                    issues.append(Issue(here, "NULL_NOT_ALLOWED"))
                else:
                    _check_scalar(item, spec.item_kind, spec, here, issues,
                                  max_length=spec.item_max_length,
                                  pattern=spec.item_pattern,
                                  enum_values=spec.item_enum_values)
        return
    _check_scalar(value, spec.kind, spec, location, issues)


def _check_model(payload: Any, spec: ModelSpec, location: str,
                 issues: List[Issue]) -> None:
    if not isinstance(payload, Mapping):
        issues.append(Issue(location, "TYPE_INVALID"))
        return
    declared = set(spec.field_names)
    for key in sorted(payload):
        if not isinstance(key, str):
            issues.append(Issue("%s.%s" % (location, key), "TYPE_INVALID"))
            continue
        if key not in declared:
            issues.append(Issue("%s.%s" % (location, key), "UNKNOWN_FIELD"))
    for item in spec.fields:
        here = "%s.%s" % (location, item.name)
        if item.name not in payload:
            if item.required:
                issues.append(Issue(here, "FIELD_REQUIRED"))
            continue
        _check_field(payload[item.name], item, here, issues)


def validate_document(model_name: str, payload: Any) -> Dict[str, Any]:
    """Check one document against its declared model, or refuse.

    Returns the payload unchanged on success. It is not coerced, normalised or
    defaulted here: turning ``"1"`` into ``1`` at the boundary is how a
    contract stops describing what a client actually sent.

    Raises:
        ContractViolation: a request document carries a prohibited field, or
            either direction carries an unnamed field, a missing required
            field, or a value outside its declared type, format, range or
            bound.
    """
    spec = MODELS.get(model_name)
    if spec is None:
        raise ContractViolation(model_name, [Issue("$", "UNKNOWN_MODEL")])

    # The prohibited scan runs on requests only, first and on its own: a
    # request carrying a genotype is refused as a whole, and its other fields
    # are never reported on, so nothing about it reads as partly acceptable.
    #
    # It must NOT run on responses, and the reason is worth stating because
    # the opposite is an easy and expensive mistake. The prohibited list says
    # what a *caller* may not supply - attention, coverage, findings,
    # evidence references, rule identities, hashes, release provenance -
    # because supplying any of them would let a client dictate an answer.
    # Those are precisely the fields a response exists to carry. Running the
    # scan over both directions would make every valid response a violation,
    # and the tempting repair - deleting entries from the prohibited list
    # until responses pass - would open the request side one field at a time.
    # The direction is what distinguishes them, so the direction is what
    # gates the scan.
    if spec.direction == "request":
        prohibited = find_prohibited_fields(payload)
        if prohibited:
            raise ContractViolation(
                model_name,
                [Issue(item, "PROHIBITED_FIELD")
                 for item in prohibited[:LIMITS["max_detail_entries"]]])

    issues: List[Issue] = []
    _check_model(payload, spec, "$", issues)
    if issues:
        raise ContractViolation(model_name, issues)
    return dict(payload)
