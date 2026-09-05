# -*- coding: utf-8 -*-
"""Deterministic artifact serialisation (WP-11).

Every byte a ruleset artifact contains is written through this module, so
"deterministic" is a property of one place rather than a habit spread across
callers.

The conventions, and why each one matters:

* **UTF-8, sorted keys, fixed separators.** Two processes serialising the same
  data must produce the same bytes; anything else makes a checksum a statement
  about the machine rather than the content.
* **``ensure_ascii=False``.** The curated text this project handles is Turkish
  and English. Escaping non-ASCII would still be deterministic, but it would
  make the artifact unreadable to the people who have to review it, and a
  reviewer who cannot read the artifact is not reviewing it.
* **``\n`` newlines, always.** Written explicitly rather than left to the
  platform, so a build on Windows and a build on Linux agree.
* **A trailing newline on every file.** POSIX text convention, and it keeps
  ``sha256sum -c`` and ordinary diff tools well-behaved.

Publication is atomic: files are written into a temporary directory beside the
destination and moved into place only after every one of them verified. An
interrupted build therefore leaves no partial artifact for anything to load,
which matters because a half-written ruleset is exactly the kind of thing that
loads successfully and produces findings nobody can account for.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import tempfile
from typing import Any, Dict, Iterable, Mapping, Sequence, Tuple

from pgx.rules.errors import ArtifactIntegrityError, FrozenArtifactExistsError

__all__ = [
    "ARTIFACT_FILES",
    "CHECKSUM_FILE",
    "canonical_bytes",
    "canonical_ndjson_bytes",
    "digest_of",
    "publish_atomically",
    "verify_checksums",
    "write_checksum_file",
]

#: The files every frozen ruleset artifact contains, in the order a reader
#: should meet them. Declared as data so the builder, the verifier, the schema
#: and the tests agree on what "complete" means.
ARTIFACT_FILES: Tuple[str, ...] = (
    "manifest.json",
    "rules.ndjson",
    "approval-list.json",
    "build-log.json",
)

CHECKSUM_FILE = "checksums.sha256"

_SEPARATORS = (",", ":")


def canonical_bytes(payload: Any) -> bytes:
    """Canonical JSON bytes for one document."""
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=_SEPARATORS, indent=2) + "\n"
    return text.encode("utf-8")


def canonical_ndjson_bytes(rows: Sequence[Any]) -> bytes:
    """Canonical NDJSON bytes: one document per line, no indentation.

    The caller has already ordered ``rows``. Sorting here would hide a
    non-deterministic caller rather than fix one, and the build is the place
    where member order is decided and recorded.
    """
    buffer = io.StringIO()
    for row in rows:
        buffer.write(json.dumps(row, ensure_ascii=False, sort_keys=True,
                                separators=_SEPARATORS))
        buffer.write("\n")
    return buffer.getvalue().encode("utf-8")


def digest_of(payload: bytes) -> str:
    """``sha256:<hex>`` of raw bytes."""
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def write_checksum_file(files: Mapping[str, bytes]) -> bytes:
    """A ``sha256sum``-compatible checksum file over the artifact's files.

    Sorted by name so the file itself is deterministic, and in the plain
    ``<hex>  <name>`` format so an operator can verify the artifact with
    ``sha256sum -c`` and no project tooling at all. An artifact only this
    project can check is an artifact nobody else will.
    """
    lines = []
    for name in sorted(files):
        lines.append("%s  %s\n" % (
            hashlib.sha256(files[name]).hexdigest(), name))
    return "".join(lines).encode("utf-8")


def verify_checksums(directory: str) -> Dict[str, str]:
    """Verify every file against the artifact's checksum file.

    Fails closed and specifically: a missing checksum file, a missing member, a
    changed byte and an unexpected extra file are four different problems and
    are reported as four different messages.
    """
    checksum_path = os.path.join(directory, CHECKSUM_FILE)
    if not os.path.isfile(checksum_path):
        raise ArtifactIntegrityError(
            "no %s in %s; an artifact without a checksum file cannot be "
            "verified, and an unverifiable ruleset is not loaded"
            % (CHECKSUM_FILE, directory),
            code="ARTIFACT_CHECKSUM_FILE_MISSING")

    expected: Dict[str, str] = {}
    with io.open(checksum_path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            parts = text.split(None, 1)
            if len(parts) != 2:
                raise ArtifactIntegrityError(
                    "line %d of %s is not '<sha256>  <name>'"
                    % (number, CHECKSUM_FILE),
                    code="ARTIFACT_CHECKSUM_FILE_MALFORMED")
            expected[parts[1].strip()] = parts[0].strip()

    actual: Dict[str, str] = {}
    for name in sorted(expected):
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            raise ArtifactIntegrityError(
                "%s is listed in %s but is not present; the artifact is "
                "incomplete" % (name, CHECKSUM_FILE),
                code="ARTIFACT_MEMBER_MISSING", detail={"file": name})
        with io.open(path, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        if digest != expected[name]:
            raise ArtifactIntegrityError(
                "%s does not match its recorded checksum: expected %s, found "
                "%s. The artifact was altered after it was frozen."
                % (name, expected[name][:16], digest[:16]),
                code="ARTIFACT_CHECKSUM_MISMATCH",
                detail={"file": name, "expected": expected[name],
                        "actual": digest})
        actual[name] = "sha256:" + digest

    present = {name for name in os.listdir(directory)
               if os.path.isfile(os.path.join(directory, name))}
    unexpected = sorted(present - set(expected) - {CHECKSUM_FILE})
    if unexpected:
        raise ArtifactIntegrityError(
            "%s contains file(s) the checksum file does not list: %s. An "
            "unlisted file in a frozen artifact is content nobody verified."
            % (directory, ", ".join(unexpected)),
            code="ARTIFACT_UNEXPECTED_FILE", detail={"files": unexpected})

    missing = sorted(set(ARTIFACT_FILES) - set(expected))
    if missing:
        raise ArtifactIntegrityError(
            "artifact is missing required file(s): %s" % ", ".join(missing),
            code="ARTIFACT_MEMBER_MISSING", detail={"files": missing})

    return actual


def publish_atomically(destination: str, files: Mapping[str, bytes]) -> Dict[str, str]:
    """Write an artifact into place, all at once or not at all.

    Refuses to overwrite an existing directory. A frozen ruleset is never
    rewritten: anything that cited its hash must keep resolving to what it
    cited, and a correction is a new build under a new identity.

    The staging directory is created beside the destination rather than in the
    system temporary directory, so the final ``os.replace`` is a rename within
    one filesystem - which is atomic - instead of a copy that can be
    interrupted halfway.
    """
    if os.path.exists(destination):
        raise FrozenArtifactExistsError(
            "%s already exists. A frozen ruleset is never rewritten: whatever "
            "cited its hash must keep resolving to what it cited, so a "
            "correction is a new build under a new identity." % destination)

    parent = os.path.dirname(os.path.abspath(destination)) or "."
    os.makedirs(parent, exist_ok=True)
    staging = tempfile.mkdtemp(prefix=".wp11-build-", dir=parent)
    try:
        written: Dict[str, str] = {}
        for name in sorted(files):
            path = os.path.join(staging, name)
            with io.open(path, "wb") as handle:
                handle.write(files[name])
            written[name] = digest_of(files[name])
        # Verify the staged copy before it becomes visible. Verifying after
        # publication would mean a bad artifact existed, however briefly, at
        # the path something else might read.
        verify_checksums(staging)
        os.replace(staging, destination)
        return written
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def read_artifact_files(directory: str) -> Dict[str, bytes]:
    """Read every listed artifact file after verifying the checksums."""
    verify_checksums(directory)
    contents: Dict[str, bytes] = {}
    for name in ARTIFACT_FILES:
        with io.open(os.path.join(directory, name), "rb") as handle:
            contents[name] = handle.read()
    return contents
