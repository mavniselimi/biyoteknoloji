#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate the Execution Wave 2 manifest.

    python3 scripts/build_closure_wave02_manifest.py

Writes ``data/closure/wave-02-execution-manifest.json``: one honest state per
work package, every artifact this wave produced with its digest, and the
blockers with their owners. Re-running over unchanged inputs produces
identical bytes.

A work package is not COMPLETED because its scaffolding exists. The states
here are the ones the wave brief defines, and PARTIALLY_COMPLETED is used
wherever part of the work needed access this environment does not have.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

MANIFEST = os.path.join("data", "closure", "wave-02-execution-manifest.json")

STATES = ("COMPLETED", "PARTIALLY_COMPLETED", "BLOCKED_BY_HUMAN",
          "BLOCKED_BY_EXTERNAL_ACCESS", "BLOCKED_BY_GOVERNANCE_INTEGRITY",
          "FAILED", "NOT_STARTED_DUE_TO_DEPENDENCY")

WORK_PACKAGES = (
    {
        "work_package": "WP-C01 residual closure",
        "state": "PARTIALLY_COMPLETED",
        "completed": [
            "migrations executed to head against real PostgreSQL 16.13 "
            "(carried over from Wave 1 and re-verified after a restart)",
            "append-only enforcement on audit_events proven by attempting an "
            "UPDATE and a DELETE and having both refused by the trigger",
            "three audit check constraints proven by three deliberately "
            "invalid inserts",
            "transaction rollback proven to leave no rows",
        ],
        "outstanding": [
            "the application connecting through SQLAlchemy, the audit chain "
            "through the unit of work, and transaction paths: all need "
            "psycopg, which no reachable index will serve",
            "uv.lock: uv lock --no-cache fails because PyPI returns 403",
        ],
        "blocked_by": "BLOCKED_BY_EXTERNAL_ACCESS",
    },
    {
        "work_package": "WP-C02 operations",
        "state": "PARTIALLY_COMPLETED",
        "completed": [
            "backup and restore drill against real PostgreSQL, verifying "
            "restored rows, table count, migration head and that the "
            "append-only trigger survived the restore",
            "secret scan clean",
            "CI-equivalent lint and type checks executed locally",
        ],
        "outstanding": [
            "wheel and sdist: the build backend is hatchling and PyPI "
            "returns 403; setuptools was deliberately not substituted",
            "CI action pins: api.github.com returns 403 and the repository's "
            "own resolver refuses to write a partially pinned workflow",
            "container image, SBOM, vulnerability scan: no container runtime "
            "and no supply-chain tooling",
            "staging and TLS: no authorized destination",
            "image rollback: no container runtime, and no governed release "
            "exists for it to be a release rollback of",
        ],
        "blocked_by": "BLOCKED_BY_EXTERNAL_ACCESS",
    },
    {
        "work_package": "WP-C05 controlled clean acquisition",
        "state": "BLOCKED_BY_HUMAN",
        "completed": [
            "acquisition matrix derived from the recorded H01 decision, "
            "refusing to be broader than it",
            "manual acquisition checklist prepared for an operator",
        ],
        "outstanding": [
            "every approved acquisition mode is MANUAL_DOWNLOAD, so a person "
            "must perform the retrievals; software may not",
            "no dataset id is allocated and no snapshot is sealed, because "
            "no permitted material has been retrieved",
        ],
        "blocked_by": "BLOCKED_BY_HUMAN",
        "note": "Also constrained by governance: pgx-source-policy validate "
                "still reports 0 approved sources, because the registry "
                "requires evidence provenance the project has not captured. "
                "Either condition alone would prevent acquisition.",
    },
    {
        "work_package": "WP-C06 dataset quality decision",
        "state": "PARTIALLY_COMPLETED",
        "completed": [
            "end-to-end audit of the existing mechanism, 18 requirements, "
            "recorded in the H04 evidence table including the rows where "
            "nothing was missing",
            "DatasetQualityDecision implemented: APPROVED/REJECTED, reviewer "
            "name and role, decision instant, rationale, DQ artifact hash "
            "and source-policy hash, all required with no defaults",
            "append-only ledger with replay refusal, stale-binding refusal "
            "and a missing-build refusal",
            "the approval path wired to the existing WP-07 transition rather "
            "than duplicating it; a rejection records and moves nothing",
            "human-readable review record renderer",
            "H04 checkpoint package prepared, approval form blank",
        ],
        "outstanding": [
            "no real decision exists: no legitimate dataset to decide about "
            "and no named data owner",
            "database persistence of a decision has never been executed",
            "an operator command that records a real decision was "
            "deliberately not added before a real dataset and a named owner "
            "exist",
        ],
        "blocked_by": "BLOCKED_BY_HUMAN",
    },
    {
        "work_package": "H02 preparation",
        "state": "COMPLETED",
        "completed": [
            "seven decisions, each in seven parts: source observation, "
            "repository assumption, owner direction, proposed "
            "representation, safety consequence, open question and the exact "
            "decision requested",
            "every WP-C04 scope contradiction linked to the decision that "
            "answers it, declared rather than string-matched",
            "each proposed decision bound to the protocol and disposition "
            "report content hashes",
            "the H01 approval explicitly stated not to constitute H02 "
            "approval",
        ],
        "outstanding": [
            "the decisions themselves, which need a qualified clinical "
            "pharmacogenomics reviewer",
        ],
        "blocked_by": "BLOCKED_BY_HUMAN",
    },
)

