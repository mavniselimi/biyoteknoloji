# -*- coding: utf-8 -*-
"""The record that a verification run actually happened.

A gate status is only as good as the run behind it. Without a record, the two
available options are both bad: report the last known result, which may be
months old and about different code, or report nothing and make the whole gate
useless.

So a run writes evidence, and the evidence carries enough to be *disqualified*:

**What was verified.** A digest over every source and test file. Change a line
in ``pgx/engine`` and the recorded digest no longer matches; the evidence is
``STALE`` and the gate says so instead of quoting a result about the old code.

**Where it ran.** Interpreter, platform, architecture, and the versions of the
packages the run depended on. An attestation does not travel between machines:
a run on Linux says nothing about macOS, and a run with ``psycopg`` absent says
nothing about a machine that has it.

Deliberately *not* recorded: hostname, username, or any absolute path. The
question is "is this the same kind of machine running the same stack", not
"whose machine is this", and the second belongs in nobody's repository. Every
document written through ``scrub.safe_render`` is checked for those anyway.

This mirrors ``apps/api/runtime_verification.py``, which does the same job for
the WP-16 ASGI evidence, on purpose: two mechanisms with different staleness
rules would eventually disagree, and a reader would have to learn both.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

__all__ = [
    "RUN_EVIDENCE_SCHEMA_VERSION",
    "RUN_EVIDENCE_PATH",
    "NO_EVIDENCE",
    "STALE",
    "RUN_FAILED",
    "VERIFIED",
    "FINGERPRINTED_TREES",
    "input_fingerprints",
    "host_fingerprint",
    "load_run_evidence",
    "run_evidence_freshness",
]

RUN_EVIDENCE_SCHEMA_VERSION = "pgx-wp19-verification-run/1"

#: Where a recorded run lives. Read by the gate status, written by the CLI.
RUN_EVIDENCE_PATH = "data/verification/wp19-verification-run.json"

#: The four states a record can be in. ``NO_EVIDENCE`` and ``STALE`` are spelled
#: as the words the gate status prints, so no caller has to translate.
VERIFIED = "VERIFIED"
NO_EVIDENCE = "BLOCKED"
RUN_FAILED = "RUN_FAILED"
STALE = "STALE_EVIDENCE_REJECTED"

#: The trees whose contents decide whether a run is still about this code.
#: ``tests`` is in the list for the obvious reason and ``pgx``/``apps`` for the
#: less obvious one: a run that passed against different application code is
#: not evidence about this application code, however green it was.
FINGERPRINTED_TREES: Tuple[str, ...] = ("pgx", "apps", "tests")

#: Packages whose presence changes what the suite can execute. Recorded so that
#: a run made without ``psycopg`` cannot be quoted on a machine that has it.
_RELEVANT_PACKAGES: Tuple[str, ...] = (
    "coverage", "fastapi", "httpx", "jinja2", "lxml", "playwright",
    "psycopg", "pydantic", "sqlalchemy", "starlette", "uvicorn",
)


def _tree_digest(root: str, tree: str) -> str:
    """A digest over every ``.py`` file under ``tree``, path included.

    Paths are relative and are hashed alongside the content, so moving a file
    changes the digest even when no byte of it changed - a moved test is a
    different suite.
    """
    digest = hashlib.sha256()
    base = os.path.join(root, tree)
    if not os.path.isdir(base):
        return digest.hexdigest()
    for current, directories, files in os.walk(base):
        directories[:] = sorted(name for name in directories
                                if name != "__pycache__")
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = os.path.join(current, name)
            relative = os.path.relpath(path, root).replace(os.sep, "/")
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            with io.open(path, "rb") as handle:
                digest.update(hashlib.sha256(handle.read()).digest())
    return digest.hexdigest()


def input_fingerprints(root: str) -> Dict[str, str]:
    """One digest per fingerprinted tree, plus one over all of them."""
    found = {"%s_sha256" % tree: _tree_digest(root, tree)
             for tree in FINGERPRINTED_TREES}
    combined = hashlib.sha256()
    for key in sorted(found):
        combined.update(key.encode("utf-8"))
        combined.update(found[key].encode("utf-8"))
    found["combined_sha256"] = combined.hexdigest()
    return found


def _package_versions() -> Dict[str, Optional[str]]:
    import importlib
    found: Dict[str, Optional[str]] = {}
    for name in _RELEVANT_PACKAGES:
        try:
            module = importlib.import_module(name)
        except Exception:
            found[name] = None
            continue
        found[name] = getattr(module, "__version__", "present")
    return found


def host_fingerprint() -> Dict[str, Any]:
    """What "this host" means for the purpose of accepting a run.

    Interpreter, platform, architecture and the package versions the run
    depended on. Never a hostname, a username, a MAC address or a path.
    """
    return {
        "implementation": platform.python_implementation(),
        "machine": platform.machine(),
        "packages": _package_versions(),
        "python": "%d.%d.%d" % sys.version_info[:3],
        "system": platform.system(),
    }


def load_run_evidence(root: str,
                      path: str = RUN_EVIDENCE_PATH
                      ) -> Optional[Mapping[str, Any]]:
    """The recorded run, or ``None`` when there is not one.

    Never raises on a malformed file: an unreadable record is the same as no
    record for every decision made from it, and a gate status that crashed
    because somebody hand-edited a JSON file would be worse than one that
    reports BLOCKED.
    """
    full = os.path.join(root, *path.split("/"))
    if not os.path.exists(full):
        return None
    try:
        with io.open(full, "r", encoding="utf-8") as handle:
            document = json.load(handle)
    except (ValueError, OSError):
        return None
    return document if isinstance(document, dict) else None


def run_evidence_freshness(evidence: Optional[Mapping[str, Any]],
                           root: str) -> Tuple[str, str]:
    """Classify a record: ``(status, reason)``. Never raises.

    The checks are in the order a reader would ask them: is there a record, is
    it a record of this kind, did the run pass, was it made here, and is it
    still about this code.
    """
    if evidence is None:
        return NO_EVIDENCE, (
            "no verification run has been recorded; run "
            "`python -m pgx.application.verification_cli run "
            "--profile full --write`")
    if evidence.get("schema_version") != RUN_EVIDENCE_SCHEMA_VERSION:
        return STALE, ("the recorded run was written against schema %r, not %r"
                       % (evidence.get("schema_version"),
                          RUN_EVIDENCE_SCHEMA_VERSION))
    if not evidence.get("passed"):
        codes = list(evidence.get("issue_codes") or ())
        return RUN_FAILED, ("the recorded verification run did not pass: %s"
                            % (", ".join(sorted(codes)) or "unspecified"))

    recorded_host = evidence.get("environment") or {}
    current_host = host_fingerprint()
    if recorded_host != current_host:
        return STALE, (
            "the run was recorded on a different host or stack (%s/%s %s) "
            "than this one (%s/%s %s); a verification result does not travel "
            "between machines"
            % (recorded_host.get("system"),
               recorded_host.get("implementation"),
               recorded_host.get("python"), current_host["system"],
               current_host["implementation"], current_host["python"]))

    recorded_inputs = evidence.get("inputs") or {}
    current_inputs = input_fingerprints(root)
    changed: List[str] = [key for key in sorted(current_inputs)
                          if recorded_inputs.get(key) != current_inputs[key]]
    if changed:
        return STALE, (
            "the source or test tree changed after the run was recorded (%s); "
            "the recorded result is about different code"
            % ", ".join(name.replace("_sha256", "") for name in changed
                        if name != "combined_sha256") or "combined digest")
    return VERIFIED, ""
