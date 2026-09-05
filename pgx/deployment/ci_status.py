# -*- coding: utf-8 -*-
"""What the pipeline is, and whether anything ever ran it (WP-24).

Two facts that get conflated constantly:

* a workflow file exists - that is ``CONFIGURED``;
* a provider ran it - that is ``EXECUTED``, and it needs evidence.

This repository has **no commits**. ``git log`` reports an empty ``main`` and
every path is untracked, so no provider has had anything to run against.
``ci_executed`` is therefore ``null`` - not ``false`` - because "nobody has
run it" and "a run failed" need different actions from different people.

The other job here is **action pinning**. Every third-party action must be
pinned by full commit SHA, because a tag is a name the action's owner can move
and a moved tag is arbitrary code executing with the workflow's token. This
module parses every ``uses:`` in every workflow and classifies it as
``sha``, ``tag`` or ``unresolved``.

``unresolved`` deserves an explanation. Resolving a tag to a SHA requires
reaching the registry, and the environment this pipeline was written in had no
network. Rather than invent forty hex characters - a fabricated pin that looks
precise and would silently execute whatever is at that address, or nothing -
the workflows carry the all-zero SHA, which is guaranteed not to be a commit.
It fails loudly, it is unmistakably a placeholder, and
``scripts/resolve_action_pins.sh`` turns every one of them into a real pin
with one command. Until then the pipeline is fail-closed and this document
says so.
"""

from __future__ import annotations

import io
import os
import re
from typing import Mapping, Optional, Sequence, Tuple

from pgx.deployment.vocabulary import ExecutionState, blocker

__all__ = [
    "CI_STATUS_VERSION",
    "JOB_ORDER",
    "UNRESOLVED_SHA",
    "WORKFLOW_DIRECTORY",
    "action_pins",
    "ci_status",
]

CI_STATUS_VERSION = "pgx-wp24-ci-status/1"

WORKFLOW_DIRECTORY = ".github/workflows"

#: The documented placeholder. Forty zeros is not a commit in any git
#: repository, so it cannot be mistaken for a resolved pin and cannot
#: accidentally reference real code.
UNRESOLVED_SHA = "0" * 40

#: The ordered pipeline from architecture.md section 14.2. Declared here so a
#: test can assert the workflow implements this order rather than a similar
#: one, and so the order lives somewhere a reader will find it.
JOB_ORDER: Tuple[str, ...] = (
    "format-check",
    "lint",
    "type-check",
    "unit",
    "integration-and-migration",
    "api-contract",
    "legacy-regression",
    "safety-invariants",
    "holdout-regression",
    "build-image",
    "vulnerability-and-secret-checks",
    "release-validation",
)

# ``- uses:`` and ``uses:`` both. The first version of this pattern
# required the line to start with optional whitespace and ``uses``, which
# silently matched three of nine references and reported the pipeline as
# nearly pinned.
_USES = re.compile(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)\s*(?:#\s*(.*))?$",
                   re.MULTILINE)
_SHA = re.compile(r"^[0-9a-f]{40}$")


def _workflow_files(root: str) -> Sequence[str]:
    directory = os.path.join(root, *WORKFLOW_DIRECTORY.split("/"))
    if not os.path.isdir(directory):
        return ()
    return tuple(sorted(
        os.path.join(WORKFLOW_DIRECTORY, name)
        for name in os.listdir(directory)
        if name.endswith((".yml", ".yaml"))))


def action_pins(root: str = ".") -> Mapping[str, object]:
    """Classify every ``uses:`` across every workflow."""
    entries = []
    for relative in _workflow_files(root):
        path = os.path.join(root, *relative.split("/"))
        with io.open(path, encoding="utf-8") as handle:
            source = handle.read()
        for match in _USES.finditer(source):
            reference = match.group(1)
            comment = (match.group(2) or "").strip()
            name, _, version = reference.partition("@")
            if version == UNRESOLVED_SHA:
                kind = "unresolved"
            elif _SHA.match(version):
                kind = "sha"
            elif not version:
                kind = "local"
            else:
                kind = "tag"
            entries.append({
                "workflow": relative, "action": name, "reference": version,
                "kind": kind,
                # The human-readable version the pin is meant to be. Required
                # for a SHA pin: forty hex characters tell a reviewer nothing
                # about what they are approving.
                "version_comment": comment or None,
            })
    unresolved = [item for item in entries if item["kind"] == "unresolved"]
    tags = [item for item in entries if item["kind"] == "tag"]
    unlabelled = [item for item in entries
                  if item["kind"] in ("sha", "unresolved")
                  and not item["version_comment"]]
    return {
        "action_count": len(entries),
        "actions": entries,
        "unresolved_count": len(unresolved),
        "tag_pinned_count": len(tags),
        "sha_pinned_count": len([item for item in entries
                                 if item["kind"] == "sha"]),
        "missing_version_comment": len(unlabelled),
        "all_sha_pinned": not unresolved and not tags,
        "unresolved_sha_sentinel": UNRESOLVED_SHA,
        "resolver": "scripts/resolve_action_pins.sh",
        "note": (
            "A tag is a name the action's owner can move, and a moved tag is "
            "arbitrary code running with the workflow's token. The all-zero "
            "SHA is a documented placeholder that is guaranteed not to be a "
            "commit: it fails loudly rather than executing something, and "
            "one command turns it into a real pin."),
    }


def ci_status(root: str = ".", *,
              environ: Optional[Mapping[str, str]] = None
              ) -> Mapping[str, object]:
    """Whether the pipeline exists, and whether a provider has run it."""
    source = dict(os.environ if environ is None else environ)
    workflows = list(_workflow_files(root))
    pins = action_pins(root)
    run_id = source.get("GITHUB_RUN_ID") or None
    executed = True if run_id else None
    blockers = []
    if executed is None:
        blockers.append(dict(blocker(
            "DEPLOY_CI_NOT_EXECUTED",
            owner="a CI provider, once this repository has a commit and a "
                  "remote",
            detail=("no run id is present. This repository has no commits, "
                    "so no provider has had anything to run against")
        ).to_json()))
    if not pins["all_sha_pinned"]:
        blockers.append(dict(blocker(
            "DEPLOY_CI_NOT_EXECUTED",
            owner="whoever has network access to the action registry",
            detail=("%d action references are not pinned to a commit SHA; "
                    "run scripts/resolve_action_pins.sh"
                    % (int(pins["unresolved_count"])  # type: ignore[arg-type]
                       + int(pins["tag_pinned_count"])))  # type: ignore
        ).to_json()))
    return {
        "ci_status_version": CI_STATUS_VERSION,
        "state": (ExecutionState.EXECUTED.value if executed
                  else ExecutionState.CONFIGURED.value),
        "workflows": workflows,
        "workflow_count": len(workflows),
        "job_order": list(JOB_ORDER),
        "ci_executed": executed,
        "ci_run_id": run_id,
        "ci_run_url": (source.get("GITHUB_SERVER_URL", "") + "/"
                       + source.get("GITHUB_REPOSITORY", "")
                       + "/actions/runs/" + run_id) if run_id else None,
        "action_pins": pins,
        "blockers": blockers,
        "note": (
            "A workflow file existing is CONFIGURED. A provider having run "
            "it is EXECUTED and needs evidence. ci_executed is null rather "
            "than false because 'nobody has run it' and 'a run failed' need "
            "different actions from different people."),
    }
