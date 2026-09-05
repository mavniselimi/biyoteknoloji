# -*- coding: utf-8 -*-
"""Building the documents WP-19 commits.

Three of these are deterministic - the inventory, the requirement matrix and
the profile registry are functions of the repository and nothing else, so a
fresh build must match the committed bytes, and ``reproducibility`` checks that
it does. The rest record an execution or an environment and are written by the
run that produced them.

The inventory is committed at *module* granularity. Per-test rows with every
field repeated come to eight hundred kilobytes of near-identical JSON, and
listing five thousand test names that are re-derivable in a second is bulk
rather than evidence.

What is committed instead is a count and a digest: ``test_count`` and
``test_id_sha256``, the latter taken over the sorted identifiers in that module.
That keeps the property the identifiers were there for - a test added, removed
or renamed changes the digest, so the committed artifact goes stale and says so
- without the bulk. The names themselves are one command away:
``pgx-verify inventory --by-test``.

Every document goes through ``scrub.safe_render``, which rewrites machine
paths, refuses credentials and clinical payload fields, and renders with the
same canonical settings the rest of the project uses: two-space indent, sorted
keys, ASCII, one trailing newline.
"""

from __future__ import annotations

import io
import os
import hashlib
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.verification.discovery import Discovery
from pgx.verification.inventory import CATEGORY_RULES, Inventory
from pgx.verification.matrix import Matrix
from pgx.verification.model import PLAN_SCHEMA_VERSION, TestEntry
from pgx.verification.profiles import PROFILE_REGISTRY_VERSION, PROFILES
from pgx.verification.requirements import REQUIREMENT_REGISTRY_VERSION
from pgx.verification.results import STDOUT_IS_NOT_A_RESULT, KNOWN_STDOUT_MARKERS
from pgx.verification.scrub import safe_render

__all__ = [
    "ARTIFACT_PATHS",
    "test_id_digest",
    "DETERMINISTIC_ARTIFACT_PATHS",
    "INVENTORY_PATH",
    "MATRIX_PATH",
    "PROFILES_PATH",
    "COVERAGE_PATH",
    "REPRODUCIBILITY_PATH",
    "build_inventory_document",
    "build_matrix_document",
    "build_profiles_document",
    "build_artifacts",
    "write_artifacts",
    "write_document",
]

INVENTORY_PATH = "data/verification/wp19-test-inventory.json"
MATRIX_PATH = "data/verification/wp19-requirement-matrix.json"
PROFILES_PATH = "data/verification/wp19-verification-profiles.json"
COVERAGE_PATH = "data/verification/wp19-coverage-summary.json"
REPRODUCIBILITY_PATH = "data/verification/wp19-reproducibility-report.json"

#: Built from the repository alone, so a fresh build must equal the committed
#: bytes. ``reproducibility.check_generators`` relies on exactly this.
DETERMINISTIC_ARTIFACT_PATHS: Tuple[str, ...] = (
    INVENTORY_PATH, MATRIX_PATH, PROFILES_PATH,
)

#: Every path this module owns, including the ones a run writes.
ARTIFACT_PATHS: Tuple[str, ...] = DETERMINISTIC_ARTIFACT_PATHS + (
    COVERAGE_PATH, REPRODUCIBILITY_PATH,
)


