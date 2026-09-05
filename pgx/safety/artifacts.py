# -*- coding: utf-8 -*-
"""Writing the WP-20 artifacts, and refusing to write the wrong ones.

Two rules this module exists to enforce:

**An incomplete run is never written as evidence.** ``--write`` records a
result only after every invariant has been processed. A build that died halfway
must not leave a passing artifact behind, and - more importantly - must not
leave *yesterday's* passing artifact behind either. So a failed or incomplete
run **replaces** the execution record with the failure rather than declining to
touch it.

**Nothing machine-specific, secret or clinical reaches a committed file.**
Every document goes through WP-19's scrubber, which rewrites the repository
root, home and temporary directories and then refuses anything still matching a
host path, a credential, or a clinical payload field. Refused, not edited: a
document with text quietly removed from it is no longer the evidence it claims
to be.
"""

from __future__ import annotations

import io
import json
import os
from typing import Any, Dict, Mapping, Tuple

from pgx.safety.controls import CONTROL_CATALOGUE_VERSION, NEGATIVE_CONTROLS
from pgx.safety.errors import GateRefusal
from pgx.safety.execution import SafetyExecution
from pgx.safety.registry import SafetyRegistry
from pgx.safety.vocabulary import REGISTRY_VERSION

__all__ = [
    "REGISTRY_PATH",
    "CONTROLS_PATH",
    "EXECUTION_PATH",
    "REPORT_PATH",
    "DETERMINISTIC_ARTIFACT_PATHS",
    "ARTIFACT_PATHS",
    "build_registry_document",
    "build_controls_document",
    "build_artifacts",
    "write_artifacts",
    "write_document",
]

REGISTRY_PATH = "data/safety/wp20-invariant-registry.json"
CONTROLS_PATH = "data/safety/wp20-negative-controls.json"
EXECUTION_PATH = "data/safety/wp20-safety-execution.json"
REPORT_PATH = "data/safety/wp20-safety-report.json"

#: Built from the repository alone, so a fresh build must equal the committed
#: bytes. WP-19's reproducibility check consumes exactly this tuple.
DETERMINISTIC_ARTIFACT_PATHS: Tuple[str, ...] = (REGISTRY_PATH, CONTROLS_PATH)

#: Every path this module owns, including the ones a run writes.
ARTIFACT_PATHS: Tuple[str, ...] = DETERMINISTIC_ARTIFACT_PATHS + (
    EXECUTION_PATH, REPORT_PATH)


def _render(document: Mapping[str, Any], root: str) -> str:
    """Scrub, render canonically, refuse if anything survived.

    Reuses ``pgx.verification.scrub`` rather than reimplementing it: two
    scrubbers with different pattern lists would eventually disagree about what
    is safe to commit, and the weaker one would win by being the one somebody
    called.
    """
    from pgx.verification.scrub import safe_render
    return safe_render(document, root)


def build_registry_document(registry: SafetyRegistry) -> Dict[str, Any]:
    """The committed registry. A function of the definitions and nothing else."""
    document = dict(registry.as_document())
    document["note"] = (
        "The authoritative machine-readable form of section 2 of "
        "docs/risk-management/safety-contract.md. Twelve invariants, not ten: "
        "the architecture asks for at least SAFETY-INV-010, and a registry "
        "that stopped there would drop real-patient-data and determinism. "
        "Every selector is resolved against live test discovery on each run, "
        "so a row whose tests were renamed empties itself and the emptiness is "
        "the finding.")
    return document


def build_controls_document() -> Dict[str, Any]:
    """The committed negative-control catalogue."""
    return {
        "control_catalogue_version": CONTROL_CATALOGUE_VERSION,
        "control_count": len(NEGATIVE_CONTROLS),
        "controls": [control.as_document() for control in NEGATIVE_CONTROLS],
        "note": "Each control is a deliberately unsafe case that the same "
                "evaluator judging the real system must reject with the named "
                "code. Asserting that a fixture contains unsafe text proves "
                "something about the fixture and nothing about the detector. "
                "Every fixture is in-memory; none modifies production source.",
    }


def build_artifacts(root: str) -> Dict[str, str]:
    """Every deterministic artifact, rendered.

    The signature every generator in this repository shares, so WP-19's
    reproducibility checker can build it twice and compare without knowing
    anything about what is inside.
    """
    from pgx.application.safety_schema import build_schemas
    from pgx.safety.registry import load_registry

    registry = load_registry(root)
    documents: Dict[str, str] = {
        REGISTRY_PATH: _render(build_registry_document(registry), root),
        CONTROLS_PATH: _render(build_controls_document(), root),
    }
    for relative, schema in build_schemas().items():
        documents[relative] = _render(schema, root)
    return documents


def write_document(root: str, relative: str,
                   document: Mapping[str, Any]) -> str:
    """Scrub, render and write one document."""
    rendered = _render(document, root)
    path = os.path.join(root, *relative.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as handle:
        handle.write(rendered)
    return rendered


def write_artifacts(root: str) -> Dict[str, str]:
    """Write every deterministic artifact under ``root``."""
    written: Dict[str, str] = {}
    for relative, rendered in sorted(build_artifacts(root).items()):
        path = os.path.join(root, *relative.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write(rendered)
        written[relative] = rendered
    return written


def write_execution(root: str, execution: SafetyExecution,
                    report: Mapping[str, Any]) -> Dict[str, str]:
    """Record one run. Refuses an incomplete one.

    A run that did not finish has not verified anything, and writing it would
    put a document that *looks* like evidence where evidence belongs.
    """
    if not execution.complete:
        raise GateRefusal(
            "refusing to write safety evidence from an incomplete run; an "
            "interrupted build must not leave a passing artifact behind")
    return {
        EXECUTION_PATH: write_document(root, EXECUTION_PATH,
                                       execution.as_document()),
        REPORT_PATH: write_document(root, REPORT_PATH, report),
    }


def invalidate_execution(root: str, reason: str) -> str:
    """Replace a previous success with an explicit failure record.

    Called when a run fails or is interrupted. Leaving the earlier artifact in
    place would let a failed build inherit a passing gate, which is the single
    most dangerous thing this package could do.
    """
    document = {
        "complete": False,
        "environment": {},
        "inputs": {},
        "invariants": [],
        "invalidated": True,
        "invalidation_reason": reason,
        "note": "A previous successful run was invalidated. Safety evidence "
                "is replaced by failure rather than left standing, so an "
                "interrupted or failing build cannot inherit an earlier PASS.",
    }
    return write_document(root, EXECUTION_PATH, document)
