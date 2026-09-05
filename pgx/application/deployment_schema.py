# -*- coding: utf-8 -*-
"""Published JSON Schemas for WP-24.

Seventeen schemas, and as in WP-21, WP-22 and WP-23 the constraints that carry
the content are the negative ones. A schema describing only the happy shape
would accept a performance result reporting a p95 of zero for a run that never
started, a smoke result calling a laptop "STAGING", a vulnerability report with
no scanner name, or a restore marked verified with one condition checked.

What is pinned, and why each pin is here rather than in a comment somebody
could stop reading:

- **Every measurement is nullable and none of them may be a false zero.**
  ``latency_p50_ms``, ``throughput_rps`` and ``error_rate`` accept ``null``;
  the schema additionally requires that when ``attempted`` is ``0`` every one
  of them *is* null. A zero-latency percentile in a report reads as an
  extraordinarily fast system.
- **A rehearsal cannot serialise as staging.** When ``environment_kind`` is
  ``LOCAL_REHEARSAL`` the schema requires ``rehearsal_label`` to be exactly
  ``LOCAL_STAGING_REHEARSAL``. The label is not optional and not free text.
- **A performance result must name its release.** ``release_id`` and
  ``release_manifest_hash`` are required together whenever the state is not
  ``BLOCKED``: a measurement pinned to nothing cannot be reproduced or
  contested.
- **A vulnerability scan that says nothing about what it compared against is
  not a passing scan.** ``state: VERIFIED`` requires ``scanner_name``,
  ``scanner_version`` and ``advisory_database_identity``.
- **A restore is verified only with all four conditions.**
  ``restore_verified: true`` requires ``restore_verification.all_satisfied``.
- **``release_may_proceed: true`` requires an empty
  ``unmet_required_gates``.** The two cannot disagree, so a document asserting
  the first while listing the second is refused rather than published.

Written against the supported subset that
``pgx.application.snapshot_schema.validate_against_schema`` implements: no
``patternProperties``, so keyed maps are described rather than pattern
matched.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

from pgx.application.snapshot_schema import validate_against_schema
from pgx.deployment.backup_execution import BACKUP_EXECUTION_VERSION
from pgx.deployment.gate_status import (GATE_E_STATUS_VERSION,
                                        WP24_GATE_STATUS_VERSION)
from pgx.deployment.image import IMAGE_INSPECTION_VERSION
from pgx.deployment.migration import MIGRATION_RESULT_VERSION
from pgx.deployment.performance import (PERFORMANCE_RESULT_VERSION,
                                        PERFORMANCE_TARGET_REGISTRY_VERSION)
from pgx.deployment.provenance import BUILD_PROVENANCE_VERSION
from pgx.deployment.release_validation import RELEASE_VALIDATION_VERSION
from pgx.deployment.reliability import RELIABILITY_RESULT_VERSION
from pgx.deployment.rollback import ROLLBACK_RESULT_VERSION
from pgx.deployment.runtime_assets import RUNTIME_ASSET_MANIFEST_VERSION
from pgx.deployment.smoke import SMOKE_RESULT_VERSION
from pgx.deployment.supply_chain import SUPPLY_CHAIN_RESULT_VERSION
from pgx.deployment.vocabulary import (DEPLOYMENT_BLOCKER_CODES,
                                       REHEARSAL_LABEL,
                                       DeploymentEnvironmentKind,
                                       ExecutionState)

__all__ = [
    "SCHEMA_DIRECTORY",
    "build_schemas",
    "validate_backup_execution",
    "validate_build_provenance",
    "validate_ci_status",
    "validate_deployment_result",
    "validate_gate_e_status",
    "validate_image_result",
    "validate_migration_result",
    "validate_performance_result",
    "validate_performance_targets",
    "validate_release_validation",
    "validate_reliability_catalogue",
    "validate_reliability_result",
    "validate_rollback_result",
    "validate_runtime_asset_manifest",
    "validate_smoke_result",
    "validate_supply_chain_result",
    "validate_wp24_gate_status",
]

SCHEMA_DIRECTORY = "schemas/wp24"

_STATES = [item.value for item in ExecutionState]
_ENVIRONMENTS = [item.value for item in DeploymentEnvironmentKind]
_BLOCKER_CODES = sorted(DEPLOYMENT_BLOCKER_CODES)


def _blocker_array() -> Dict[str, Any]:
    """A blocker names a declared code, a reason and an owner.

    ``owner`` is required. A blocker with no owner is one nobody is going to
    clear, and the four human blockers this project carries are exactly the
    ones an engineering plan tends to lose track of.
    """
    return {
        "type": "array",
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["code", "detail", "owner", "blocking"],
            "properties": {
                "code": {"type": "string", "enum": _BLOCKER_CODES},
                "detail": {"type": "string", "minLength": 1},
                "owner": {"type": "string", "minLength": 1},
                "blocking": {"type": "boolean"},
            },
        },
    }


def _nullable_number() -> Dict[str, Any]:
    return {"type": ["number", "null"]}


def _nullable_string() -> Dict[str, Any]:
    return {"type": ["string", "null"]}


def _rehearsal_rule() -> Dict[str, Any]:
    """A local rehearsal must carry the label. Enforced, not requested."""
    return {
        "if": {"properties": {
            "environment_kind": {"const":
                                 DeploymentEnvironmentKind
                                 .LOCAL_REHEARSAL.value}},
               "required": ["environment_kind"]},
        "then": {"properties": {"rehearsal_label": {
            "const": REHEARSAL_LABEL}},
            "required": ["rehearsal_label"]},
    }


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

def _build_provenance_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://pgx.local/schemas/wp24/build-provenance.schema.json",
        "title": "PGx build provenance (WP-24)",
        "description": (
            "What a build was made from. source_revision is null when the "
            "repository has no commit - this one has none - and the "
            "source-tree manifest hash is then the only content identity the "
            "build has. Every field describing something that did not happen "
            "is null, never a placeholder string, so two builds cannot match "
            "on the word 'unknown'."),
        "type": "object",
        "required": ["build_provenance_version", "source_revision",
                     "source_tree_manifest_hash", "pyproject_hash",
                     "lockfile_hash", "python_version", "platform_machine",
                     "image_digest", "built_at"],
        "properties": {
            "build_provenance_version": {
                "const": BUILD_PROVENANCE_VERSION},
            "source_revision": _nullable_string(),
            "source_tree_manifest_hash": {
                "type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
            "source_tree_file_count": {"type": "integer", "minimum": 0},
            "pyproject_hash": _nullable_string(),
            "lockfile_hash": _nullable_string(),
            "lockfile_present": {"type": "boolean"},
            "dockerfile_hash": _nullable_string(),
            "python_version": {"type": "string"},
            "platform_machine": {"type": "string"},
            "wheel_sha256": _nullable_string(),
            "sdist_sha256": _nullable_string(),
            "image_repository": _nullable_string(),
            "image_tag": _nullable_string(),
            "image_digest": _nullable_string(),
            "base_image": _nullable_string(),
            "base_image_digest": _nullable_string(),
            "runtime_asset_manifest_hash": {"type": "string"},
            "sbom_reference": _nullable_string(),
            "sbom_sha256": _nullable_string(),
            "built_at": _nullable_string(),
            "ci_run_id": _nullable_string(),
            "ci_run_url": _nullable_string(),
        },
        # A lockfile hash without a lockfile is a hash of nothing.
        "if": {"properties": {"lockfile_present": {"const": True}},
               "required": ["lockfile_present"]},
        "then": {"properties": {"lockfile_hash": {"type": "string"}}},
    }


def _runtime_asset_manifest_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": ("https://pgx.local/schemas/wp24/"
                "runtime-asset-manifest.schema.json"),
        "title": "PGx runtime asset manifest (WP-24)",
        "description": (
            "The exact files the runtime image must contain. An allowlist of "
            "files, never a directory: a directory is a promise about what "
            "somebody will remember not to put in it."),
        "type": "object",
        "required": ["runtime_asset_manifest_version", "assets",
                     "missing_required", "checksum_mismatches", "satisfied"],
        "properties": {
            "runtime_asset_manifest_version": {
                "const": RUNTIME_ASSET_MANIFEST_VERSION},
            "asset_count": {"type": "integer", "minimum": 1},
            "assets": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["path", "reason", "required", "present",
                                 "sha256"],
                    "properties": {
                        "path": {"type": "string", "minLength": 1},
                        # A reason per file. An allowlist entry nobody can
                        # justify is one nobody can remove either.
                        "reason": {"type": "string", "minLength": 10},
                        "required": {"type": "boolean"},
                        "present": {"type": "boolean"},
                        "sha256": _nullable_string(),
                        "matches_pinned": {"type": ["boolean", "null"]},
                    },
                },
            },
            "missing_required": {"type": "array",
                                 "items": {"type": "string"}},
            "checksum_mismatches": {"type": "array",
                                    "items": {"type": "string"}},
            "satisfied": {"type": "boolean"},
            "manifest_hash": {"type": "string"},
        },
    }


def _ci_status_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://pgx.local/schemas/wp24/ci-status.schema.json",
        "title": "PGx continuous integration status (WP-24)",
        "description": (
            "Workflows existing is CONFIGURED. A provider having run them is "
            "a different fact, and ci_executed stays null until one is "
            "observed - not false, because 'nobody has run it' and 'a run "
            "failed' need different actions."),
        "type": "object",
        "required": ["state", "workflows", "ci_executed"],
        "properties": {
            "state": {"type": "string", "enum": _STATES},
            "workflows": {"type": "array", "items": {"type": "string"}},
            "ci_executed": {"type": ["boolean", "null"]},
            "ci_run_id": _nullable_string(),
            "ci_run_url": _nullable_string(),
            "job_order": {"type": "array", "items": {"type": "string"}},
            "blockers": _blocker_array(),
        },
        # A run id with no observed run, or an observed run with no id, is a
        # document that cannot be checked against a provider.
        "if": {"properties": {"ci_executed": {"const": True}},
               "required": ["ci_executed"]},
        "then": {"required": ["ci_run_id"],
                 "properties": {"ci_run_id": {"type": "string"}}},
    }


def _migration_result_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://pgx.local/schemas/wp24/migration-result.schema.json",
        "title": "PGx migration execution result (WP-24)",
        "description": (
            "Where the revision chain is, where a database is, and whether "
            "they agree. executed is false until a migration ran against a "
            "server; the chain is a fact about files and says nothing about "
            "any database."),
        "type": "object",
        "required": ["migration_result_version", "state", "executed",
                     "chain"],
        "properties": {
            "migration_result_version": {"const": MIGRATION_RESULT_VERSION},
            "state": {"type": "string", "enum": _STATES},
            "executed": {"type": "boolean"},
            "expected_head": _nullable_string(),
            "database_revision": _nullable_string(),
            "database_revision_note": _nullable_string(),
            "applied_head": _nullable_string(),
            "chain": {
                "type": "object",
                "required": ["revision_count", "heads", "single_head"],
                "properties": {
                    "revision_count": {"type": "integer", "minimum": 1},
                    "file_count": {"type": "integer", "minimum": 1},
                    "heads": {"type": "array", "items": {"type": "string"}},
                    "single_head": {"type": "boolean"},
                    "head": _nullable_string(),
                },
            },
            "blockers": _blocker_array(),
        },
        # A migration cannot be executed with no database revision to show
        # for it.
        "if": {"properties": {"executed": {"const": True}},
               "required": ["executed"]},
        "then": {"anyOf": [
            {"properties": {"database_revision": {"type": "string"}},
             "required": ["database_revision"]},
            {"properties": {"applied_head": {"type": "string"}},
             "required": ["applied_head"]}]},
    }


def _image_result_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://pgx.local/schemas/wp24/image-result.schema.json",
        "title": "PGx image build result (WP-24)",
        "description": (
            "image_digest is present only when an image has been pushed or "
            "pulled; a purely local build has no repository digest, and "
            "inventing one would claim a registry identity that does not "
            "exist."),
        "type": "object",
        "required": ["image_result_version", "state", "reference",
                     "image_id", "image_digest"],
        "properties": {
            "image_result_version": {"const": IMAGE_INSPECTION_VERSION},
            "state": {"type": "string", "enum": _STATES},
            "reference": {"type": "string"},
            "image_id": _nullable_string(),
            "image_digest": _nullable_string(),
            "base_image_digest": _nullable_string(),
            "layer_diff_ids": {"type": "array",
                               "items": {"type": "string"}},
            # Non-root. A string, and the schema refuses the two spellings of
            # root rather than trusting a build to have set it.
            "user": {"type": ["string", "null"],
                     "not": {"enum": ["root", "0", "0:0"]}},
            "entrypoint": {"type": ["array", "null"],
                           "items": {"type": "string"}},
            "command": {"type": ["array", "null"],
                        "items": {"type": "string"}},
            "exposed_ports": {"type": "array", "items": {"type": "string"}},
            "architecture": _nullable_string(),
            "os": _nullable_string(),
            "size_bytes": {"type": ["integer", "null"], "minimum": 0},
            "runtime_assets": {"type": "object"},
            "blockers": _blocker_array(),
        },
    }


def _deployment_result_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://pgx.local/schemas/wp24/deployment-result.schema.json",
        "title": "PGx deployment result (WP-24)",
        "description": (
            "One deployment action and where it happened. A LOCAL_REHEARSAL "
            "must carry the rehearsal label; nothing in this project may "
            "describe a laptop as staging."),
        "type": "object",
        "required": ["state", "environment_kind"],
        "properties": {
            "state": {"type": "string", "enum": _STATES},
            "environment_kind": {"type": "string", "enum": _ENVIRONMENTS},
            "rehearsal_label": _nullable_string(),
            "compose_project": _nullable_string(),
            "services": {"type": "array", "items": {"type": "string"}},
            "volumes_removed": {"const": False},
            "blockers": _blocker_array(),
        },
        **_rehearsal_rule(),
    }


def _smoke_result_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://pgx.local/schemas/wp24/staging-smoke.schema.json",
        "title": "PGx staging smoke result (WP-24)",
        "description": (
            "Status codes, component names and cookie attribute compliance. "
            "No response body appears here: a smoke report that captured "
            "bodies would capture whatever the deployment was serving."),
        "type": "object",
        "required": ["staging_smoke_version", "state", "environment_kind"],
        "properties": {
            "staging_smoke_version": {"const": SMOKE_RESULT_VERSION},
            "state": {"type": "string", "enum": _STATES},
            "environment_kind": {"type": "string", "enum": _ENVIRONMENTS},
            "rehearsal_label": _nullable_string(),
            "base_url_scheme": _nullable_string(),
            "tls_used": {"type": ["boolean", "null"]},
            # Never true. There is no code path that disables verification
            # and no document may report one that did.
            "tls_verification_disabled": {"const": False},
            "tls_trust_source": _nullable_string(),
            "observed_at": _nullable_string(),
            "liveness": {"type": ["object", "null"]},
            "readiness": {"type": ["object", "null"]},
            "login_page_status": {"type": ["integer", "null"]},
            "cookie_policy": {"type": ["object", "null"]},
            "blockers": _blocker_array(),
        },
        **_rehearsal_rule(),
    }


def _performance_targets_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": ("https://pgx.local/schemas/wp24/"
                "performance-targets.schema.json"),
        "title": "PGx performance target registry (WP-24)",
        "description": (
            "Declared before any measurement exists. A target chosen after "
            "the numbers is not a target, it is a description."),
        "type": "object",
        "required": ["performance_target_registry_version",
                     "declared_before_measurement", "required_attempts",
                     "percentile_definition", "zero_denominator_behaviour",
                     "targets"],
        "properties": {
            "performance_target_registry_version": {
                "const": PERFORMANCE_TARGET_REGISTRY_VERSION},
            "declared_before_measurement": {"const": True},
            "required_attempts": {"const": 1000},
            "warmup_attempts": {"type": "integer", "minimum": 0},
            "percentile_definition": {"type": "string", "minLength": 40},
            "zero_denominator_behaviour": {"type": "string",
                                           "minLength": 40},
            "not_a_clinical_claim": {"type": "string", "minLength": 40},
            "targets": {
                "type": "array", "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["target_id", "metric", "comparator",
                                 "value", "unit", "rationale"],
                    "properties": {
                        "target_id": {"type": "string"},
                        "metric": {"type": "string"},
                        "comparator": {"type": "string",
                                       "enum": ["<=", ">=", "=="]},
                        "value": {"type": "number"},
                        "unit": {"type": "string"},
                        # A number with no reason behind it cannot be argued
                        # with, and a target nobody can argue with is one
                        # nobody will revise when it is wrong.
                        "rationale": {"type": "string", "minLength": 40},
                    },
                },
            },
        },
    }


def _performance_result_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": ("https://pgx.local/schemas/wp24/"
                "performance-result.schema.json"),
        "title": "PGx performance execution result (WP-24)",
        "description": (
            "Every measurement is nullable and none may be a false zero. A "
            "run that did not happen reports null latency, null throughput "
            "and a null error rate - a zero error rate for a run that never "
            "started is the most misleading number this document could "
            "carry."),
        "type": "object",
        "required": ["performance_result_version", "state",
                     "attempts_required", "attempted", "completed", "failed",
                     "latency_p50_ms", "latency_p95_ms", "throughput_rps",
                     "error_rate", "release_id", "release_manifest_hash",
                     "environment_kind"],
        "properties": {
            "performance_result_version": {
                "const": PERFORMANCE_RESULT_VERSION},
            "state": {"type": "string", "enum": _STATES},
            "test_only": {"type": "boolean"},
            "environment_kind": {"type": "string", "enum": _ENVIRONMENTS},
            "rehearsal_label": _nullable_string(),
            "attempts_required": {"const": 1000},
            "attempts_meets_requirement": {"type": "boolean"},
            "warmup_attempts": {"type": "integer", "minimum": 0},
            "concurrency": {"type": "integer", "minimum": 1},
            "attempted": {"type": "integer", "minimum": 0},
            "completed": {"type": ["integer", "null"], "minimum": 0},
            "failed": {"type": ["integer", "null"], "minimum": 0},
            "latency_p50_ms": _nullable_number(),
            "latency_p95_ms": _nullable_number(),
            "latency_p99_ms": _nullable_number(),
            "latency_min_ms": _nullable_number(),
            "latency_max_ms": _nullable_number(),
            "throughput_rps": _nullable_number(),
            "error_rate": _nullable_number(),
            "response_code_distribution": {"type": "object"},
            "wall_seconds": _nullable_number(),
            "release_id": _nullable_string(),
            "release_manifest_hash": _nullable_string(),
            "software_id": _nullable_string(),
            "dataset_id": _nullable_string(),
            "ruleset_id": _nullable_string(),
            "input_case_count": {"type": "integer", "minimum": 0},
            "input_mix_hash": _nullable_string(),
            "input_case_ids": {"type": "array", "items": {"type": "string"}},
            "image_digest": _nullable_string(),
            "resource_limits": {"type": "object"},
            "started_at": _nullable_string(),
            "finished_at": _nullable_string(),
            "target_registry_version": {
                "const": PERFORMANCE_TARGET_REGISTRY_VERSION},
            "targets_evaluated": {"type": "array"},
            "output_determinism": {"type": "object"},
            "blockers": _blocker_array(),
        },
        "allOf": [
            _rehearsal_rule(),
            # Nothing attempted means nothing measured. Stated in the schema
            # so a producer cannot emit a zero and a reader cannot be misled
            # by one.
            {"if": {"properties": {"attempted": {"const": 0}},
                    "required": ["attempted"]},
             "then": {"properties": {
                 "latency_p50_ms": {"type": "null"},
                 "latency_p95_ms": {"type": "null"},
                 "throughput_rps": {"type": "null"},
                 "error_rate": {"type": "null"}}}},
            # A measurement that is not blocked must name the release it was
            # taken against, both id and manifest hash.
            {"if": {"properties": {"state": {"enum": [
                ExecutionState.EXECUTED.value,
                ExecutionState.VERIFIED.value,
                ExecutionState.OBSERVED.value]}},
                "required": ["state"]},
             "then": {"properties": {
                 "release_id": {"type": "string", "minLength": 1},
                 "release_manifest_hash": {"type": "string",
                                           "minLength": 1}}}},
        ],
    }


def _reliability_result_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": ("https://pgx.local/schemas/wp24/"
                "reliability-drill.schema.json"),
        "title": "PGx reliability drill result (WP-24)",
        "description": (
            "A drill with no runner is BLOCKED, never passed. The three "
            "states - verified, executed-and-wrong, and not run - need "
            "different actions from different people."),
        "type": "object",
        "required": ["reliability_drill_version", "state"],
        "properties": {
            "reliability_drill_version": {
                "const": RELIABILITY_RESULT_VERSION},
            "state": {"type": "string", "enum": _STATES},
            "environment_kind": {"type": "string", "enum": _ENVIRONMENTS},
            "rehearsal_label": _nullable_string(),
            "declared_count": {"type": "integer", "minimum": 1},
            "drill_count": {"type": "integer", "minimum": 1},
            "executed_count": {"type": "integer", "minimum": 0},
            "failed_count": {"type": "integer", "minimum": 0},
            "passed_count": {"type": ["integer", "null"], "minimum": 0},
            "observed_at": _nullable_string(),
            "drills": {"type": "array"},
            "results": {"type": "array"},
            "blockers": _blocker_array(),
        },
        "allOf": [
            _rehearsal_rule(),
            # Nothing executed means no pass count. Zero would read as "none
            # of them passed", which is a different and much worse claim.
            {"if": {"properties": {"executed_count": {"const": 0}},
                    "required": ["executed_count"]},
             "then": {"properties": {"passed_count": {"type": "null"}}}},
        ],
    }


def _reliability_catalogue_schema() -> Dict[str, Any]:
    """The declared drills. A different document from a drill *result*.

    Kept separate rather than described by one permissive schema that fits
    both: a catalogue has no state and no outcome, and a schema loose enough
    to accept either would accept a result with no state at all - which is
    the one field that says whether anything happened.
    """
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": ("https://pgx.local/schemas/wp24/"
                "reliability-drill-catalogue.schema.json"),
        "title": "PGx reliability drill catalogue (WP-24)",
        "description": (
            "Declared before execution. A drill catalogue written after the "
            "results is a list of the failures that happened to be "
            "survived."),
        "type": "object",
        "required": ["reliability_drill_version", "drill_count", "drills"],
        "properties": {
            "reliability_drill_version": {
                "const": RELIABILITY_RESULT_VERSION},
            "drill_count": {"type": "integer", "minimum": 1},
            "drills": {
                "type": "array", "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["drill_id", "title", "injected_failure",
                                 "expected_behaviour", "requires",
                                 "runnable_in_process"],
                    "properties": {
                        "drill_id": {"type": "string"},
                        "title": {"type": "string", "minLength": 5},
                        # What is deliberately broken, and what must happen.
                        # Both required: a drill that names no injected
                        # failure is an observation, and one that names no
                        # expected behaviour cannot fail.
                        "injected_failure": {"type": "string",
                                             "minLength": 10},
                        "expected_behaviour": {"type": "string",
                                               "minLength": 20},
                        "requires": {"type": "array",
                                     "items": {"type": "string"}},
                        "runnable_in_process": {"type": "boolean"},
                    },
                },
            },
        },
    }


def _rollback_result_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://pgx.local/schemas/wp24/rollback-drill.schema.json",
        "title": "PGx rollback drill result (WP-24)",
        "description": (
            "Two operations share the word rollback. A deployment rollback "
            "must not downgrade the schema, and a governed release rollback "
            "never edits a manifest."),
        "type": "object",
        "required": ["rollback_result_version", "kind", "state"],
        "properties": {
            "rollback_result_version": {"const": ROLLBACK_RESULT_VERSION},
            "kind": {"type": "string",
                     "enum": ["deployment_image", "governed_release"]},
            "state": {"type": "string", "enum": _STATES},
            "environment_kind": {"type": "string", "enum": _ENVIRONMENTS},
            "rehearsal_label": _nullable_string(),
            "test_only": {"type": "boolean"},
            "previous_image": {"type": ["object", "null"]},
            "candidate_image": {"type": ["object", "null"]},
            "rollback_target_explicit": {"type": "boolean"},
            # Never true in a verified drill. A rollback that downgraded the
            # schema is not the operation this drill is for, and letting it
            # pass would put the procedure in a runbook.
            "database_downgraded": {"type": "boolean"},
            "health_before": {"type": ["object", "null"]},
            "health_after": {"type": ["object", "null"]},
            "eligible_release_count": {"type": "integer", "minimum": 0},
            "active_release_id": _nullable_string(),
            "rolled_back_to": _nullable_string(),
            "audited_event_id": _nullable_string(),
            "manifest_edited": {"const": False},
            "observed_at": _nullable_string(),
            "blockers": _blocker_array(),
        },
        "allOf": [
            _rehearsal_rule(),
            {"if": {"properties": {"state": {
                "const": ExecutionState.VERIFIED.value}},
                "required": ["state"]},
             "then": {"properties": {
                 "database_downgraded": {"const": False}}}},
        ],
    }


def _backup_execution_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": ("https://pgx.local/schemas/wp24/"
                "backup-restore-execution.schema.json"),
        "title": "PGx backup and restore execution (WP-24)",
        "description": (
            "A successor to WP-23's status artifact, never a replacement. A "
            "restore is verified only when all four runbook conditions hold; "
            "pg_restore exiting zero satisfies none of them."),
        "type": "object",
        "required": ["backup_execution_version", "state",
                     "operational_status", "backup_executed",
                     "restore_verified", "destination_kind",
                     "restore_verification"],
        "properties": {
            "backup_execution_version": {"const": BACKUP_EXECUTION_VERSION},
            "state": {"type": "string", "enum": _STATES},
            "operational_status": {
                "type": "string",
                "enum": ["BLOCKED", "VERIFIED", "LOCAL_REHEARSAL_VERIFIED"]},
            "supersedes": {"type": "string"},
            "backup_executed": {"type": "boolean"},
            # A kind, never a path: a path can name a host, a bucket, an
            # account or a customer.
            "destination_kind": {
                "type": "string",
                "enum": ["none", "temporary", "local_path", "remote"]},
            "encrypted_at_rest": {"type": ["boolean", "null"]},
            "scope": {"type": "object"},
            "restore_verification": {
                "type": "object",
                "required": ["conditions", "condition_count",
                             "satisfied_count", "all_satisfied"],
                "properties": {
                    "conditions": {"type": "array", "minItems": 4},
                    "condition_count": {"const": 4},
                    "satisfied_count": {"type": "integer", "minimum": 0},
                    "unevaluated_count": {"type": "integer", "minimum": 0},
                    "all_satisfied": {"type": "boolean"},
                },
            },
            "restore_verified": {"type": "boolean"},
            "local_rehearsal": {"type": "boolean"},
            "observed_at": _nullable_string(),
            "blockers": _blocker_array(),
        },
        "allOf": [
            # All four, or not verified.
            {"if": {"properties": {"restore_verified": {"const": True}},
                    "required": ["restore_verified"]},
             "then": {"properties": {"restore_verification": {
                 "properties": {"all_satisfied": {"const": True}}}}}},
            # A temporary directory beside the source database is a drill
            # artifact, not an operational backup.
            {"if": {"properties": {"operational_status": {
                "const": "VERIFIED"}}, "required": ["operational_status"]},
             "then": {"properties": {"destination_kind": {
                 "enum": ["local_path", "remote"]}}}},
        ],
    }


def _supply_chain_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": ("https://pgx.local/schemas/wp24/"
                "supply-chain-result.schema.json"),
        "title": "PGx SBOM and vulnerability result (WP-24)",
        "description": (
            "A vulnerability report's most important field is not the count "
            "of findings; it is what they were compared against. A VERIFIED "
            "scan must name the scanner, its version and the advisory "
            "database."),
        "type": "object",
        "required": ["supply_chain_version", "sbom", "vulnerability_scan"],
        "properties": {
            "supply_chain_version": {"const": SUPPLY_CHAIN_RESULT_VERSION},
            "sbom": {
                "type": "object",
                "required": ["state", "generator", "source"],
                "properties": {
                    "state": {"type": "string", "enum": _STATES},
                    "generator": _nullable_string(),
                    "format": _nullable_string(),
                    # Never pyproject.toml: that file declares ranges, and a
                    # bill of materials from a range lists what might be
                    # there.
                    "source": {"type": ["string", "null"],
                               "enum": ["image", "lockfile", None]},
                    "path": _nullable_string(),
                    "blockers": _blocker_array(),
                },
            },
            "vulnerability_scan": {
                "type": "object",
                "required": ["state", "scanner_name", "scanner_version",
                             "advisory_database_identity", "severity_policy"],
                "properties": {
                    "state": {"type": "string", "enum": _STATES},
                    "scanner_name": _nullable_string(),
                    "scanner_version": _nullable_string(),
                    "advisory_database_identity": _nullable_string(),
                    "advisory_database_date": _nullable_string(),
                    "image_reference": _nullable_string(),
                    "image_digest": _nullable_string(),
                    "severity_policy": {"type": "object"},
                    "blocking_severities": {"type": "array"},
                    "finding_counts": {"type": ["object", "null"]},
                    "blocking_finding_count": {"type": ["integer", "null"]},
                    "exit_code": {"type": ["integer", "null"]},
                    "active_ignores": {"type": "array"},
                    "expired_ignores": {"type": "array"},
                    "blockers": _blocker_array(),
                },
                # A scan that says nothing about what it compared against is
                # not a passing scan.
                "if": {"properties": {"state": {
                    "const": ExecutionState.VERIFIED.value}},
                    "required": ["state"]},
                "then": {"properties": {
                    "scanner_name": {"type": "string", "minLength": 1},
                    "scanner_version": {"type": "string", "minLength": 1},
                    "advisory_database_identity": {"type": "string",
                                                   "minLength": 1}}},
            },
            "secret_scan": {"type": "object"},
            "release_path_clear": {"type": "boolean"},
            "blockers": _blocker_array(),
        },
    }


def _release_validation_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": ("https://pgx.local/schemas/wp24/"
                "release-validation.schema.json"),
        "title": "PGx release validation (WP-24)",
        "description": (
            "release_may_proceed is the conjunction of the required gates. "
            "There is no override, no force flag and no warn-only mode, and "
            "a TEST_ONLY_REHEARSAL never closes a gate."),
        "type": "object",
        "required": ["release_validation_version", "gates",
                     "unmet_required_gates", "release_may_proceed",
                     "image_released", "image_published"],
        "properties": {
            "release_validation_version": {
                "const": RELEASE_VALIDATION_VERSION},
            "evaluated_at": {"type": "string"},
            "gate_count": {"type": "integer", "minimum": 1},
            "required_gate_count": {"type": "integer", "minimum": 1},
            "satisfied_required_count": {"type": "integer", "minimum": 0},
            "gates": {
                "type": "array", "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["gate", "state", "required",
                                 "may_close_gate"],
                    "properties": {
                        "gate": {"type": "string"},
                        "state": {"type": "string", "enum": _STATES},
                        "detail": {"type": "string"},
                        "source": _nullable_string(),
                        "required": {"type": "boolean"},
                        "may_close_gate": {"type": "boolean"},
                    },
                },
            },
            "unmet_required_gates": {"type": "array",
                                     "items": {"type": "string"}},
            "release_may_proceed": {"type": "boolean"},
            "image_built": {"type": "boolean"},
            "image_released": {"type": "boolean"},
            "image_published": {"type": "boolean"},
            "blockers": _blocker_array(),
        },
        # The two cannot disagree. A document asserting the release may
        # proceed while listing unmet gates is refused rather than published.
        "if": {"properties": {"release_may_proceed": {"const": True}},
               "required": ["release_may_proceed"]},
        "then": {"properties": {
            "unmet_required_gates": {"type": "array", "maxItems": 0}}},
    }


def _wp24_gate_status_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://pgx.local/schemas/wp24/wp24-gate-status.schema.json",
        "title": "PGx WP-24 gate status (WP-24)",
        "description": (
            "Implemented, configured and executed are three groups and they "
            "are allowed to disagree. In this repository the first is "
            "complete and the other two are almost entirely absent."),
        "type": "object",
        "required": ["gate_status_schema_version", "work_package",
                     "implementation_status", "deployment_gate_status",
                     "release_may_proceed", "ci_executed",
                     "migration_executed", "restore_verified"],
        "properties": {
            "gate_status_schema_version": {
                "const": WP24_GATE_STATUS_VERSION},
            "work_package": {"const": "WP-24"},
            "generated_at": {"type": "string"},
            "implementation_status": {"type": "string",
                                      "enum": ["IMPLEMENTED", "INCOMPLETE"]},
            "deployment_package_present": {"type": "boolean"},
            "module_markers_found": {"type": "integer", "minimum": 0},
            "module_markers_expected": {"type": "integer", "minimum": 1},
            "missing_markers": {"type": "array", "items": {"type": "string"}},
            "dockerfile_present": {"type": "boolean"},
            "dockerignore_present": {"type": "boolean"},
            "compose_topology_present": {"type": "boolean"},
            "ci_workflows_present": {"type": "array",
                                     "items": {"type": "string"}},
            "deploy_cli_present": {"type": "boolean"},
            "runtime_composition_implemented": {"type": "boolean"},
            "container_runtime_available": {"type": "boolean"},
            "package_index_reachable": {"type": "boolean"},
            "argon2_available": {"type": "boolean"},
            "lockfile_present": {"type": "boolean"},
            "lockfile_state": _nullable_string(),
            "database_url_configured": {"type": "boolean"},
            "distribution_build_state": _nullable_string(),
            "image_build_state": _nullable_string(),
            "image_digest": _nullable_string(),
            "migration_state": _nullable_string(),
            "migration_executed": {"type": "boolean"},
            "staging_smoke_state": _nullable_string(),
            "staging_environment_kind": _nullable_string(),
            "tls_observed": {"type": "boolean"},
            "performance_state": _nullable_string(),
            # Null, not zero. A zero here would say a thousand assessments
            # completed in no time.
            "performance_completed": {"type": ["integer", "null"]},
            "reliability_state": _nullable_string(),
            "reliability_executed_count": {"type": ["integer", "null"]},
            "rollback_state": _nullable_string(),
            "backup_state": _nullable_string(),
            "backup_operational_status": _nullable_string(),
            "restore_verified": {"type": "boolean"},
            "sbom_state": _nullable_string(),
            "vulnerability_scan_state": _nullable_string(),
            # Null until observed. Not false: "nobody has run it" and "a run
            # failed" need different actions.
            "ci_executed": {"type": ["boolean", "null"]},
            "ci_action_pins_resolved": {"type": "boolean"},
            "deployment_gate_status": {"type": "string",
                                       "enum": ["PASS", "BLOCKED"]},
            "release_may_proceed": {"type": "boolean"},
            "unmet_required_gates": {"type": "array"},
            "blockers": _blocker_array(),
        },
        "if": {"properties": {"deployment_gate_status": {"const": "PASS"}},
               "required": ["deployment_gate_status"]},
        "then": {"properties": {"release_may_proceed": {"const": True},
                                "migration_executed": {"const": True},
                                "restore_verified": {"const": True}}},
    }


def _gate_e_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": ("https://pgx.local/schemas/wp24/"
                "gate-e-operational-status.schema.json"),
        "title": "PGx Gate E operational status (WP-24)",
        "description": (
            "Gate E needs both halves. WP-23's security gate and WP-24's "
            "deployment gate are read from their own artifacts and neither "
            "is inferred from the other."),
        "type": "object",
        "required": ["gate_status_schema_version", "gate", "gate_e_status",
                     "release_may_proceed", "ci_executed",
                     "image_published"],
        "properties": {
            "gate_status_schema_version": {"const": GATE_E_STATUS_VERSION},
            "gate": {"const": "Gate E - Operational"},
            "definition_source": {"type": "string"},
            "work_packages": {"type": "array", "items": {"type": "string"}},
            "generated_at": {"type": "string"},
            "wp23_security_gate_status": _nullable_string(),
            "wp23_implementation_status": _nullable_string(),
            "wp24_deployment_gate_status": _nullable_string(),
            "wp24_implementation_status": _nullable_string(),
            "authentication_configured": {"type": "boolean"},
            "canonical_audit_implemented": {"type": "boolean"},
            "audit_chain_verified": {"type": ["boolean", "null"]},
            "ci_configured": {"type": "boolean"},
            "ci_executed": {"type": ["boolean", "null"]},
            "image_built": {"type": "boolean"},
            "image_published": {"const": False},
            "staging_deployed": {"type": "boolean"},
            "staging_is_remote": {"type": "boolean"},
            "tls_observed": {"type": "boolean"},
            "rollback_exercised": {"type": "boolean"},
            "backup_operational": {"type": "boolean"},
            "restore_verified": {"type": "boolean"},
            "reliability_evidence": _nullable_string(),
            "performance_evidence": _nullable_string(),
            "claim_boundary_status": _nullable_string(),
            "gate_e_status": {"type": "string", "enum": ["PASS", "BLOCKED"]},
            "release_may_proceed": {"type": "boolean"},
        },
        "if": {"properties": {"gate_e_status": {"const": "PASS"}},
               "required": ["gate_e_status"]},
        "then": {"properties": {
            "wp23_security_gate_status": {"const": "PASS"},
            "wp24_deployment_gate_status": {"const": "PASS"},
            "tls_observed": {"const": True},
            "restore_verified": {"const": True}}},
    }


# ---------------------------------------------------------------------------
# Registry and validators
# ---------------------------------------------------------------------------

def build_schemas() -> Dict[str, Dict[str, Any]]:
    """Every WP-24 schema, by committed path."""
    return {
        SCHEMA_DIRECTORY + "/build-provenance.schema.json":
            _build_provenance_schema(),
        SCHEMA_DIRECTORY + "/runtime-asset-manifest.schema.json":
            _runtime_asset_manifest_schema(),
        SCHEMA_DIRECTORY + "/ci-status.schema.json": _ci_status_schema(),
        SCHEMA_DIRECTORY + "/migration-result.schema.json":
            _migration_result_schema(),
        SCHEMA_DIRECTORY + "/image-result.schema.json":
            _image_result_schema(),
        SCHEMA_DIRECTORY + "/deployment-result.schema.json":
            _deployment_result_schema(),
        SCHEMA_DIRECTORY + "/staging-smoke.schema.json":
            _smoke_result_schema(),
        SCHEMA_DIRECTORY + "/performance-targets.schema.json":
            _performance_targets_schema(),
        SCHEMA_DIRECTORY + "/performance-result.schema.json":
            _performance_result_schema(),
        SCHEMA_DIRECTORY + "/reliability-drill.schema.json":
            _reliability_result_schema(),
        SCHEMA_DIRECTORY + "/reliability-drill-catalogue.schema.json":
            _reliability_catalogue_schema(),
        SCHEMA_DIRECTORY + "/rollback-drill.schema.json":
            _rollback_result_schema(),
        SCHEMA_DIRECTORY + "/backup-restore-execution.schema.json":
            _backup_execution_schema(),
        SCHEMA_DIRECTORY + "/supply-chain-result.schema.json":
            _supply_chain_schema(),
        SCHEMA_DIRECTORY + "/release-validation.schema.json":
            _release_validation_schema(),
        SCHEMA_DIRECTORY + "/wp24-gate-status.schema.json":
            _wp24_gate_status_schema(),
        SCHEMA_DIRECTORY + "/gate-e-operational-status.schema.json":
            _gate_e_schema(),
    }


def _validate(document: Mapping[str, Any],
              schema: Mapping[str, Any]) -> List[str]:
    return list(validate_against_schema(document, schema))


def validate_build_provenance(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _build_provenance_schema())


def validate_runtime_asset_manifest(document: Mapping[str, Any]
                                    ) -> List[str]:
    return _validate(document, _runtime_asset_manifest_schema())


def validate_ci_status(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _ci_status_schema())


def validate_migration_result(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _migration_result_schema())


def validate_image_result(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _image_result_schema())


def validate_deployment_result(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _deployment_result_schema())


def validate_smoke_result(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _smoke_result_schema())


def validate_performance_targets(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _performance_targets_schema())


def validate_performance_result(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _performance_result_schema())


def validate_reliability_result(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _reliability_result_schema())


def validate_reliability_catalogue(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _reliability_catalogue_schema())


def validate_rollback_result(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _rollback_result_schema())


def validate_backup_execution(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _backup_execution_schema())


def validate_supply_chain_result(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _supply_chain_schema())


def validate_release_validation(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _release_validation_schema())


def validate_wp24_gate_status(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _wp24_gate_status_schema())


def validate_gate_e_status(document: Mapping[str, Any]) -> List[str]:
    return _validate(document, _gate_e_schema())
