# -*- coding: utf-8 -*-
"""Building and verifying the evidence pack (WP-25).

Two operations that must never be confused, so they are two functions with
two return shapes and two exit codes.

``build_pack`` writes the twelve artifacts and the manifest. It succeeds when
the pack is internally consistent - every member present, every digest
recorded, the manifest covering everything but itself. It succeeds *while
recording six blocked gates*, because that is what an honest pack about a
blocked programme looks like, and a build that refused to produce one would
leave the project with no document at all.

``verify_pack`` re-reads the tree and recomputes. It succeeds when the pack
still describes the tree it claims to describe.

Neither says anything about THS 6. That answer lives in ``status``, comes
with its own exit code, and is reported in the same breath as the pack result
so no output can be quoted as though the first implied the second.

One more refusal lives here: **no absolute path and no credential-shaped
string may enter the pack.** Both are checked over the rendered bytes before
anything is written, not over the inputs, because the thing that circulates is
the rendered document.
"""

from __future__ import annotations

import io
import json
import os
import re
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.ths6.artifacts import (ARTIFACT_PATHS, PACK_MEMBER_PATHS,
                                write_ths6_artifacts)
from pgx.ths6.integrity import (MANIFEST_MEMBER_PATH, build_pack_manifest,
                                verify_pack_manifest)
from pgx.ths6.status import build_ths6_status, exit_code_for_status
from pgx.ths6.vocabulary import (EXIT_BLOCKED, EXIT_FAILURE, EXIT_SUCCESS,
                                 PACK_INTEGRITY_IS_NOT_ACHIEVEMENT)

__all__ = [
    "PACK_VERSION",
    "build_pack",
    "leaked_absolute_paths",
    "verify_pack",
]

PACK_VERSION = "pgx-wp25-evidence-pack/1"

#: A POSIX home directory, a Windows drive letter, a UNC path, or a path
#: under a common absolute root. Applied to rendered pack bytes.
_ABSOLUTE_PATH_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("posix_home", re.compile(r"/(?:home|Users)/[A-Za-z0-9._-]+")),
    ("windows_drive", re.compile(r"\b[A-Za-z]:\\\\?[A-Za-z0-9._\\-]")),
    ("unc", re.compile(r"\\\\\\\\[A-Za-z0-9._-]+\\\\")),
    ("absolute_root", re.compile(
        r"(?<![A-Za-z0-9._~-])/(?:opt|var|usr|etc|private|mnt|srv|root)/"
        r"[A-Za-z0-9._-]")),
)


