#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Seal the Wave 4 validation catalogue before any benchmark runs (WP-C10).

Sealing first is the whole discipline. After this script has written the
catalogue, an expected answer that disagrees with a benchmark run becomes a
recorded issue; it does not become a corrected expectation. The script refuses
to overwrite a sealed catalogue for exactly that reason.

The expert-reserved payloads are written to their own file, and the benchmark
never opens it.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pgx.application.candidate_release import (  # noqa: E402
    load_active_candidate_release)
from pgx.closure.wave04_catalogue import (CATALOGUE_LIMITATIONS,  # noqa: E402
                                          CATALOGUE_VERSION, build_catalogue)
from pgx.domain.authority import CandidateAuthorityState  # noqa: E402
from pgx.validation.separation import audit_partition  # noqa: E402
from pgx.validation.vocabulary import ValidationCaseRole  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.join(REPO, "data", "validation", "wave-04-catalogue")


def _write(relative: str, payload: object) -> dict:
    path = os.path.join(ROOT, relative)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True,
                      ensure_ascii=False) + "\n"
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    raw = text.encode("utf-8")
    return {"relative_path": relative, "byte_length": len(raw),
            "sha256": "sha256:" + hashlib.sha256(raw).hexdigest()}


def main() -> int:
    if os.path.isdir(ROOT):
        sys.stdout.write(
            "the catalogue is already sealed at %s. It is not rewritten: a "
            "sealed expectation that could be edited after a benchmark run "
            "would not be an expectation.\n" % os.path.relpath(ROOT, REPO))
        return 0

    pinned = load_active_candidate_release(REPO)
    cases = build_catalogue(pinned.release_public_id,
                            pinned.manifest["manifest_hash"], pinned.ruleset)
    audit = audit_partition([case.metadata for case in cases])
    if audit.issues:
        sys.stderr.write("refusing to seal: %d separation issue(s)\n"
                         % len(audit.issues))
        for issue in audit.issues:
            sys.stderr.write("  %s %s\n" % (issue.code, issue.detail))
        return 2
    if audit.internal_holdout_count < 20 or audit.expert_holdout_count < 10 \
            or len(cases) < 50:
        sys.stderr.write(
            "refusing to seal: the catalogue is short of the P0 targets "
            "(%d cases, %d internal holdout, %d expert holdout)\n"
            % (len(cases), audit.internal_holdout_count,
               audit.expert_holdout_count))
        return 2

    by_role = {role: [c for c in cases if c.metadata.role is role]
               for role in ValidationCaseRole}
    artifacts = [
        _write("development.json",
               [c.to_json() for c in by_role[ValidationCaseRole.DEVELOPMENT]]),
        _write("internal-holdout.json",
               [c.to_json()
                for c in by_role[ValidationCaseRole.INTERNAL_HOLDOUT]]),
        # Reserved. The benchmark does not open this file, and its cases carry
        # no expected answer to open it for.
        _write("expert-reserved.json",
               [c.to_json()
                for c in by_role[ValidationCaseRole.EXPERT_HOLDOUT]]),
        _write("separation-audit.json", audit.to_json()),
    ]
    manifest = {
        "artifacts": artifacts,
        "authority_state": CandidateAuthorityState.INTERNAL_VALIDATION.value,
        "case_total": len(cases),
        "catalogue_version": CATALOGUE_VERSION,
        "development_count": audit.development_count,
        "expert_holdout_count": audit.expert_holdout_count,
        "expert_reserved_carry_no_expected_answer": True,
        "internal_holdout_count": audit.internal_holdout_count,
        "limitations": list(CATALOGUE_LIMITATIONS),
        "release_public_id": pinned.release_public_id,
        "release_manifest_hash": pinned.manifest["manifest_hash"],
        "review_state":
            CandidateAuthorityState.PENDING_EXTERNAL_EXPERT_REVIEW.value,
        "ruleset_content_hash": pinned.ruleset.content_hash(),
        "separation_issue_count": len(audit.issues),
        "sealed_before_any_benchmark_run": True,
    }
    manifest_entry = _write("manifest.json", manifest)
    lines = sorted("%s  %s" % (item["sha256"].split(":", 1)[1],
                               item["relative_path"])
                   for item in artifacts + [manifest_entry])
    with io.open(os.path.join(ROOT, "checksums.sha256"), "w",
                 encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")

    sys.stdout.write(
        "sealed %d cases (%d development, %d internal holdout, %d expert "
        "reserved)\n  separation issues  %d\n  release            %s\n"
        % (len(cases), audit.development_count, audit.internal_holdout_count,
           audit.expert_holdout_count, len(audit.issues),
           pinned.release_public_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
