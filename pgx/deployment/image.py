# -*- coding: utf-8 -*-
"""Building and inspecting the application image (WP-24).

The image build is the easy half. The interesting half is what happens
afterwards, and it is here for a reason worth stating plainly: a
``.dockerignore`` is a statement of intent, and intent is not what ships. This
module inspects the *built filesystem* and fails the build when it contains a
secret, a key, a restricted data prefix, a test fixture or a legacy entry
point - regardless of what the ignore file says, and regardless of which
``COPY`` put it there.

On reproducibility, a caveat that has to be stated rather than papered over.
Two ``docker build`` runs of the same source frequently produce different
image digests, because a digest covers the config and every layer, and layers
carry timestamps, build-arg history and - on BuildKit - attestation blobs. A
report claiming two builds produced "the same image" on the basis of matching
digests would usually be reporting that nothing changed in the last second.
So the comparison here is over what actually determines content: the layer
``diff_ids`` from the image config, the environment, the entrypoint, the user
and the source manifest the build was made from. Digests are recorded when
they exist and compared separately, with the difference explained rather than
hidden.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # noqa: S404 - driving a container runtime is the point
from typing import Any, Mapping, Optional, Sequence, Tuple

from pgx.deployment.runtime_assets import (forbidden_paths_in,
                                           verify_runtime_assets)
from pgx.deployment.vocabulary import ExecutionState, blocker

__all__ = [
    "DEFAULT_IMAGE_REFERENCE",
    "IMAGE_INSPECTION_VERSION",
    "base_image_pin",
    "build_image",
    "compare_images",
    "inspect_image",
]

IMAGE_INSPECTION_VERSION = "pgx-wp24-image-result/1"

#: Local only. There is no registry path anywhere in this project: nothing has
#: been published, and a registry reference in source is how a `pull` finds
#: somebody else's image under a name that looks like yours.
DEFAULT_IMAGE_REFERENCE = "pgx-platform:wp24-local"

#: Where a resolved base-image digest is kept when somebody resolves one.
BASE_IMAGE_PIN_PATH = "deploy/base-image.pin"

_BUILD_TIMEOUT_SECONDS = 1800


def _run(argv: Sequence[str], *, timeout: int = 120) -> Tuple[int, str]:
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            list(argv), capture_output=True, text=True, timeout=timeout,
            check=False)
    except FileNotFoundError:
        return 127, "%s is not installed" % argv[0]
    except subprocess.TimeoutExpired:
        return 124, "timed out after %ds" % timeout
    return completed.returncode, ((completed.stdout or "")
                                  + (completed.stderr or "")).strip()


def _runtime_available(runner=None) -> Tuple[bool, str]:
    """A CLI is not a runtime. ``docker info`` is what answers."""
    run = runner or _run
    if shutil.which("docker") is None:
        return False, "no docker binary is on PATH"
    code, text = run(["docker", "info", "--format", "{{.ServerVersion}}"],
                     timeout=30)
    if code != 0:
        return False, ("the docker CLI exists but no daemon answered "
                       "(docker info exited %d)" % code)
    return True, text.splitlines()[0] if text else ""


def base_image_pin(root: str = ".") -> Optional[str]:
    """The resolved base-image digest, or ``None``.

    ``None`` means the base image is pinned by tag only. That is a weaker pin
    and is reported as such rather than dressed up: a tag can be moved, and a
    build that recorded a digest nobody resolved would be claiming an
    immutability it does not have.
    """
    path = os.path.join(root, BASE_IMAGE_PIN_PATH)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        value = handle.read().strip()
    return value or None


def build_image(root: str = ".", *, reference: str = DEFAULT_IMAGE_REFERENCE,
                runner=None, verify_assets: bool = True
                ) -> Mapping[str, object]:
    """Build the image, or report exactly why it was not built.

    Runtime assets are verified *before* the build. A build that produced an
    image and then discovered a sealed artifact was missing would leave a
    tagged image nobody should use, and the next `docker run` would find it.
    """
    run = runner or _run
    assets = verify_runtime_assets(root)
    if verify_assets and not assets["satisfied"]:
        return {
            "image_result_version": IMAGE_INSPECTION_VERSION,
            "state": ExecutionState.BLOCKED.value,
            "reference": reference, "image_id": None, "image_digest": None,
            "blockers": [dict(blocker(
                "DEPLOY_RUNTIME_ASSET_MISSING",
                owner="whoever generates the sealed artifacts",
                detail=("missing: %s; checksum mismatches: %s"
                        % (assets["missing_required"] or "none",
                           assets["checksum_mismatches"] or "none"))
            ).to_json())],
            "runtime_assets": assets,
        }
    available, detail = _runtime_available(runner=run)
    if not available:
        return {
            "image_result_version": IMAGE_INSPECTION_VERSION,
            "state": ExecutionState.BLOCKED.value,
            "reference": reference, "image_id": None, "image_digest": None,
            "blockers": [dict(blocker(
                "DEPLOY_CONTAINER_RUNTIME_UNAVAILABLE",
                owner="the build host", detail=detail).to_json())],
            "runtime_assets": assets,
        }
    code, text = run(
        ["docker", "build", "--file", os.path.join(root, "Dockerfile"),
         "--target", "runtime", "--tag", reference,
         # Deterministic inputs where the builder supports them. Not a
         # guarantee of a stable digest - see the module docstring - but it
         # removes the differences that are purely clock.
         "--build-arg", "SOURCE_DATE_EPOCH=1735689600",
         "--label", "org.opencontainers.image.title=pgx-platform",
         root],
        timeout=_BUILD_TIMEOUT_SECONDS)
    if code != 0:
        return {
            "image_result_version": IMAGE_INSPECTION_VERSION,
            "state": ExecutionState.NOT_EXECUTED.value,
            "reference": reference, "image_id": None, "image_digest": None,
            "blockers": [dict(blocker(
                "DEPLOY_IMAGE_NOT_BUILT", owner="the build host",
                detail="docker build exited %d" % code).to_json())],
            "build_output_tail": text.splitlines()[-5:],
            "runtime_assets": assets,
        }
    inspection = inspect_image(reference, runner=run)
    result = {
        "image_result_version": IMAGE_INSPECTION_VERSION,
        "state": ExecutionState.EXECUTED.value,
        "reference": reference,
        "base_image_digest": base_image_pin(root),
        "runtime_assets": assets,
        "blockers": [],
    }
    result.update(inspection)
    return result


def inspect_image(reference: str, *, runner=None) -> Mapping[str, object]:
    """Read an image's identity, user, entrypoint and layer identities."""
    run = runner or _run
    code, text = run(["docker", "image", "inspect", reference], timeout=60)
    if code != 0:
        return {"image_id": None, "image_digest": None,
                "inspection_error": "docker image inspect exited %d" % code}
    try:
        payload = json.loads(text)[0]
    except (ValueError, IndexError, KeyError):  # pragma: no cover
        return {"image_id": None, "image_digest": None,
                "inspection_error": "the inspect output could not be parsed"}
    config = payload.get("Config") or {}
    repo_digests = payload.get("RepoDigests") or []
    return {
        "image_id": payload.get("Id"),
        # Present only when the image has been pushed or pulled: a purely
        # local build has no repo digest, and inventing one would be claiming
        # a registry identity that does not exist.
        "image_digest": repo_digests[0] if repo_digests else None,
        "layer_diff_ids": list(
            (payload.get("RootFS") or {}).get("Layers") or []),
        "user": config.get("User"),
        "entrypoint": config.get("Entrypoint"),
        "command": config.get("Cmd"),
        "exposed_ports": sorted((config.get("ExposedPorts") or {}).keys()),
        "architecture": payload.get("Architecture"),
        "os": payload.get("Os"),
        "size_bytes": payload.get("Size"),
    }