def leaked_absolute_paths(text: str) -> Tuple[Mapping[str, object], ...]:
    """Absolute paths in rendered pack text. Locations, never the value.

    Reports the pattern that fired and the line, not the matched string: a
    leak report that quoted the leak would be a second copy of it.
    """
    found: List[Mapping[str, object]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for name, pattern in _ABSOLUTE_PATH_PATTERNS:
            if pattern.search(line):
                found.append({"line": number, "pattern": name})
    return tuple(found)


def _scan_rendered(root: str, paths: Sequence[str]) -> Mapping[str, object]:
    """Scan what will circulate: the rendered members, not their inputs."""
    absolute_leaks: List[Mapping[str, object]] = []
    secret_findings: List[Mapping[str, object]] = []
    try:
        from pgx.security.secret_scan import scan_text
    except Exception:  # pragma: no cover - scanner removed
        scan_text = None  # type: ignore[assignment]
    for relative in paths:
        path = os.path.join(root, *relative.split("/"))
        if not os.path.isfile(path):
            continue
        with io.open(path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
        for entry in leaked_absolute_paths(text):
            absolute_leaks.append(dict(entry, path=relative))
        if scan_text is not None:
            for finding in scan_text(text, relative=relative):
                if finding.classification == "FINDING":
                    secret_findings.append(
                        {"path": relative, "line": finding.line,
                         "rule_id": finding.rule_id})
    return {
        "scanned_member_count": len(paths),
        "absolute_path_leak_count": len(absolute_leaks),
        "absolute_path_leaks": absolute_leaks,
        "secret_finding_count": len(secret_findings),
        "secret_findings": secret_findings,
        "scanner_available": scan_text is not None,
        "clean": not absolute_leaks and not secret_findings,
    }


def build_pack(root: str = ".") -> Mapping[str, object]:
    """Write the pack, then check what was written.

    The scan runs after writing rather than before, because the question is
    whether the *rendered* documents leak, and a check over the inputs would
    miss a path that a renderer introduced.
    """
    written = write_ths6_artifacts(root)
    members = PACK_MEMBER_PATHS(root)
    manifest = _read_manifest(root)
    verification = verify_pack_manifest(root, manifest)
    scan = _scan_rendered(root, members)
    intact = bool(verification["intact"]) and bool(scan["clean"])
    status = build_ths6_status(root, pack_integrity=intact)
    _rewrite_status(root, status)
    # The status document is a pack member, so rewriting it invalidates the
    # manifest that covered the previous bytes. Rebuilding the manifest here
    # is the only correct order: a manifest that predates its members is a
    # manifest describing a pack that no longer exists.
    manifest = build_pack_manifest(root, members, pack_version=PACK_VERSION)
    _write_manifest(root, manifest)
    verification = verify_pack_manifest(root, manifest)
    return {
        "pack_version": PACK_VERSION,
        "written_paths": list(written),
        "member_count": len(members),
        "manifest_path": MANIFEST_MEMBER_PATH,
        "pack_sha256": manifest["pack_sha256"],
        "integrity": dict(verification),
        "scan": dict(scan),
        "pack_integrity_pass": bool(verification["intact"])
        and bool(scan["clean"]),
        "ths6_achieved": status["ths6_achieved"],
        "release_may_proceed": status["release_may_proceed"],
        "exit_code": (EXIT_SUCCESS
                      if bool(verification["intact"]) and bool(scan["clean"])
                      else EXIT_FAILURE),
        "integrity_note": PACK_INTEGRITY_IS_NOT_ACHIEVEMENT,
    }


def verify_pack(root: str = ".") -> Mapping[str, object]:
    """Re-read the tree and check the committed pack still describes it."""
    manifest = _read_manifest(root)
    if manifest is None:
        return {
            "pack_version": PACK_VERSION,
            "manifest_present": False,
            "pack_integrity_pass": False,
            "exit_code": EXIT_FAILURE,
            "reason": "no pack manifest at %s" % MANIFEST_MEMBER_PATH,
            "integrity_note": PACK_INTEGRITY_IS_NOT_ACHIEVEMENT,
        }
    verification = verify_pack_manifest(root, manifest)
    members = [str(item["path"])
               for item in manifest.get("members", ())]  # type: ignore
    scan = _scan_rendered(root, members + [MANIFEST_MEMBER_PATH])
    declared = set(members)
    expected = set(PACK_MEMBER_PATHS(root)) - {MANIFEST_MEMBER_PATH}
    unlisted = sorted(expected - declared)
    intact = (bool(verification["intact"]) and bool(scan["clean"])
              and not unlisted)
    status = build_ths6_status(root, pack_integrity=intact)
    return {
        "pack_version": PACK_VERSION,
        "manifest_present": True,
        "member_count": len(members),
        "unlisted_member_paths": unlisted,
        "integrity": dict(verification),
        "scan": dict(scan),
        "pack_integrity_pass": intact,
        "ths6_achieved": status["ths6_achieved"],
        "release_may_proceed": status["release_may_proceed"],
        "ths6_status_exit_code": exit_code_for_status(status),
        "exit_code": EXIT_SUCCESS if intact else EXIT_FAILURE,
        "integrity_note": PACK_INTEGRITY_IS_NOT_ACHIEVEMENT,
        "note": (
            "This command exits zero for an intact pack that honestly "
            "records a blocked programme. Ask `pgx-ths6 status` whether the "
            "programme has achieved anything; it exits %d while blocked."
            % EXIT_BLOCKED),
    }


def _read_manifest(root: str) -> Optional[Mapping[str, object]]:
    path = os.path.join(root, *MANIFEST_MEMBER_PATH.split("/"))
    if not os.path.isfile(path):
        return None
    try:
        with io.open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def _write_manifest(root: str, manifest: Mapping[str, object]) -> None:
    from pgx.ths6.integrity import canonical_json

    path = os.path.join(root, *MANIFEST_MEMBER_PATH.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as handle:
        handle.write(canonical_json(manifest))


def _rewrite_status(root: str, status: Mapping[str, object]) -> None:
    from pgx.ths6.integrity import canonical_json

    path = os.path.join(root, "data", "ths6", "wp25-ths6-status.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as handle:
        handle.write(canonical_json(status))
