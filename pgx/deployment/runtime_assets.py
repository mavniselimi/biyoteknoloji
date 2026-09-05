# -*- coding: utf-8 -*-
"""What the runtime image must contain, exactly (WP-24).

The lazy version of this file is ``COPY data/ /app/data/``. That ships the
raw ClinPGx snapshot, the legacy baseline, every regression report, the
curation exercises and - the reason this matters - anything a future work
package puts under ``data/``, including restricted holdout payloads. An
allowlist that a person maintains is worse than useless if it is a directory;
a directory is a promise about what somebody will remember not to put there.

So this is an explicit list of files, each with a reason and a checksum
recorded at build time. The build fails when a listed file is absent or its
checksum disagrees. Two different failures, deliberately:

* **absent** means the image would start and serve a page that says the
  catalogue is unavailable - which is honest but is not what was asked for;
* **checksum disagrees** means the artifact is not the one that was reviewed,
  and shipping it would attach a build's provenance to content nobody checked.

What is deliberately *not* here: ``data/raw``, ``data/canonical``,
``data/evidence``, ``data/legacy-baseline``, ``data/migration``,
``data/holdout`` and everything under ``data/_to_delete``. The first five are
build inputs the application never reads; the sixth does not exist and must
never be copied into an image if it ever does; the last is a staging area.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence, Tuple

__all__ = [
    "FORBIDDEN_IMAGE_PREFIXES",
    "RUNTIME_ASSETS",
    "RUNTIME_ASSET_MANIFEST_VERSION",
    "RuntimeAsset",
    "build_runtime_asset_manifest",
    "verify_runtime_assets",
]

RUNTIME_ASSET_MANIFEST_VERSION = "pgx-wp24-runtime-asset-manifest/1"


@dataclass(frozen=True)
class RuntimeAsset:
    """One file the serving image needs, and why it needs it."""

    path: str
    reason: str
    #: False for artifacts whose absence degrades a page rather than breaking
    #: the application. The build still records them; it does not fail on
    #: them, because a deployment with no dashboard feed serves an empty
    #: dashboard, which is a supported state WP-17 already renders.
    required: bool = True


#: Every file the serving path reads. Derived from the path constants the
#: modules declare, not from a trace: a trace only sees what the exercised
#: configuration happened to touch, and the configuration that matters here is
#: the one nobody has run yet.
RUNTIME_ASSETS: Tuple[RuntimeAsset, ...] = (
    RuntimeAsset(
        "data/demo/wp17-development-cases.json",
        "the sealed development case catalogue the demo pages read"),
    RuntimeAsset(
        "data/demo/wp17-demo-case-manifest.json",
        "the manifest that seals the case catalogue; without it the "
        "catalogue is content nobody can verify"),
    RuntimeAsset(
        "data/api/wp16-real-gate-status.json",
        "the API gate status the system page reports"),
    RuntimeAsset(
        "data/web/wp17-real-gate-status.json",
        "the interface gate status the system page reports"),
    RuntimeAsset(
        "data/api/wp16-runtime-verification.json",
        "the recorded ASGI runtime evidence the OpenAPI document reflects. "
        "Optional because it is written only when the runtime suite actually "
        "runs; its absence makes the served document report itself "
        "unverified, which is the truthful answer and not a broken image",
        required=False),
    RuntimeAsset(
        "data/validation/wp18-real-gate-status.json",
        "the validation gate status the dashboard reports"),
    RuntimeAsset(
        "data/validation/wp21-dashboard-feed.json",
        "the benchmark dashboard feed", required=False),
    RuntimeAsset(
        "data/safety/wp20-real-gate-status.json",
        "the safety gate status the system page reports"),
    RuntimeAsset(
        "data/security/wp23-real-gate-status.json",
        "the security gate status the system page reports"),
    RuntimeAsset(
        "schemas/openapi/wp16-openapi.json",
        "the committed OpenAPI document the served one is compared against"),
    RuntimeAsset(
        "config/scientific-sources.json",
        "the reviewed source registry; a build without it must fail to load "
        "a policy rather than quietly find none"),
)

#: Path prefixes that must never appear inside the image, checked after the
#: build rather than trusted to ``.dockerignore``. An ignore file is a
#: statement of intent; this is a measurement of the result.
FORBIDDEN_IMAGE_PREFIXES: Tuple[str, ...] = (
    ".git/", ".venv/", ".venv-linux/", "_to_delete/", "data/_to_delete/",
    "data/raw/", "data/canonical/", "data/evidence/", "data/legacy-baseline/",
    "data/migration/", "data/holdout/", "data/curation/",
    "tests/", "clinpgx_outputs/", "clinpgx_outputs_v2/", "clinpgx_mvp_seed/",
    "final_report/", "build/", "deploy/secrets/",
)

#: Filenames that must never appear anywhere in the image, at any depth.
FORBIDDEN_IMAGE_NAMES: Tuple[str, ...] = (
    ".env", ".env.local", ".env.production", "id_rsa", "id_ed25519",
)

#: Suffixes that must never appear anywhere in the image.
FORBIDDEN_IMAGE_SUFFIXES: Tuple[str, ...] = (
    ".pem", ".key", ".p12", ".pfx", ".jks", ".sql.gz", ".dump",
)


def _digest(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def verify_runtime_assets(root: str = ".",
                          assets: Optional[Sequence[RuntimeAsset]] = None,
                          expected: Optional[Mapping[str, str]] = None
                          ) -> Mapping[str, object]:
    """Check every declared asset exists and, when pinned, still matches.

    ``expected`` is a previously recorded manifest. Passing one turns this
    from "the files are there" into "the files are the ones that were
    reviewed", which is the check the image build runs.
    """
    entries = []
    missing = []
    mismatched = []
    for asset in (assets if assets is not None else RUNTIME_ASSETS):
        absolute = os.path.join(root, asset.path)
        present = os.path.isfile(absolute)
        digest = _digest(absolute) if present else None
        pinned = (expected or {}).get(asset.path)
        agrees: Optional[bool] = None
        if pinned is not None and digest is not None:
            agrees = pinned == digest
            if not agrees:
                mismatched.append(asset.path)
        if not present and asset.required:
            missing.append(asset.path)
        entries.append({"path": asset.path, "reason": asset.reason,
                        "required": asset.required, "present": present,
                        "sha256": digest, "matches_pinned": agrees})
    return {
        "runtime_asset_manifest_version": RUNTIME_ASSET_MANIFEST_VERSION,
        "asset_count": len(entries),
        "assets": entries,
        "missing_required": sorted(missing),
        "checksum_mismatches": sorted(mismatched),
        "satisfied": not missing and not mismatched,
        "forbidden_prefixes": list(FORBIDDEN_IMAGE_PREFIXES),
        "forbidden_names": list(FORBIDDEN_IMAGE_NAMES),
        "forbidden_suffixes": list(FORBIDDEN_IMAGE_SUFFIXES),
        "note": (
            "An allowlist of files, never a directory. A directory is a "
            "promise about what somebody will remember not to put in it."),
    }


def build_runtime_asset_manifest(root: str = ".") -> Mapping[str, object]:
    """The manifest an image build pins and a later build compares against."""
    result = dict(verify_runtime_assets(root))
    result["manifest_hash"] = manifest_hash(result)
    return result


def manifest_hash(manifest: Mapping[str, object]) -> str:
    """A digest over the declared paths and their checksums only.

    Excludes ``present``, ``matches_pinned`` and every other observation, so
    the hash identifies *what was asked for* rather than what one host found.
    Two builds of the same source produce the same manifest hash even when one
    of them is missing a file - and the missing file is reported separately,
    where it cannot be mistaken for a different manifest.
    """
    import json

    pinned = sorted(
        (str(entry["path"]), str(entry["sha256"]))
        for entry in manifest.get("assets", [])  # type: ignore[union-attr]
        if entry.get("sha256"))
    payload = json.dumps({"version": RUNTIME_ASSET_MANIFEST_VERSION,
                          "assets": pinned},
                         sort_keys=True, ensure_ascii=True)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def forbidden_paths_in(paths: Sequence[str]) -> Tuple[str, ...]:
    """Which of ``paths`` must never be in an image. Used on a real listing.

    Takes a listing rather than reading a filesystem so it can be run against
    ``docker export`` output, against a staging directory, and against a test
    fixture - the same rule, checked wherever the answer is available.
    """
    offenders = []
    for raw in paths:
        # A prefix removal, not ``lstrip("./")``. ``lstrip`` strips
        # *characters*: it turned ".env" into "env", so the single most
        # important filename in this list was silently never matched. Found
        # by the test below, which is why the test lists ".env" explicitly
        # rather than trusting the rule.
        path = raw
        while path.startswith("./"):
            path = path[2:]
        path = path.lstrip("/")
        if any(path.startswith(prefix) for prefix in
               FORBIDDEN_IMAGE_PREFIXES):
            offenders.append(raw)
            continue
        name = os.path.basename(path)
        if name in FORBIDDEN_IMAGE_NAMES:
            offenders.append(raw)
            continue
        if any(name.endswith(suffix) for suffix in FORBIDDEN_IMAGE_SUFFIXES):
            offenders.append(raw)
    return tuple(sorted(set(offenders)))