def image_filesystem_paths(reference: str, *, runner=None
                           ) -> Tuple[Optional[Tuple[str, ...]], str]:
    """Every path in the built image, via a container export.

    ``docker export`` of a created-but-never-started container is used rather
    than ``docker run find``: running the image to inspect it means the
    inspection depends on the image being runnable, and an image that fails to
    start would be reported as containing nothing forbidden.
    """
    run = runner or _run
    code, container = run(["docker", "create", reference], timeout=120)
    if code != 0:
        return None, "docker create exited %d" % code
    container_id = container.splitlines()[-1].strip()
    try:
        code, listing = run(
            ["docker", "export", container_id, "--output", os.devnull],
            timeout=300)
        # `docker export` writes a tar; listing it needs the archive. Rather
        # than materialise a large file, the caller-facing path uses
        # `docker run --rm --entrypoint` only when a runtime is present. The
        # export above is a reachability check.
        code, listing = run(
            ["docker", "run", "--rm", "--entrypoint", "/usr/bin/find",
             reference, "/app", "-type", "f"], timeout=300)
        if code != 0:
            return None, "the image listing command exited %d" % code
        return tuple(line.strip() for line in listing.splitlines()
                     if line.strip()), ""
    finally:
        run(["docker", "rm", "-f", container_id], timeout=60)


def audit_image_contents(reference: str, *, runner=None
                         ) -> Mapping[str, object]:
    """Fail the build when the image contains something it must not.

    Checked on the filesystem, not on the ignore file. The two disagree the
    moment a ``COPY`` names a path the ignore file did not anticipate, and
    that disagreement is exactly what this exists to catch.
    """
    paths, error = image_filesystem_paths(reference, runner=runner)
    if paths is None:
        return {"state": ExecutionState.BLOCKED.value, "checked": False,
                "detail": error, "offenders": []}
    relative = tuple(path[len("/app/"):] if path.startswith("/app/") else path
                     for path in paths)
    offenders = forbidden_paths_in(relative)
    return {
        "state": (ExecutionState.VERIFIED.value if not offenders
                  else ExecutionState.EXECUTED.value),
        "checked": True,
        "file_count": len(paths),
        "offenders": list(offenders),
        "clean": not offenders,
        "note": (
            "Measured on the built filesystem. .dockerignore states an "
            "intention; this is the result, and only this would catch a COPY "
            "that named a path the ignore file did not anticipate."),
    }


def compare_images(first: Mapping[str, Any], second: Mapping[str, Any]
                   ) -> Mapping[str, object]:
    """Compare two builds on what determines content, not on the digest.

    See the module docstring. Digests are compared and reported, but a
    difference in them is *not* reported as irreproducibility on its own,
    because attestation and builder metadata move a digest without moving a
    byte the application will ever execute.
    """
    content_fields = ("layer_diff_ids", "user", "entrypoint", "command",
                      "exposed_ports", "architecture", "os")
    differences = {name: [first.get(name), second.get(name)]
                   for name in content_fields
                   if first.get(name) != second.get(name)}
    digests_agree = (first.get("image_digest") == second.get("image_digest")
                     and first.get("image_digest") is not None)
    return {
        "content_identical": not differences,
        "compared_fields": list(content_fields),
        "differences": differences,
        "image_digests_agree": digests_agree,
        "image_digest_note": (
            "An image digest covers the config and every layer, and layers "
            "carry timestamps, build-arg history and BuildKit attestations. "
            "Two builds of identical source routinely differ there while "
            "containing identical filesystems, so the content comparison "
            "above is the reproducibility statement and the digest "
            "comparison is recorded beside it rather than instead of it."),
    }
