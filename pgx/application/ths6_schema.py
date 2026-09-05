# -*- coding: utf-8 -*-
"""Published JSON Schemas for WP-25.

Twenty schemas, and as in WP-21 through WP-24 the constraints that carry the
content are the negative ones. A schema describing only the happy shape would
accept an evidence item claiming to support a THS 6 claim while typed as a
unit test, a gate recorded PASS beside its own unmet conditions, a sign-off
row carrying a name, a pack manifest hashing itself, or a status document
asserting achievement with three of four conditions false.

What is pinned, and why each pin is here rather than in a comment somebody
could stop reading:

- **A test result may not present as a real one.** ``may_support_a_ths6_claim:
  true`` requires ``evidence_type`` to be ``REAL_EXECUTED`` or
  ``REAL_OBSERVED`` *and* ``test_only`` to be false. This is the single
  substitution the whole work package exists to prevent.
- **An absent artifact has no digest.** ``present: false`` requires
  ``sha256: null``. A digest beside an absent file is a value somebody
  invented.
- **A gate recorded PASS has nothing unmet.** ``result: "PASS"`` requires
  ``unmet_condition_ids`` and ``blockers`` to be empty and ``is_pass`` true.
- **A claim is SUPPORTED only with nothing missing.** ``support:
  "SUPPORTED"`` requires ``missing_evidence_ids`` empty.
- **An unsatisfied Definition of Done item names a blocker and an owner.**
- **A sign-off row cannot carry a name.** ``signatory`` must be ``null`` and
  ``signed`` must be ``false``, in the schema, so a hand-edited artifact
  claiming a signature fails validation rather than circulating.
- **A manifest may not hash itself.** ``manifest_self_hash`` must be null.
- **Achievement is a conjunction.** ``ths6_achieved: true`` requires all four
  achievement conditions true; ``release_may_proceed: true`` requires
  ``ths6_achieved`` true. A document asserting either alone is refused.
- **A blocked preflight executed nothing.** ``preflight_state: "BLOCKED"``
  requires ``demo_executed: false``.

Written against the supported subset that
``pgx.application.snapshot_schema.validate_against_schema`` implements: no
``patternProperties``, so keyed maps are described rather than pattern
matched.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

from pgx.application.snapshot_schema import validate_against_schema
from pgx.ths6.contingency import CONTINGENCY_MATRIX_VERSION
from pgx.ths6.claim_registry import CLAIM_REGISTRY_VERSION
from pgx.ths6.definition_of_done import DOD_REGISTRY_VERSION
from pgx.ths6.demo import DEMO_MANIFEST_VERSION
from pgx.ths6.evidence_registry import EVIDENCE_REGISTRY_VERSION
from pgx.ths6.gate_matrix import GATE_MATRIX_VERSION
from pgx.ths6.integrity import PACK_INTEGRITY_VERSION
from pgx.ths6.models import THS6_MODEL_VERSION
from pgx.ths6.signoff import SIGNOFF_MATRIX_VERSION
from pgx.ths6.status import THS6_STATUS_VERSION
from pgx.ths6.traceability import TRACEABILITY_VERSION
from pgx.ths6.vocabulary import (BLOCKER_CODES, ClaimSupport, EvidenceType,
                                 GateResult)

__all__ = [
    "SCHEMA_DIRECTORY",
    "build_schemas",
    "validate_claim_registry",
    "validate_contingency_matrix",
    "validate_definition_of_done",
    "validate_demo_manifest",
    "validate_demo_preflight",
    "validate_evidence_item",
    "validate_evidence_registry",
    "validate_gate_matrix",
    "validate_pack_integrity_result",
    "validate_pack_manifest",
    "validate_signoff_matrix",
    "validate_ths6_status",
    "validate_traceability_matrix",
]

SCHEMA_DIRECTORY = "schemas/wp25"

_EVIDENCE_TYPES = [item.value for item in EvidenceType]
_CLAIM_SUPPORT = [item.value for item in ClaimSupport]
_GATE_RESULTS = [item.value for item in GateResult]
_BLOCKER_CODES = sorted(BLOCKER_CODES)

_SHA = {"type": ["string", "null"], "pattern": "^sha256:[0-9a-f]{64}$"}
_EMPTY_ARRAY = {"type": "array", "maxItems": 0}
_STRING_ARRAY = {"type": "array", "items": {"type": "string"}}


def _blocker() -> Dict[str, Any]:
    return {
        "type": "object",
        "required": ["code", "detail", "owner", "blocking"],
        "properties": {
            "code": {"type": "string", "enum": _BLOCKER_CODES},
            "detail": {"type": "string", "minLength": 1},
            "owner": {"type": "string", "minLength": 1},
            "gate_id": {"type": ["string", "null"],
                        "pattern": "^GATE-[A-F]$"},
            "blocking": {"type": "boolean", "const": True},
        },
    }


def _finding() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "WP-25 finding",
        "description": (
            "A discrepancy WP-25 noticed: a document, count or artifact that "
            "is wrong. Distinct from a blocker, which says a condition is "
            "unmet. Every finding names an owner and what WP-25 did in the "
            "meantime; 'ignored' is not a resolution."),
        "type": "object",
        "required": ["code", "detail", "owner", "resolution", "blocking"],
        "properties": {
            "code": {"type": "string", "enum": _BLOCKER_CODES},
            "detail": {"type": "string", "minLength": 1},
            "owner": {"type": "string", "minLength": 1},
            "resolution": {"type": "string", "minLength": 1},
            "blocking": {"type": "boolean"},
            "references": _STRING_ARRAY,
        },
    }


def _evidence_item() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "WP-25 evidence item",
        "description": (
            "One artifact in the pack. The constraints that matter are the "
            "refusals: an item may not claim to support a THS 6 claim while "
            "typed as a test or marked test-only, an absent item may not "
            "carry a digest, and a path may not be absolute."),
        "type": "object",
        "required": ["evidence_id", "title", "work_package", "evidence_type",
                     "path", "present", "sha256", "test_only",
                     "observed_or_executed", "may_support_a_ths6_claim",
                     "contains_numeric_claim", "supported_claim_ids",
                     "gate_ids", "limitations"],
        "properties": {
            "evidence_id": {"type": "string",
                            "pattern": "^EV-WP[0-2][0-9]-[0-9]{3}$"},
            "title": {"type": "string", "minLength": 1},
            "work_package": {"type": "string", "pattern": "^WP-[0-9]{2}$"},
            "evidence_type": {"type": "string", "enum": _EVIDENCE_TYPES},
            # Repository-relative: no leading slash, tilde, backslash or
            # drive letter. A pack recording an absolute path describes the
            # machine it was built on and discloses whoever built it.
            "path": {"type": "string",
                     "pattern": "^(?![/~\\\\])(?![A-Za-z]:)[^\\s].*$"},
            "present": {"type": "boolean"},
            "sha256": _SHA,
            "media_type": {"type": ["string", "null"]},
            "schema_path": {"type": ["string", "null"]},
            "generator": {"type": "string"},
            "observed_or_executed": {"type": "boolean"},
            "test_only": {"type": "boolean"},
            "contains_numeric_claim": {"type": "boolean"},
            "may_support_a_ths6_claim": {"type": "boolean"},
            "supported_claim_ids": {
                "type": "array",
                "items": {"type": "string",
                          "pattern": "^THS6-CLAIM-[0-9]{3}$"}},
            "gate_ids": {"type": "array",
                         "items": {"type": "string",
                                   "pattern": "^GATE-[A-F]$"}},
            "freshness_source": {"type": ["string", "null"]},
            "validation_result": {"type": ["string", "null"]},
            "limitations": _STRING_ARRAY,
            "gap_owner": {"type": ["string", "null"]},
        },
        "allOf": [
            {"if": {"required": ["may_support_a_ths6_claim"],
                    "properties": {
                        "may_support_a_ths6_claim": {"const": True}}},
             "then": {"properties": {
                 "evidence_type": {"enum": ["REAL_EXECUTED",
                                            "REAL_OBSERVED"]},
                 "test_only": {"const": False}}}},
            {"if": {"required": ["observed_or_executed"],
                    "properties": {"observed_or_executed": {"const": True}}},
             "then": {"properties": {
                 "evidence_type": {"enum": ["REAL_EXECUTED",
                                            "REAL_OBSERVED"]},
                 "present": {"const": True}}}},
            {"if": {"required": ["present"],
                    "properties": {"present": {"const": False}}},
             "then": {"properties": {"sha256": {"type": "null"},
                                     "observed_or_executed":
                                         {"const": False}}}},
            {"if": {"required": ["test_only"],
                    "properties": {"test_only": {"const": True}}},
             "then": {"properties": {
                 "may_support_a_ths6_claim": {"const": False}}}},
        ],
    }


def _evidence_registry() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "WP-25 evidence registry",
        "description": (
            "The whole inventory. Counts are required alongside the items so "
            "a reader can check the document against itself."),
        "type": "object",
        "required": ["evidence_registry_version", "declared_count",
                     "present_count", "absent_count", "invalid_count",
                     "admissible_count", "counts_by_type", "items",
                     "findings", "preliminary_ths6_documents"],
        "properties": {
            "evidence_registry_version": {
                "type": "string", "const": EVIDENCE_REGISTRY_VERSION},
            "declared_count": {"type": "integer", "minimum": 1},
            "resolved_count": {"type": "integer", "minimum": 0},
            "present_count": {"type": "integer", "minimum": 0},
            "absent_count": {"type": "integer", "minimum": 0},
            "invalid_count": {"type": "integer", "minimum": 0},
            "admissible_count": {"type": "integer", "minimum": 0},
            "admissible_evidence_ids": _STRING_ARRAY,
            "counts_by_type": {"type": "object",
                               "additionalProperties": {"type": "integer",
                                                        "minimum": 0}},
            "preliminary_ths6_documents": {
                "type": "array", "items": {"type": "string"}, "minItems": 3},
            "final_pack_document_prefix": {"type": "string"},
            "items": {"type": "array", "items": _evidence_item(),
                      "minItems": 1},
            "findings": {"type": "array", "items": _finding()},
            "note": {"type": "string"},
        },
    }


def _claim() -> Dict[str, Any]:
    return {
        "type": "object",
        "required": ["claim_id", "statement", "origin",
                     "required_evidence_ids", "support", "sufficient",
                     "missing_evidence_ids"],
        "properties": {
            "claim_id": {"type": "string",
                         "pattern": "^THS6-CLAIM-[0-9]{3}$"},
            "statement": {"type": "string", "minLength": 1},
            "origin": {"type": "string", "minLength": 1},
            "required_evidence_ids": {
                "type": "array", "minItems": 1,
                "items": {"type": "string",
                          "pattern": "^EV-WP[0-2][0-9]-[0-9]{3}$"}},
            "gate_id": {"type": ["string", "null"],
                        "pattern": "^GATE-[A-F]$"},
            "dod_ids": {"type": "array",
                        "items": {"type": "string",
                                  "pattern": "^P0-DOD-0(0[1-9]|1[0-5])$"}},
            "outward_facing": {"type": "boolean"},
            "support": {"type": "string", "enum": _CLAIM_SUPPORT},
            "sufficient": {"type": "boolean"},
            "missing_evidence_ids": _STRING_ARRAY,
            "notes": {"type": "string"},
        },
        "allOf": [
            {"if": {"required": ["support"],
                    "properties": {"support": {"const": "SUPPORTED"}}},
             "then": {"properties": {"missing_evidence_ids": _EMPTY_ARRAY,
                                     "sufficient": {"const": True}}}},
            {"if": {"required": ["sufficient"],
                    "properties": {"sufficient": {"const": True}}},
             "then": {"properties": {"support": {"const": "SUPPORTED"}}}},
        ],
    }


def _claim_registry() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "WP-25 claim registry",
        "description": (
            "Every claim and its support. There is deliberately no "
            "'all_supported' field: a conjunction may only be drawn by a "
            "gate."),
        "type": "object",
        "required": ["claim_registry_version", "claim_count",
                     "counts_by_support", "supported_claim_ids",
                     "contradicted_claim_ids", "claims", "probe_count",
                     "unresolvable_probes"],
        "properties": {
            "claim_registry_version": {"type": "string",
                                       "const": CLAIM_REGISTRY_VERSION},
            "claim_count": {"type": "integer", "minimum": 1},
            "counts_by_support": {
                "type": "object",
                "propertyNames": {"enum": _CLAIM_SUPPORT},
                "additionalProperties": {"type": "integer", "minimum": 0}},
            "supported_claim_ids": _STRING_ARRAY,
            "contradicted_claim_ids": _STRING_ARRAY,
            "outward_facing_claim_ids": _STRING_ARRAY,
            "claims": {"type": "array", "items": _claim(), "minItems": 1},
            "probes": {"type": "object", "additionalProperties": {
                "type": "array", "items": {
                    "type": "object",
                    "required": ["source_path", "field", "explanation"],
                    "properties": {
                        "source_path": {"type": "string"},
                        "field": {"type": "string"},
                        "refuting_value": {},
                        "explanation": {"type": "string", "minLength": 1}}}}},
            "probe_count": {"type": "integer", "minimum": 0},
            # A probe that cannot resolve is worse than no probe: it looks
            # like diligence and can never fire.
            "unresolvable_probes": {"type": "array", "maxItems": 0},
            "note": {"type": "string"},
        },
    }


def _traceability_row() -> Dict[str, Any]:
    return {
        "type": "object",
        "required": ["row_id", "requirement", "requirement_source",
                     "implementation_paths", "test_paths", "evidence_ids",
                     "claim_ids", "gate_ids", "dod_ids", "result"],
        "properties": {
            "row_id": {"type": "string", "minLength": 1},
            "requirement": {"type": "string", "minLength": 1},
            "requirement_source": {"type": "string", "minLength": 1},
            "implementation_paths": _STRING_ARRAY,
            "test_paths": _STRING_ARRAY,
            "evidence_ids": _STRING_ARRAY,
            "claim_ids": _STRING_ARRAY,
            "gate_ids": _STRING_ARRAY,
            "dod_ids": _STRING_ARRAY,
            "result": {"type": "string", "enum": _CLAIM_SUPPORT},
            "gap": {"type": "string"},
            "gap_owner": {"type": ["string", "null"]},
        },
        # A row short of SUPPORTED must say what is missing and who owns it.
        # A gap with no owner is a gap nobody clears.
        "allOf": [
            {"if": {"required": ["result"],
                    "properties": {"result": {"enum": [
                        "PARTIALLY_SUPPORTED", "UNSUPPORTED",
                        "NOT_EVALUATED", "CONTRADICTED"]}}},
             "then": {"required": ["gap", "gap_owner"],
                      "properties": {"gap": {"type": "string",
                                             "minLength": 1},
                                     "gap_owner": {"type": "string",
                                                   "minLength": 1}}}},
        ],
    }


def _traceability_matrix() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "WP-25 traceability matrix",
        "description": (
            "Requirement to result. Every dangling list must be empty: a "
            "matrix citing a deleted module asserts coverage it does not "
            "have, which is worse than no matrix."),
        "type": "object",
        "required": ["traceability_version", "row_count", "rows", "dangling",
                     "has_dangling_reference", "p0_dod_014_satisfied"],
        "properties": {
            "traceability_version": {"type": "string",
                                     "const": TRACEABILITY_VERSION},
            "row_count": {"type": "integer", "minimum": 1},
            "counts_by_result": {
                "type": "object",
                "propertyNames": {"enum": _CLAIM_SUPPORT},
                "additionalProperties": {"type": "integer", "minimum": 0}},
            "dangling": {"type": "object",
                         "additionalProperties": _STRING_ARRAY},
            "has_dangling_reference": {"type": "boolean"},
            "every_claim_names_required_evidence": {"type": "boolean"},
            "p0_dod_014_satisfied": {"type": "boolean"},
            "p0_dod_014_basis": {"type": "string", "minLength": 1},
            "rows": {"type": "array", "items": _traceability_row(),
                     "minItems": 1},
            "gap_owners": _STRING_ARRAY,
            "note": {"type": "string"},
        },
        "allOf": [
            {"if": {"required": ["p0_dod_014_satisfied"],
                    "properties": {"p0_dod_014_satisfied": {"const": True}}},
             "then": {"properties": {
                 "has_dangling_reference": {"const": False},
                 "every_claim_names_required_evidence": {"const": True}}}},
        ],
    }


def _gate_condition() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "WP-25 gate condition",
        "description": (
            "One mandatory condition, with the artifact and field it was "
            "read from. ``met`` is nullable because 'not evaluated' is a "
            "third state and collapsing it into false would make an "
            "unevaluable gate look merely blocked."),
        "type": "object",
        "required": ["condition_id", "description", "source_path",
                     "source_field", "expected", "observed", "met"],
        "properties": {
            "condition_id": {"type": "string", "minLength": 1},
            "description": {"type": "string", "minLength": 1},
            "source_path": {"type": "string",
                            "pattern": "^(?![/~\\\\])(?![A-Za-z]:)[^\\s].*$"},
            "source_field": {"type": "string", "minLength": 1},
            "expected": {"type": "string"},
            "observed": {"type": "string"},
            "met": {"type": ["boolean", "null"]},
            "blocker": {"anyOf": [_blocker(), {"type": "null"}]},
        },
        "allOf": [
            {"if": {"required": ["met"], "properties": {"met": {
                "const": False}}},
             "then": {"required": ["blocker"],
                      "properties": {"blocker": _blocker()}}},
            {"if": {"required": ["met"], "properties": {"met": {
                "const": True}}},
             "then": {"properties": {"blocker": {"type": "null"}}}},
        ],
    }


def _gate_record() -> Dict[str, Any]:
    return {
        "type": "object",
        "required": ["gate_id", "title", "result", "is_pass",
                     "condition_count", "met_condition_count",
                     "unmet_condition_ids", "conditions", "blockers"],
        "properties": {
            "gate_id": {"type": "string", "pattern": "^GATE-[A-F]$"},
            "title": {"type": "string", "minLength": 1},
            "result": {"type": "string", "enum": _GATE_RESULTS},
            "is_pass": {"type": "boolean"},
            "condition_count": {"type": "integer", "minimum": 1},
            "met_condition_count": {"type": "integer", "minimum": 0},
            "unmet_condition_ids": _STRING_ARRAY,
            "conditions": {"type": "array", "items": _gate_condition(),
                           "minItems": 1},
            "blockers": {"type": "array", "items": _blocker()},
            "depends_on": _STRING_ARRAY,
            "findings": {"type": "array", "items": _finding()},
            "notes": {"type": "string"},
        },
        "allOf": [
            {"if": {"required": ["result"],
                    "properties": {"result": {"const": "PASS"}}},
             "then": {"properties": {"unmet_condition_ids": _EMPTY_ARRAY,
                                     "blockers": _EMPTY_ARRAY,
                                     "is_pass": {"const": True}}}},
            {"if": {"required": ["is_pass"],
                    "properties": {"is_pass": {"const": True}}},
             "then": {"properties": {"result": {"const": "PASS"}}}},
        ],
    }


def _gate_matrix() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "WP-25 gate matrix",
        "description": (
            "Gates A to F. ``all_gates_pass`` requires every gate PASS and "
            "``override_available`` must be false: there is no force flag, "
            "and a document claiming one describes different software."),
        "type": "object",
        "required": ["gate_matrix_version", "gate_count", "results",
                     "passing_gate_ids", "gates", "all_gates_pass",
                     "override_available", "source_artifact_disagreements"],
        "properties": {
            "gate_matrix_version": {"type": "string",
                                    "const": GATE_MATRIX_VERSION},
            "gate_count": {"type": "integer", "minimum": 6},
            "results": {"type": "object",
                        "propertyNames": {"pattern": "^GATE-[A-F]$"},
                        "additionalProperties": {"type": "string",
                                                 "enum": _GATE_RESULTS}},
            "passing_gate_ids": _STRING_ARRAY,
            "passing_gate_count": {"type": "integer", "minimum": 0},
            "blocking_gate_ids": _STRING_ARRAY,
            "failing_gate_ids": _STRING_ARRAY,
            "all_gates_pass": {"type": "boolean"},
            "gates": {"type": "array", "items": _gate_record(),
                      "minItems": 6},
            "total_blocker_count": {"type": "integer", "minimum": 0},
            "blocker_owners": _STRING_ARRAY,
            "source_artifact_disagreements": {
                "type": "array",
                "items": {"type": "object",
                          "required": ["fact", "left_path", "right_path",
                                       "explanation", "owner"],
                          "properties": {
                              "fact": {"type": "string", "minLength": 1},
                              "left_path": {"type": "string"},
                              "left_field": {"type": "string"},
                              "left_value": {},
                              "right_path": {"type": "string"},
                              "right_field": {"type": "string"},
                              "right_value": {},
                              "explanation": {"type": "string",
                                              "minLength": 1},
                              "owner": {"type": "string", "minLength": 1},
                              "resolution": {"type": "string"}}}},
            "disagreement_count": {"type": "integer", "minimum": 0},
            "override_available": {"type": "boolean", "const": False},
            "note": {"type": "string"},
        },
        "allOf": [
            {"if": {"required": ["all_gates_pass"],
                    "properties": {"all_gates_pass": {"const": True}}},
             "then": {"properties": {"blocking_gate_ids": _EMPTY_ARRAY,
                                     "failing_gate_ids": _EMPTY_ARRAY,
                                     "total_blocker_count": {"maximum": 0}}}},
        ],
    }


def _dod_item() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "WP-25 Definition of Done item",
        "description": (
            "One P0 bullet, carrying the architecture text verbatim so the "
            "transcription can be checked, and an observable condition so "
            "the bullet can be evaluated rather than argued about."),
        "type": "object",
        "required": ["dod_id", "architecture_text", "observable_condition",
                     "satisfied", "blockers"],
        "properties": {
            "dod_id": {"type": "string",
                       "pattern": "^P0-DOD-0(0[1-9]|1[0-5])$"},
            "architecture_text": {"type": "string", "minLength": 1},
            "observable_condition": {"type": "string", "minLength": 1},
            "satisfied": {"type": ["boolean", "null"]},
            "evidence_ids": _STRING_ARRAY,
            "gate_ids": _STRING_ARRAY,
            "blockers": {"type": "array", "items": _blocker()},
            "owner": {"type": ["string", "null"]},
            "notes": {"type": "string"},
        },
        "allOf": [
            {"if": {"required": ["satisfied"],
                    "properties": {"satisfied": {"const": False}}},
             "then": {"required": ["owner"],
                      "properties": {"owner": {"type": "string",
                                               "minLength": 1},
                                     "blockers": {"minItems": 1}}}},
        ],
    }


def _dod_registry() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "WP-25 Definition of Done registry",
        "description": (
            "All fifteen bullets. ``enumerated_count`` must be 15 and the "
            "declared count in the work package prose is recorded beside it "
            "so the discrepancy is data rather than prose."),
        "type": "object",
        "required": ["definition_of_done_version", "architecture_section",
                     "enumerated_count", "declared_count_in_wp25_prose",
                     "count_matches_declaration", "items", "findings",
                     "all_items_satisfied"],
        "properties": {
            "definition_of_done_version": {"type": "string",
                                           "const": DOD_REGISTRY_VERSION},
            "architecture_section": {"type": "string", "minLength": 1},
            "enumerated_count": {"type": "integer", "const": 15},
            "declared_count_in_wp25_prose": {"type": "integer"},
            "count_matches_declaration": {"type": "boolean"},
            "satisfied_count": {"type": "integer", "minimum": 0},
            "unsatisfied_count": {"type": "integer", "minimum": 0},
            "unevaluated_count": {"type": "integer", "minimum": 0},
            "satisfied_dod_ids": _STRING_ARRAY,
            "unsatisfied_dod_ids": _STRING_ARRAY,
            "unevaluated_dod_ids": _STRING_ARRAY,
            "all_items_satisfied": {"type": "boolean"},
            "items": {"type": "array", "items": _dod_item(),
                      "minItems": 15, "maxItems": 15},
            "findings": {"type": "array", "items": _finding(),
                         "minItems": 1},
            "note": {"type": "string"},
        },
        "allOf": [
            {"if": {"required": ["all_items_satisfied"],
                    "properties": {"all_items_satisfied": {"const": True}}},
             "then": {"properties": {"unsatisfied_dod_ids": _EMPTY_ARRAY,
                                     "unevaluated_dod_ids": _EMPTY_ARRAY}}},
        ],
    }


def _demo_manifest() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "WP-25 demonstration manifest",
        "description": (
            "The representative workflow as declared. Environment "
            "requirements are declared here and measured in the preflight; "
            "keeping the observation out is what lets this document be "
            "compared byte for byte between machines."),
        "type": "object",
        "required": ["demo_manifest_version", "step_count", "steps",
                     "environment_requirements", "force_available"],
        "properties": {
            "demo_manifest_version": {"type": "string",
                                      "const": DEMO_MANIFEST_VERSION},
            "step_count": {"type": "integer", "minimum": 1},
            "steps": {
                "type": "array", "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["step_id", "title", "observable_outcome",
                                 "preconditions"],
                    "properties": {
                        "step_id": {"type": "string",
                                    "pattern": "^DEMO-[0-9]{2}$"},
                        "title": {"type": "string", "minLength": 1},
                        "observable_outcome": {"type": "string",
                                               "minLength": 1},
                        "precondition_count": {"type": "integer",
                                               "minimum": 1},
                        "preconditions": {
                            "type": "array", "minItems": 1,
                            "items": {
                                "type": "object",
                                "required": ["description", "source_path",
                                             "source_field", "blocker_code",
                                             "owner"],
                                "properties": {
                                    "description": {"type": "string",
                                                    "minLength": 1},
                                    "source_path": {"type": "string"},
                                    "source_field": {"type": "string"},
                                    "required": {},
                                    "blocker_code": {"type": "string",
                                                     "enum": _BLOCKER_CODES},
                                    "owner": {"type": "string",
                                              "minLength": 1}}}}}}},
            "environment_requirements": {
                "type": "array", "minItems": 3,
                "items": {"type": "object",
                          "required": ["condition_id", "description",
                                       "source", "note"],
                          "properties": {
                              "condition_id": {"type": "string"},
                              "description": {"type": "string",
                                              "minLength": 1},
                              "source": {"type": "string"},
                              "required": {},
                              "note": {"type": "string", "minLength": 1}}}},
            "force_available": {"type": "boolean", "const": False},
            "note": {"type": "string"},
        },
    }


def _demo_preflight() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "WP-25 demonstration preflight",
        "description": (
            "The preflight result. A BLOCKED preflight must record "
            "``demo_executed: false``: the whole point is that nothing was "
            "run past the first unmet precondition."),
        "type": "object",
        "required": ["demo_manifest_version", "preflight_state",
                     "demo_executed", "stopped_at_step_id", "steps",
                     "blockers", "exit_code", "force_available",
                     "environment_conditions"],
        "properties": {
            "demo_manifest_version": {"type": "string",
                                      "const": DEMO_MANIFEST_VERSION},
            "step_count": {"type": "integer", "minimum": 1},
            "preflight_state": {"type": "string",
                                "enum": ["READY", "BLOCKED"]},
            "demo_executed": {"type": "boolean"},
            "demo_execution_note": {"type": "string"},
            "stopped_at_step_id": {"type": ["string", "null"]},
            "steps_with_preconditions_met": {"type": "integer",
                                             "minimum": 0},
            "steps_not_attempted": {"type": "integer", "minimum": 0},
            "environment_conditions": {"type": "array", "minItems": 3,
                                       "items": {"type": "object"}},
            "unmet_environment_condition_ids": _STRING_ARRAY,
            "steps": {"type": "array", "minItems": 1,
                      "items": {"type": "object",
                                "required": ["step_id", "state", "reason"],
                                "properties": {
                                    "step_id": {"type": "string"},
                                    "title": {"type": "string"},
                                    "state": {"type": "string", "enum": [
                                        "PRECONDITIONS_MET", "BLOCKED",
                                        "NOT_ATTEMPTED"]},
                                    "reason": {"type": "string",
                                               "minLength": 1},
                                    "preconditions": {"type": "array"}}}},
            "blockers": {"type": "array", "items": _blocker()},
            "blocker_count": {"type": "integer", "minimum": 0},
            "exit_code": {"type": "integer", "enum": [0, 2]},
            "force_available": {"type": "boolean", "const": False},
            "note": {"type": "string"},
        },
        "allOf": [
            {"if": {"required": ["preflight_state"],
                    "properties": {"preflight_state": {"const": "BLOCKED"}}},
             "then": {"properties": {"demo_executed": {"const": False},
                                     "exit_code": {"const": 2}}}},
            {"if": {"required": ["demo_executed"],
                    "properties": {"demo_executed": {"const": True}}},
             "then": {"properties": {
                 "preflight_state": {"const": "READY"},
                 "stopped_at_step_id": {"type": "null"}}}},
        ],
    }


def _contingency_scenario() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "WP-25 contingency scenario",
        "description": (
            "One failure and its response. ``does_not_prove`` is required "
            "and non-empty: a contingency matrix without it reads as "
            "resilience and is silent about correctness."),
        "type": "object",
        "required": ["scenario_id", "title", "detection", "response",
                     "proves", "does_not_prove", "continuation_permitted",
                     "owner"],
        "properties": {
            "scenario_id": {"type": "string", "pattern": "^CONT-[0-9]{2}$"},
            "title": {"type": "string", "minLength": 1},
            "detection": {"type": "string", "minLength": 1},
            "response": {"type": "string", "minLength": 1},
            "proves": {"type": "string", "minLength": 1},
            "does_not_prove": {"type": "string", "minLength": 1},
            "continuation_permitted": {"type": "boolean"},
            "owner": {"type": "string", "minLength": 1},
        },
    }


def _contingency_matrix() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "WP-25 contingency matrix",
        "description": (
            "Fourteen scenarios. ``substitution_permitted`` must be false: "
            "no row may substitute a fixture for governed content, a cached "
            "number for a computed one, or a rehearsal for a deployment."),
        "type": "object",
        "required": ["contingency_matrix_version", "scenario_count",
                     "scenarios", "substitution_permitted"],
        "properties": {
            "contingency_matrix_version": {
                "type": "string", "const": CONTINGENCY_MATRIX_VERSION},
            "scenario_count": {"type": "integer", "minimum": 14},
            "continuation_permitted_ids": _STRING_ARRAY,
            "continuation_refused_ids": _STRING_ARRAY,
            "scenarios": {"type": "array", "minItems": 14,
                          "items": _contingency_scenario()},
            "substitution_permitted": {"type": "boolean", "const": False},
            "note": {"type": "string"},
        },
    }


def _signoff_matrix() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "WP-25 sign-off matrix",
        "description": (
            "Nine roles, none signed. ``signatory`` must be null and "
            "``signed`` false in the schema itself, so a hand-edited "
            "artifact claiming a signature fails validation rather than "
            "circulating. ``signature_mechanism`` must be null because this "
            "repository contains no way to record one."),
        "type": "object",
        "required": ["signoff_matrix_version", "role_count", "signed_count",
                     "roles", "signature_mechanism", "example_names_used"],
        "properties": {
            "signoff_matrix_version": {"type": "string",
                                       "const": SIGNOFF_MATRIX_VERSION},
            "role_count": {"type": "integer", "const": 9},
            "signed_count": {"type": "integer", "const": 0},
            "unsigned_role_ids": {"type": "array", "minItems": 9},
            "roles": {
                "type": "array", "minItems": 9, "maxItems": 9,
                "items": {
                    "type": "object",
                    "required": ["role_id", "role", "attests_to",
                                 "must_have_reviewed", "signatory",
                                 "signed"],
                    "properties": {
                        "role_id": {"type": "string",
                                    "pattern": "^SIGN-0[1-9]$"},
                        "role": {"type": "string", "minLength": 1},
                        "attests_to": {"type": "string", "minLength": 1},
                        "must_have_reviewed": {"type": "array", "minItems": 1,
                                               "items": {"type": "string"}},
                        "gate_ids": _STRING_ARRAY,
                        "signatory": {"type": "null"},
                        "signed": {"type": "boolean", "const": False},
                        "signature_recorded_at": {"type": "null"}}}},
            "signature_mechanism": {"type": "null"},
            "signature_mechanism_note": {"type": "string", "minLength": 1},
            "example_names_used": {"type": "boolean", "const": False},
            "note": {"type": "string"},
        },
    }


def _pack_manifest() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "WP-25 evidence pack manifest",
        "description": (
            "Two levels of hash. ``manifest_self_hash`` must be null: a "
            "manifest containing a digest of itself could never satisfy its "
            "own check, because writing the digest changes the bytes."),
        "type": "object",
        "required": ["pack_integrity_version", "manifest_member_path",
                     "manifest_excludes_itself", "manifest_self_hash",
                     "members", "pack_sha256", "member_count",
                     "integrity_note"],
        "properties": {
            "pack_integrity_version": {"type": "string",
                                       "const": PACK_INTEGRITY_VERSION},
            "pack_version": {"type": "string", "minLength": 1},
            "manifest_member_path": {"type": "string", "minLength": 1},
            "manifest_excludes_itself": {"type": "boolean", "const": True},
            "manifest_self_hash": {"type": "null"},
            "manifest_self_hash_note": {"type": "string", "minLength": 1},
            "member_count": {"type": "integer", "minimum": 1},
            "present_member_count": {"type": "integer", "minimum": 0},
            "absent_member_paths": _STRING_ARRAY,
            "refused_member_paths": _STRING_ARRAY,
            "members": {
                "type": "array", "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["path", "present", "sha256", "state"],
                    "properties": {
                        "path": {"type": "string", "pattern":
                                 "^(?![/~\\\\])(?![A-Za-z]:)[^\\s].*$"},
                        "present": {"type": "boolean"},
                        "sha256": _SHA,
                        "bytes": {"type": ["integer", "null"], "minimum": 0},
                        "state": {"type": "string",
                                  "enum": ["PRESENT", "ABSENT",
                                           "SYMLINK_REFUSED"]}},
                    "allOf": [
                        {"if": {"required": ["state"],
                                "properties": {"state": {"const": "ABSENT"}}},
                         "then": {"properties": {"sha256": {"type": "null"},
                                                 "bytes": {"type": "null"},
                                                 "present": {
                                                     "const": False}}}}]}},
            "pack_sha256": {"type": "string",
                            "pattern": "^sha256:[0-9a-f]{64}$"},
            "integrity_note": {"type": "string", "minLength": 1},
        },
    }


def _pack_integrity_result() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "WP-25 pack integrity result",
        "description": (
            "The verification result. ``intact`` describes bytes and says "
            "nothing about whether any gate passed."),
        "type": "object",
        "required": ["pack_integrity_version", "declared_pack_sha256",
                     "recomputed_pack_sha256", "pack_digest_matches",
                     "changed_members", "absent_member_paths", "intact",
                     "integrity_note"],
        "properties": {
            "pack_integrity_version": {"type": "string",
                                       "const": PACK_INTEGRITY_VERSION},
            "declared_pack_sha256": {"type": ["string", "null"]},
            "recomputed_pack_sha256": {"type": "string"},
            "pack_digest_matches": {"type": "boolean"},
            "changed_member_count": {"type": "integer", "minimum": 0},
            "changed_members": {"type": "array"},
            "absent_member_paths": _STRING_ARRAY,
            "member_count": {"type": "integer", "minimum": 0},
            "intact": {"type": "boolean"},
            "integrity_note": {"type": "string", "minLength": 1},
            "achievement_note": {"type": "string", "minLength": 1},
        },
        "allOf": [
            {"if": {"required": ["intact"],
                    "properties": {"intact": {"const": True}}},
             "then": {"properties": {"changed_members": _EMPTY_ARRAY,
                                     "absent_member_paths": _EMPTY_ARRAY,
                                     "pack_digest_matches": {
                                         "const": True}}}},
        ],
    }


def _ths6_status() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "WP-25 THS 6 status",
        "description": (
            "Pack integrity and THS 6 achievement, as separate fields. "
            "``ths6_achieved: true`` requires all four achievement "
            "conditions true; ``release_may_proceed: true`` requires "
            "``ths6_achieved`` true. Neither may be derived from pack "
            "integrity."),
        "type": "object",
        "required": ["ths6_status_version", "work_package",
                     "implementation_status", "evidence_pack_integrity",
                     "ths6_achieved", "release_may_proceed",
                     "ths6_achievement_conditions", "unmet_conditions",
                     "gate_results", "override_available",
                     "not_clinical_validation"],
        "properties": {
            "ths6_status_version": {"type": "string",
                                    "const": THS6_STATUS_VERSION},
            "work_package": {"type": "string", "const": "WP-25"},
            "implementation_status": {"type": "string",
                                      "enum": ["IMPLEMENTED", "PARTIAL"]},
            "implementation_note": {"type": "string", "minLength": 1},
            "evidence_pack_integrity": {"type": ["boolean", "null"]},
            "evidence_pack_integrity_note": {"type": "string",
                                             "minLength": 1},
            "ths6_achieved": {"type": "boolean"},
            "release_may_proceed": {"type": "boolean"},
            "ths6_achievement_conditions": {
                "type": "object",
                "required": ["all_gates_pass",
                             "all_definition_of_done_items_satisfied",
                             "representative_demonstration_executed",
                             "all_signoff_roles_signed"],
                "additionalProperties": {"type": "boolean"}},
            "release_condition_release_validation_permits": {
                "type": "boolean"},
            "unmet_conditions": _STRING_ARRAY,
            "gate_results": {"type": "object",
                             "propertyNames": {"pattern": "^GATE-[A-F]$"},
                             "additionalProperties": {"type": "string",
                                                      "enum":
                                                          _GATE_RESULTS}},
            "passing_gate_count": {"type": "integer", "minimum": 0},
            "gate_count": {"type": "integer", "minimum": 6},
            "total_gate_blocker_count": {"type": "integer", "minimum": 0},
            "source_artifact_disagreement_count": {"type": "integer",
                                                   "minimum": 0},
            "definition_of_done_enumerated_count": {"type": "integer",
                                                    "const": 15},
            "definition_of_done_declared_count_in_prose": {
                "type": "integer"},
            "definition_of_done_satisfied_count": {"type": "integer",
                                                   "minimum": 0},
            "claim_count": {"type": "integer", "minimum": 1},
            "supported_claim_count": {"type": "integer", "minimum": 0},
            "contradicted_claim_count": {"type": "integer", "minimum": 0},
            "evidence_item_count": {"type": "integer", "minimum": 1},
            "admissible_evidence_count": {"type": "integer", "minimum": 0},
            "traceability_row_count": {"type": "integer", "minimum": 1},
            "traceability_has_dangling_reference": {"type": "boolean"},
            "demo_preflight_state": {"type": "string",
                                     "enum": ["READY", "BLOCKED"]},
            "demo_stopped_at_step_id": {"type": ["string", "null"]},
            "contingency_scenario_count": {"type": "integer", "minimum": 14},
            "signoff_role_count": {"type": "integer", "const": 9},
            "signed_signoff_count": {"type": "integer", "const": 0},
            "blocker_owners": _STRING_ARRAY,
            "not_clinical_validation": {"type": "string", "minLength": 1},
            "override_available": {"type": "boolean", "const": False},
            "note": {"type": "string"},
        },
        "allOf": [
            {"if": {"required": ["ths6_achieved"],
                    "properties": {"ths6_achieved": {"const": True}}},
             "then": {"properties": {
                 "unmet_conditions": _EMPTY_ARRAY,
                 "demo_preflight_state": {"const": "READY"},
                 "ths6_achievement_conditions": {
                     "properties": {
                         "all_gates_pass": {"const": True},
                         "all_definition_of_done_items_satisfied": {
                             "const": True},
                         "representative_demonstration_executed": {
                             "const": True},
                         "all_signoff_roles_signed": {"const": True}}}}}},
            {"if": {"required": ["release_may_proceed"],
                    "properties": {"release_may_proceed": {"const": True}}},
             "then": {"properties": {"ths6_achieved": {"const": True}}}},
        ],
    }


def build_schemas() -> Mapping[str, Dict[str, Any]]:
    """Every WP-25 schema, keyed by the path it is published at."""
    return {
        "%s/evidence-item.schema.json" % SCHEMA_DIRECTORY: _evidence_item(),
        "%s/evidence-registry.schema.json" % SCHEMA_DIRECTORY:
            _evidence_registry(),
        "%s/finding.schema.json" % SCHEMA_DIRECTORY: _finding(),
        "%s/claim.schema.json" % SCHEMA_DIRECTORY: dict(
            _claim(), **{"$schema":
                         "https://json-schema.org/draft/2020-12/schema",
                         "title": "WP-25 claim",
                         "description":
                             "One statement and what would justify it. "
                             "SUPPORTED requires nothing missing."}),
        "%s/claim-registry.schema.json" % SCHEMA_DIRECTORY:
            _claim_registry(),
        "%s/traceability-row.schema.json" % SCHEMA_DIRECTORY: dict(
            _traceability_row(),
            **{"$schema": "https://json-schema.org/draft/2020-12/schema",
               "title": "WP-25 traceability row",
               "description":
                   "One requirement traced to its result. Anything short of "
                   "SUPPORTED must name the gap and its owner."}),
        "%s/traceability-matrix.schema.json" % SCHEMA_DIRECTORY:
            _traceability_matrix(),
        "%s/gate-condition.schema.json" % SCHEMA_DIRECTORY: _gate_condition(),
        "%s/gate-record.schema.json" % SCHEMA_DIRECTORY: dict(
            _gate_record(),
            **{"$schema": "https://json-schema.org/draft/2020-12/schema",
               "title": "WP-25 gate record",
               "description":
                   "One gate and its conjunction. PASS requires no unmet "
                   "condition and no blocker."}),
        "%s/gate-matrix.schema.json" % SCHEMA_DIRECTORY: _gate_matrix(),
        "%s/definition-of-done-item.schema.json" % SCHEMA_DIRECTORY:
            _dod_item(),
        "%s/definition-of-done-registry.schema.json" % SCHEMA_DIRECTORY:
            _dod_registry(),
        "%s/demo-manifest.schema.json" % SCHEMA_DIRECTORY: _demo_manifest(),
        "%s/demo-preflight.schema.json" % SCHEMA_DIRECTORY: _demo_preflight(),
        "%s/contingency-scenario.schema.json" % SCHEMA_DIRECTORY:
            _contingency_scenario(),
        "%s/contingency-matrix.schema.json" % SCHEMA_DIRECTORY:
            _contingency_matrix(),
        "%s/signoff-matrix.schema.json" % SCHEMA_DIRECTORY: _signoff_matrix(),
        "%s/evidence-pack-manifest.schema.json" % SCHEMA_DIRECTORY:
            _pack_manifest(),
        "%s/pack-integrity-result.schema.json" % SCHEMA_DIRECTORY:
            _pack_integrity_result(),
        "%s/ths6-status.schema.json" % SCHEMA_DIRECTORY: _ths6_status(),
    }


def _validate(document: Mapping[str, Any], name: str) -> List[str]:
    schemas = build_schemas()
    return list(validate_against_schema(
        document, schemas["%s/%s" % (SCHEMA_DIRECTORY, name)]))


def validate_evidence_item(document):
    return _validate(document, "evidence-item.schema.json")


def validate_evidence_registry(document):
    return _validate(document, "evidence-registry.schema.json")


def validate_claim_registry(document):
    return _validate(document, "claim-registry.schema.json")


def validate_traceability_matrix(document):
    return _validate(document, "traceability-matrix.schema.json")


def validate_gate_matrix(document):
    return _validate(document, "gate-matrix.schema.json")


def validate_definition_of_done(document):
    return _validate(document, "definition-of-done-registry.schema.json")


def validate_demo_manifest(document):
    return _validate(document, "demo-manifest.schema.json")


def validate_demo_preflight(document):
    return _validate(document, "demo-preflight.schema.json")


def validate_contingency_matrix(document):
    return _validate(document, "contingency-matrix.schema.json")


def validate_signoff_matrix(document):
    return _validate(document, "signoff-matrix.schema.json")


def validate_pack_manifest(document):
    return _validate(document, "evidence-pack-manifest.schema.json")


def validate_pack_integrity_result(document):
    return _validate(document, "pack-integrity-result.schema.json")


def validate_ths6_status(document):
    return _validate(document, "ths6-status.schema.json")


def write_schemas(root: str = ".") -> List[str]:
    """Write every schema to its published path. Returns what was written."""
    import io
    import os

    from pgx.ths6.integrity import canonical_json

    written: List[str] = []
    for relative, schema in sorted(build_schemas().items()):
        path = os.path.join(root, *relative.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write(canonical_json(schema))
        written.append(relative)
    return written