ARTIFACTS = (
    "data/closure/h01-source-policy-decision.json",
    "data/closure/wp-c05-acquisition-plan.json",
    "data/closure/wp-c01-c02-operational-evidence.json",
    "docs/closure/wp-c05-manual-acquisition-checklist.md",
    "docs/closure/checkpoints/H02-curation-protocol/clinical-review-table.csv",
    "docs/closure/checkpoints/H04-dataset-quality-decision/evidence-table.csv",
    "docs/closure/checkpoints/H04-dataset-quality-decision/proposed-decisions.csv",
    "pgx/normalization/quality_decision.py",
    "pgx/application/quality_decision_service.py",
    "pgx/closure/h02_package.py",
    "pgx/closure/acquisition_plan.py",
    "data/canonical/dataset-quality-decisions.ndjson",
)


def _sha256(path):
    if not os.path.isfile(path):
        return None
    digest = hashlib.sha256()
    with io.open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _git(root, *args):
    try:
        return subprocess.check_output(("git",) + args, cwd=root,
                                       stderr=subprocess.DEVNULL) \
            .decode("utf-8", "replace").strip()
    except Exception:  # noqa: BLE001
        return ""


def _read_json(path):
    if not os.path.isfile(path):
        return {}
    try:
        with io.open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def build(root):
    for item in WORK_PACKAGES:
        if item["state"] not in STATES:
            raise ValueError("%s is not a permitted state" % item["state"])

    artifacts = []
    for relative in sorted(ARTIFACTS):
        absolute = os.path.join(root, *relative.split("/"))
        artifacts.append({
            "path": relative,
            "present": os.path.isfile(absolute),
            "sha256": _sha256(absolute),
            "bytes": os.path.getsize(absolute)
            if os.path.isfile(absolute) else 0,
        })

    decision = _read_json(os.path.join(root, "data", "closure",
                                       "h01-source-policy-decision.json"))
    run = _read_json(os.path.join(root, "data", "verification",
                                  "wp19-verification-run.json"))
    ledger = os.path.join(root, "data", "canonical",
                          "dataset-quality-decisions.ndjson")

    payload = {
        "manifest_version": "pgx-closure-wave-02-manifest/1",
        "wave": "EXECUTION WAVE 2",
        "work_packages": [dict(item) for item in WORK_PACKAGES],
        "h01_enforcement": {
            "state": decision.get("state"),
            "reviewer": (decision.get("reviewer") or {}).get("name"),
            "decision": (decision.get("reviewer") or {}).get("decision"),
            "reviewed_content_matches": (decision.get("hash_binding") or {})
            .get("reviewed_content_matches"),
            "registry_changed": (decision.get("registry_change") or {})
            .get("config_scientific_sources_changed"),
            "approved_source_count": len(decision.get("source_outcomes") or ()),
        },
        "acquisition": {
            "executed": False,
            "dataset_id_allocated": False,
            "snapshot_sealed": False,
            "legacy_dataset_reused": False,
            "note": "no material was retrieved, so no dataset identity was "
                    "allocated and nothing was sealed. The quarantined "
                    "legacy dataset was not reused, relabelled or copied.",
        },
        "dataset_quality": {
            "mechanism_implemented": True,
            "decisions_recorded": sum(
                1 for line in io.open(ledger, encoding="utf-8")
                if line.strip()) if os.path.isfile(ledger) else 0,
            "note": "the mechanism is implemented and unit-tested; no real "
                    "decision exists and none was fabricated",
        },
        "verification_run": {
            "outcome": run.get("outcome"),
            "summary": run.get("summary"),
            "environment_class": "EPHEMERAL_CLOUD_DEVELOPMENT_CONTAINER",
        },
        "artifacts": artifacts,
        "git": {
            "head": _git(root, "rev-parse", "HEAD"),
            "baseline_tag": _git(root, "describe", "--tags", "--abbrev=0"),
            "remotes": len([line for line
                            in _git(root, "remote").splitlines() if line]),
        },
        "ths6_achieved": False,
        "release_activated": False,
        "note": "Nothing in this wave approved a source for use, curated an "
                "interpretation, generated a rule, published a dataset or "
                "activated a release. One human decision was recorded, on "
                "H01, and it did not make any source usable.",
    }
    payload["content_hash"] = "sha256:" + hashlib.sha256(json.dumps(
        payload, indent=2, sort_keys=True,
        ensure_ascii=False).encode("utf-8")).hexdigest()
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=REPO_ROOT)
    args = parser.parse_args()
    payload = build(args.repo_root)
    target = os.path.join(args.repo_root, MANIFEST)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with io.open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True,
                                ensure_ascii=False) + "\n")
    for item in payload["work_packages"]:
        sys.stdout.write("  %-38s %s\n"
                         % (item["work_package"], item["state"]))
    sys.stdout.write("artifacts present: %d/%d; decisions recorded: %d\n"
                     % (sum(1 for a in payload["artifacts"] if a["present"]),
                        len(payload["artifacts"]),
                        payload["dataset_quality"]["decisions_recorded"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
