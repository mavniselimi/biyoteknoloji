#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Freeze the core candidate ruleset into data/rulesets (WP-C08)."""

from __future__ import annotations

import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pgx.closure.wave03b_build import build_core_candidate_ruleset  # noqa: E402
from pgx.normalization.quality_decision import (LEDGER_PATH,  # noqa: E402
                                                QualityDecision, load_ledger)
from pgx.rules.candidate import write_candidate_ruleset  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET_ID = "PGX-DATA-20260906-001"
RULESET_KEY = "PGX-CANDIDATE-RULESET-WAVE03B"
DESTINATION = os.path.join(REPO, "data", "candidate-rulesets", RULESET_KEY)


def _read(path: str):
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    manifest = _read(os.path.join(REPO, "data", "canonical", DATASET_ID,
                                  "manifest.json"))
    snapshot = _read(os.path.join(REPO, "data", "raw",
                                  "cpic-guideline-capture", DATASET_ID,
                                  "manifest.json"))

    ledger = load_ledger(os.path.join(REPO, LEDGER_PATH))
    superseded = {row.supersedes for row in ledger if row.supersedes}
    current = [row for row in ledger
               if row.dataset_public_id == DATASET_ID
               and row.decision_id not in superseded]
    if len(current) != 1:
        sys.stderr.write("expected exactly one current decision for %s, "
                         "found %d\n" % (DATASET_ID, len(current)))
        return 2
    decision = current[0]
    if not decision.decision.permits_candidate_release:
        sys.stderr.write(
            "refusing: the current decision for %s is %s, which does not "
            "permit a candidate release\n"
            % (DATASET_ID, decision.decision.value))
        return 2

    ruleset = build_core_candidate_ruleset({
        "canonical_build_content_hash": manifest["content_hash"],
        "canonical_build_key": manifest["canonical_build_key"],
        "dataset_public_id": manifest["dataset_public_id"],
        "dq_decision_id": decision.decision_id,
        "snapshot_manifest_hash": snapshot["manifest_hash"],
        "source_policy_content_hash": decision.source_policy_hash,
        "source_policy_status": "PENDING_REVIEW",
    })

    if os.path.isdir(DESTINATION):
        sys.stdout.write("candidate ruleset already frozen at %s\n"
                         % os.path.relpath(DESTINATION, REPO))
    else:
        write_candidate_ruleset(ruleset, DESTINATION)

    sys.stdout.write(
        "%s\n  rules        %d (%d joint)\n  refusals     %d\n"
        "  modes        %s\n  content      %s\n"
        % (ruleset.ruleset_key, len(ruleset.rules),
           sum(1 for r in ruleset.rules if r.is_joint),
           len(ruleset.refusals), ", ".join(ruleset.permitted_modes),
           ruleset.content_hash()))
    for drug, genes in sorted(ruleset.expected_gene_scope.items()):
        sys.stdout.write("  scope        %-22s %s\n"
                         % (drug, ", ".join(genes)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
