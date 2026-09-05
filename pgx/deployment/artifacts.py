# -*- coding: utf-8 -*-
"""Committed WP-24 artifacts (WP-24).

Two kinds of document, kept in two places, because they answer different
questions and go stale for different reasons.

**Committed, under ``data/deployment/``.** Documents that describe *this
repository*: the declared performance targets, the reliability drill
catalogue, the runtime asset manifest, the restore conditions. They are
deterministic - the same source produces the same bytes - so WP-19's
reproducibility generator can compare a fresh build against the committed copy
and report drift.

**Generated, under ``.deploy-out/``.** Documents that describe *one host at
one moment*: an environment probe, an image result, a smoke observation, a
performance run. Committing those would mean a repository whose artifacts
change depending on who ran a command last, and a reproducibility check that
failed for everybody. They are gitignored and are written where a CI job can
upload them.

The split is the same one WP-19 already makes for gate statuses, and it is why
``DETERMINISTIC_ARTIFACT_PATHS`` excludes the gate status and the release
validation: both measure the filesystem and the environment, and a document
that measures the machine is supposed to differ between machines.
"""

from __future__ import annotations

import io
import json
import os
from typing import Mapping, Optional, Sequence, Tuple

__all__ = [
    "ARTIFACT_PATHS",
    "DETERMINISTIC_ARTIFACT_PATHS",
    "GENERATED_OUTPUT_DIRECTORY",
    "canonical_json",
    "write_deployment_artifacts",
]

#: Where environment-specific output goes. Gitignored, uploaded by CI.
GENERATED_OUTPUT_DIRECTORY = ".deploy-out"

#: Committed documents, and what each describes.
ARTIFACT_PATHS: Mapping[str, str] = {
    "data/deployment/wp24-performance-targets.json":
        "the declared engineering targets, published before any measurement",
    "data/deployment/wp24-reliability-drills.json":
        "the declared failure drills, published before any is run",
    "data/deployment/wp24-runtime-asset-manifest.json":
        "the exact files the runtime image must contain, with checksums",
    "data/deployment/wp24-restore-conditions.json":
        "the four conditions a restore must satisfy to be verified",
    "data/deployment/wp24-secret-configuration.json":
        "which deployment secrets exist and by which mechanism - names and "
        "mechanisms only, never a value",
    "data/deployment/wp24-real-gate-status.json":
        "the real WP-24 gate status for this repository",
    "data/deployment/wp24-release-validation.json":
        "the release-validation aggregate for this repository",
    "data/deployment/wp24-gate-e-status.json":
        "Gate E, read from WP-23's and WP-24's own artifacts",
    "data/deployment/wp24-build-provenance.json":
        "what this repository would be built from: source manifest, "
        "pyproject and lockfile identities, with null wherever nothing "
        "happened",
}

#: The subset a reproducibility check may compare byte for byte. The gate
#: status, the release validation and the provenance are excluded: each
#: measures the filesystem, the environment or a clock, and a document that
#: measures the machine is supposed to differ between machines.
DETERMINISTIC_ARTIFACT_PATHS: Tuple[str, ...] = (
    "data/deployment/wp24-performance-targets.json",
    "data/deployment/wp24-reliability-drills.json",
    "data/deployment/wp24-restore-conditions.json",
)


def canonical_json(document: Mapping[str, object]) -> str:
    """The project's canonical JSON form, spelled the same way everywhere."""
    return json.dumps(document, indent=2, sort_keys=True,
                      ensure_ascii=True) + "\n"


def build_restore_conditions_document() -> Mapping[str, object]:
    from pgx.deployment.backup_execution import (BACKUP_EXECUTION_VERSION,
                                                 RESTORE_CONDITIONS)

    return {
        "backup_execution_version": BACKUP_EXECUTION_VERSION,
        "condition_count": len(RESTORE_CONDITIONS),
        "conditions": [dict(item) for item in RESTORE_CONDITIONS],
        "all_four_required": True,
        "note": (
            "All four, or the restore is not verified. pg_restore exiting "
            "zero satisfies none of them: it says the archive was readable."),
    }


def write_deployment_artifacts(root: str = ".", *,
                               documents: Optional[Mapping[str, Mapping]]
                               = None) -> Sequence[str]:
    """Write the committed artifacts. Returns the paths written."""
    from pgx.deployment.performance import target_registry
    from pgx.deployment.reliability import drill_catalogue
    from pgx.deployment.runtime_assets import build_runtime_asset_manifest
    from pgx.deployment.secrets import secret_configuration_report

    built = {
        "data/deployment/wp24-performance-targets.json": target_registry(),
        "data/deployment/wp24-reliability-drills.json": drill_catalogue(),
        "data/deployment/wp24-runtime-asset-manifest.json":
            build_runtime_asset_manifest(root),
        "data/deployment/wp24-restore-conditions.json":
            build_restore_conditions_document(),
        "data/deployment/wp24-secret-configuration.json":
            secret_configuration_report(),
    }
    built.update(dict(documents or {}))
    written = []
    for relative, document in sorted(built.items()):
        path = os.path.join(root, *relative.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write(canonical_json(document))
        written.append(relative)
    return tuple(written)


def write_generated_artifact(root: str, name: str,
                             document: Mapping[str, object]) -> str:
    """Write an environment-specific observation to the generated directory.

    Never under ``data/``. A repository whose committed artifacts changed
    depending on who ran a command last would have a reproducibility check
    that failed for everybody, which is the fastest way to teach a team to
    ignore one.
    """
    directory = os.path.join(root, GENERATED_OUTPUT_DIRECTORY)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, name)
    with io.open(path, "w", encoding="utf-8") as handle:
        handle.write(canonical_json(document))
    return os.path.join(GENERATED_OUTPUT_DIRECTORY, name)


def build_artifacts(root: str) -> Mapping[str, str]:
    """Every deterministic artifact, rendered. WP-19's generator signature.

    Only the deterministic ones. The gate status, the release validation and
    the provenance are excluded because each measures the filesystem, the
    environment or a clock - a document that measures the machine is supposed
    to differ between machines, and comparing one byte for byte would fail for
    everybody, which is the fastest way to teach a team to ignore a
    reproducibility check.

    Registered with WP-19 rather than checked only by WP-24's own suite
    because the failure this catches is invisible inside one interpreter: the
    performance target registry and the drill catalogue are built from tuples
    of dataclasses, and a future refactor to a set or a dict comprehension
    would be stable within a process and differ between two at different hash
    seeds.
    """
    from pgx.application.deployment_schema import build_schemas
    from pgx.deployment.performance import target_registry
    from pgx.deployment.reliability import drill_catalogue

    documents = {
        "data/deployment/wp24-performance-targets.json":
            canonical_json(target_registry()),
        "data/deployment/wp24-reliability-drills.json":
            canonical_json(drill_catalogue()),
        "data/deployment/wp24-restore-conditions.json":
            canonical_json(build_restore_conditions_document()),
        "data/deployment/wp24-runtime-asset-manifest.json":
            canonical_json(build_runtime_asset_manifest_for(root)),
    }
    for relative, schema in build_schemas().items():
        documents[relative] = canonical_json(schema)
    return documents


def build_runtime_asset_manifest_for(root: str) -> Mapping[str, object]:
    """The manifest, for the generator. Deterministic given the same tree.

    Included in the committed comparison on purpose: the checksums it records
    change exactly when a sealed artifact changes, which is a difference
    somebody should have to look at.
    """
    from pgx.deployment.runtime_assets import build_runtime_asset_manifest

    return build_runtime_asset_manifest(root)
