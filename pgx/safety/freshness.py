# -*- coding: utf-8 -*-
"""Binding safety evidence to the code it verified.

A recorded PASS is a statement about a particular tree at a particular moment.
Left unbound it becomes a statement about nothing: change the aggregator, and
yesterday's "SAFETY-INV-001 holds" is still sitting in the artifact looking
authoritative.

So evidence carries a fingerprint over everything the gate's answer depends on,
and a mismatch is ``STALE`` - not silently refreshed, not quietly ignored.
``STALE`` blocks a release exactly as ``FAIL`` does, because "we do not know"
and "we know it is broken" are both reasons not to ship.

What is fingerprinted, and why each one:

* ``pgx/safety`` - the registry, the evaluators, the controls. If the detector
  changed, the detection result is about a different detector.
* ``tests/unit/safety``, ``tests/safety``, ``tests/fixtures/wp20`` - the safe
  and unsafe controls themselves.
* ``pgx/domain``, ``pgx/engine``, ``pgx/reporting``, ``pgx/validation`` - the
  surfaces the invariants govern. This is the important one: a change here is
  precisely what a stale PASS would hide.
* ``schemas/wp20`` and ``data/safety`` - the published contracts and artifacts
  the gate reads.

Deliberately **not** fingerprinted: absolute paths, usernames, hostnames. The
question is "is this evidence about this code on this kind of machine", never
"whose machine is this".
"""

from __future__ import annotations

import hashlib
import io
import os
import platform
import sys
from typing import Any, Dict, List, Mapping, Optional, Tuple

__all__ = [
    "FINGERPRINTED_PATHS",
    "EVIDENCE_SCHEMA_VERSION",
    "fingerprint_inputs",
    "environment_fingerprint",
    "compare_fingerprints",
]

EVIDENCE_SCHEMA_VERSION = "pgx-wp20-safety-execution/1"

#: Each entry is ``(name, relative path, suffixes)``. Named individually rather
#: than as one digest over the repository, so a stale result says *which* input
#: moved - "the engine changed" is actionable and "something changed" is not.
FINGERPRINTED_PATHS: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    ("safety_package", "pgx/safety", (".py",)),
    ("safety_unit_tests", "tests/unit/safety", (".py",)),
    ("safety_suite", "tests/safety", (".py",)),
    ("negative_fixtures", "tests/fixtures/wp20", (".py",)),
    ("domain", "pgx/domain", (".py",)),
    ("engine", "pgx/engine", (".py",)),
    ("reporting", "pgx/reporting", (".py",)),
    ("validation", "pgx/validation", (".py",)),
    ("safety_schemas", "schemas/wp20", (".json",)),
    ("safety_artifacts", "data/safety", (".json",)),
)

#: Packages whose presence changes what the gate could execute.
_RELEVANT_PACKAGES: Tuple[str, ...] = (
    "coverage", "fastapi", "psycopg", "playwright", "pydantic",
)


def _tree_digest(root: str, relative: str,
                 suffixes: Tuple[str, ...]) -> str:
    """A digest over one tree: relative paths and contents, sorted.

    The path is hashed alongside the content, so moving a file changes the
    digest even when no byte of it did. A moved evaluator is a different
    evaluator as far as this gate is concerned.
    """
    digest = hashlib.sha256()
    base = os.path.join(root, *relative.split("/"))
    if not os.path.isdir(base):
        # An absent tree is a legitimate state - data/safety does not exist
        # before the first run - and hashes to a stable, distinguishable value.
        digest.update(b"<absent>")
        return digest.hexdigest()
    for current, directories, files in os.walk(base):
        directories[:] = sorted(name for name in directories
                                if name != "__pycache__")
        for name in sorted(files):
            if not name.endswith(suffixes):
                continue
            path = os.path.join(current, name)
            key = os.path.relpath(path, root).replace(os.sep, "/")
            digest.update(key.encode("utf-8"))
            digest.update(b"\0")
            with io.open(path, "rb") as handle:
                digest.update(hashlib.sha256(handle.read()).digest())
    return digest.hexdigest()


def fingerprint_inputs(root: str) -> Dict[str, str]:
    """One digest per fingerprinted tree, plus a combined one."""
    found = {name: _tree_digest(root, relative, suffixes)
             for name, relative, suffixes in FINGERPRINTED_PATHS}
    combined = hashlib.sha256()
    for name in sorted(found):
        combined.update(name.encode("utf-8"))
        combined.update(found[name].encode("utf-8"))
    found["combined"] = combined.hexdigest()
    return found


def environment_fingerprint() -> Dict[str, Any]:
    """Controlled environment metadata. No host, no user, no path."""
    import importlib

    packages: Dict[str, Optional[str]] = {}
    for name in _RELEVANT_PACKAGES:
        try:
            module = importlib.import_module(name)
        except Exception:
            packages[name] = None
        else:
            packages[name] = getattr(module, "__version__", "present")
    return {
        "implementation": platform.python_implementation(),
        "machine": platform.machine(),
        "packages": packages,
        "python": "%d.%d.%d" % sys.version_info[:3],
        "system": platform.system(),
    }


def compare_fingerprints(recorded: Mapping[str, Any],
                         current: Mapping[str, Any]) -> Tuple[str, ...]:
    """Which named inputs changed. Empty means the evidence is still current.

    Returns the individual names rather than only the combined digest, because
    "the engine changed" tells an operator what to look at and "the combined
    digest changed" does not.
    """
    changed: List[str] = []
    for name in sorted(set(recorded) | set(current)):
        if name == "combined":
            continue
        if recorded.get(name) != current.get(name):
            changed.append(name)
    if not changed and recorded.get("combined") != current.get("combined"):
        changed.append("combined")
    return tuple(changed)
