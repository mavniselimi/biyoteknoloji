#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the Wave 5 external expert evaluation package (B2/B3/B4 artifacts).

Deterministic: run twice on an unchanged tree and the files are byte-identical.
The clock is pinned to the frozen record's own commit-independent constant so
that the access ledger does not change the manifest on every run - what the
ledger proves is the *decision*, and a wall-clock timestamp would only make
the artifact undiffable.

The script refuses to write anything if the committed reserved-case artifact
no longer matches what the canonical builder produces, because a package built
from a drifted catalogue would send the reviewer a version nobody froze.
"""

from __future__ import annotations

import datetime as _dt
import io
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from pgx.application.candidate_release import (  # noqa: E402
    load_active_candidate_release)
from pgx.closure.wave04_catalogue import build_catalogue  # noqa: E402
from pgx.closure.wave05_expert_package import (  # noqa: E402
    digest_file, package_manifest, reviewer_response_template,
    reviewer_worksheet, seal_report)
from pgx.validation.vocabulary import ValidationCaseRole  # noqa: E402

OUT = os.path.join(REPO, "data", "expert-package")
CATALOGUE = os.path.join(REPO, "data", "closure", "wave-04-catalogue",
                         "expert-reserved.json")
CATALOGUE_RELATIVE = "data/closure/wave-04-catalogue/expert-reserved.json"
FROZEN = os.path.join(REPO, "data", "closure",
                      "wave-05-frozen-candidate-version.json")

#: A fixed instant. The ledger records which decision was reached for which
#: case, and pinning the instant is what lets the artifact be diffed.
PINNED = _dt.datetime(2026, 9, 6, 12, 0, 0, tzinfo=_dt.timezone.utc)

#: Every document the package contains, in reading order. Listed rather than
#: globbed: a file that appears in the directory without being added here is
#: not part of the package, and the manifest will not silently adopt it.
PACKAGE_DOCUMENTS = (
    "docs/expert-package/README.md",
    "docs/expert-package/01-purpose-and-claim-boundary.md",
    "docs/expert-package/02-demo-and-validation-only-scope.md",
    "docs/expert-package/03-scientific-source-strategy.md",
    "docs/expert-package/04-h01-decision-and-its-limits.md",
    "docs/expert-package/05-dataset-provenance-and-dq-decision.md",
    "docs/expert-package/06-four-drugs-two-genes.md",
    "docs/expert-package/07-curation-methodology.md",
    "docs/expert-package/08-amitriptyline-joint-representation.md",
    "docs/expert-package/09-clopidogrel-acs-pci-restriction.md",
    "docs/expert-package/10-phenotype-and-activity-score-refusals.md",
    "docs/expert-package/11-rule-and-release-lineage.md",
    "docs/expert-package/12-internal-validation-methodology.md",
    "docs/expert-package/13-non-independence-limitation.md",
    "docs/expert-package/14-representative-demonstration.md",
    "docs/expert-package/15-known-limitations.md",
    "docs/expert-package/16-questions-for-the-expert.md",
    "docs/expert-package/reviewer/00-reviewer-instructions.md",
    "docs/expert-package/reviewer/01-qualification-and-identity.md",
    "docs/expert-package/reviewer/02-conflict-of-interest.md",
    "docs/expert-package/reviewer/03-consent-and-data-handling.md",
    "docs/expert-package/reviewer/04-blind-first-workflow.md",
    "docs/expert-package/reviewer/05-review-questionnaire.md",
    "docs/expert-package/reviewer/06-submission-procedure.md",
    "data/expert-package/expert-reserved-seal.json",
    "data/expert-package/expert-reserved-worksheet.json",
    "data/expert-package/reviewer-response-template.json",
)


def _write(relative: str, payload: object) -> str:
    path = os.path.join(REPO, *relative.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True,
                      ensure_ascii=False) + "\n"
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return relative


def main() -> int:
    if not os.path.isfile(FROZEN):
        sys.stderr.write("the frozen candidate version record is missing; "
                         "run scripts/freeze_candidate_evaluation.py first\n")
        return 2
    with io.open(FROZEN, encoding="utf-8") as handle:
        frozen = json.load(handle)

    pinned = load_active_candidate_release(REPO)
    cases = build_catalogue(pinned.release_public_id,
                            pinned.manifest["manifest_hash"], pinned.ruleset)

    # The committed reserved artifact must still be what the builder makes.
    rebuilt = json.dumps(
        [case.to_json() for case in cases
         if case.metadata.role is ValidationCaseRole.EXPERT_HOLDOUT],
        indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with io.open(CATALOGUE, encoding="utf-8") as handle:
        committed = handle.read()
    if rebuilt != committed:
        sys.stderr.write(
            "refusing to build: the committed reserved-case artifact is not "
            "what the canonical builder produces. The package would describe "
            "a version nobody froze.\n")
        return 2

    seal = seal_report(cases, catalogue_path=CATALOGUE,
                       catalogue_relative=CATALOGUE_RELATIVE,
                       actor="pgx-closure-wave05",
                       clock=lambda: PINNED)
    if seal["payload_reads_allowed"]:
        sys.stderr.write("refusing to build: a reserved payload read was "
                         "allowed; the boundary this package rests on is "
                         "not intact\n")
        return 2
    if not seal["expected_is_null_for_every_case"]:
        sys.stderr.write("refusing to build: a reserved case carries an "
                         "expected answer\n")
        return 2

    worksheet = reviewer_worksheet(
        cases, release_public_id=pinned.release_public_id,
        release_manifest_hash=pinned.manifest["manifest_hash"],
        catalogue_sha256=seal["catalogue_sha256"])

    _write("data/expert-package/expert-reserved-seal.json", seal)
    _write("data/expert-package/expert-reserved-worksheet.json", worksheet)

    # The response template names the package manifest it answers, so the
    # manifest is hashed once without it, then the template is written, then
    # the manifest is written for real. Both hashes end up in the tree and
    # both are reproducible.
    provisional = package_manifest(
        REPO, [p for p in PACKAGE_DOCUMENTS
               if p != "data/expert-package/reviewer-response-template.json"],
        frozen=frozen, seal=seal)
    provisional_hash = "sha256:" + __import__("hashlib").sha256(
        (json.dumps(provisional, indent=2, sort_keys=True,
                    ensure_ascii=False) + "\n").encode("utf-8")).hexdigest()

    _write("data/expert-package/reviewer-response-template.json",
           reviewer_response_template(
               release_public_id=pinned.release_public_id,
               frozen_combined_hash=frozen["combined_hash"],
               package_manifest_hash=provisional_hash))

    manifest = package_manifest(REPO, PACKAGE_DOCUMENTS,
                                frozen=frozen, seal=seal)
    manifest["pre_template_manifest_hash"] = provisional_hash
    _write("data/expert-package/package-manifest.json", manifest)

    print("  reserved cases          %d" % seal["reserved_case_count"])
    print("  expected answers        %s"
          % ("none, in any of them"
             if seal["expected_is_null_for_every_case"] else "PRESENT"))
    print("  payload reads allowed   %d" % seal["payload_reads_allowed"])
    print("  access events           %d (chain intact: %s)"
          % (seal["access_ledger"]["event_count"],
             seal["access_chain_intact"]))
    print("  package files           %d" % manifest["file_count"])
    if manifest["missing_files"]:
        print("  MISSING                 %s"
              % ", ".join(manifest["missing_files"]))
    print("  catalogue sha256        %s" % seal["catalogue_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