def test_id_digest(test_ids: Sequence[str]) -> str:
    """A digest over sorted test identifiers.

    The committed artifact's substitute for listing them. Sorted first, so the
    digest is a property of the set rather than of the order a loader happened
    to walk a directory in.
    """
    digest = hashlib.sha256()
    for identifier in sorted(test_ids):
        digest.update(identifier.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _module_rows(inventory: Inventory) -> List[Dict[str, Any]]:
    """One row per test module.

    Fields that are constant within a module - category, owning work package,
    criticality, skip policy - are written once, and the tests themselves are
    represented by a count and a digest over their sorted identifiers.
    """
    grouped: Dict[str, List[TestEntry]] = {}
    for entry in inventory.entries:
        grouped.setdefault(entry.module, []).append(entry)

    rows: List[Dict[str, Any]] = []
    for module in sorted(grouped):
        entries = sorted(grouped[module], key=lambda item: item.test_id)
        first = entries[0]
        rows.append({
            "assigned_by": first.assigned_by,
            "category": first.category.value,
            "command": first.command,
            "criticality": first.criticality.value,
            "dependencies": list(first.dependencies),
            "evidence": list(first.evidence),
            "module": module,
            "offline": first.offline,
            "permitted_skip_reasons": list(first.permitted_skip_reasons),
            "requirements": list(first.requirements),
            "safety_invariants": list(first.safety_invariants),
            "skip_policy": first.skip_policy.value,
            "suite_id": module,
            "synthetic_fixtures": first.synthetic_fixtures,
            "test_count": len(entries),
            "test_id_sha256": test_id_digest(
                [item.test_id for item in entries]),
            "work_package": first.work_package,
        })
    return rows


def build_inventory_document(discovery: Discovery,
                             inventory: Inventory) -> Dict[str, Any]:
    """The committed inventory. A function of the tree and nothing else."""
    rows = _module_rows(inventory)
    return {
        "category_rule_count": len(CATEGORY_RULES),
        "discovered_test_count": discovery.count,
        "inventoried_test_count": inventory.count,
        "load_failures": [{"module": module, "detail": detail}
                          for module, detail in discovery.load_failures],
        "note": "Discovered by unittest's own loader, so this inventory and "
                "the suite that runs are the same enumeration. A test that "
                "matches no category rule is refused rather than defaulted, "
                "so an uncategorised package fails the build instead of "
                "quietly becoming UNIT.",
        "pattern": discovery.pattern,
        "plan_schema_version": PLAN_SCHEMA_VERSION,
        "requirement_registry_version": REQUIREMENT_REGISTRY_VERSION,
        "start_directory": discovery.start_directory,
        "stdout_note": STDOUT_IS_NOT_A_RESULT,
        "known_stdout_markers": list(KNOWN_STDOUT_MARKERS),
        "suite_count": len(rows),
        "suites": rows,
        "unmapped_modules": list(inventory.unmapped),
    }


def build_matrix_document(matrix: Matrix) -> Dict[str, Any]:
    """The committed requirement/test matrix."""
    document = dict(matrix.as_document())
    document["requirement_registry_version"] = REQUIREMENT_REGISTRY_VERSION
    return document


def build_profiles_document() -> Dict[str, Any]:
    """The committed profile registry, so a CI job can read it rather than
    hard-code a list of profile names it believes exist."""
    return {
        "note": "A profile is a selection plus a contract. `minimum_tests` is "
                "the floor below which a run is an ERROR rather than a pass: a "
                "selector that stops matching would otherwise turn a profile "
                "green in two seconds.",
        "profile_registry_version": PROFILE_REGISTRY_VERSION,
        "profiles": [profile.as_document() for profile in PROFILES],
    }


def build_artifacts(root: str) -> Dict[str, str]:
    """Every deterministic artifact, rendered.

    The signature every generator in this repository shares: a mapping of
    relative path to rendered text, which ``reproducibility`` can build twice
    and compare without knowing anything about what is inside.

    The published schemas are built here rather than by a separate command, so
    that a schema and the document it describes cannot be regenerated
    independently and drift.
    """
    from pgx.application.verification_schema import build_schemas
    from pgx.verification.discovery import discover
    from pgx.verification.inventory import build_inventory
    from pgx.verification.matrix import build_matrix

    discovery = discover(root)
    inventory = build_inventory(discovery)
    matrix = build_matrix(inventory)
    documents: Dict[str, str] = {
        INVENTORY_PATH: safe_render(
            build_inventory_document(discovery, inventory), root),
        MATRIX_PATH: safe_render(build_matrix_document(matrix), root),
        PROFILES_PATH: safe_render(build_profiles_document(), root),
    }
    for relative, schema in build_schemas().items():
        documents[relative] = safe_render(schema, root)
    return documents


def write_document(root: str, relative: str, document: Mapping[str, Any]
                   ) -> str:
    """Scrub, render and write one document. Returns the rendered text."""
    rendered = safe_render(document, root)
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
