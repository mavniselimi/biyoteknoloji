#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the candidate release and run the internal validation (WP-C09, C10).

Three things happen here and they are kept apart in the output, because they
support very different claims:

``SOFTWARE_VERIFICATION``
    the DEVELOPMENT partition. The rules were authored from these table rows,
    so agreement means the encoding is faithful. It is a statement about code.

``INTERNAL_VALIDATION``
    the INTERNAL_HOLDOUT partition - the amitriptyline joint table, which no
    candidate rule encodes. Each case asserts that combining the single-gene
    rules is never *weaker* than the guideline's own joint answer. This is the
    only partition in the wave that can fail for a scientific reason.

sealed and untouched
    the EXPERT_HOLDOUT partition. The access ledger records that this run
    listed its metadata and never read its payloads, so a later reader can
    check that claim rather than believe it.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pgx.closure.authority import CandidateAuthorityState  # noqa: E402
from pgx.closure.candidate_cases import (CATALOGUE_LIMITATIONS,  # noqa: E402
                                         CATALOGUE_VERSION, build_catalogue)
from pgx.closure.candidate_curation import attention_for_recommendation  # noqa: E402
from pgx.closure.candidate_release import (EVALUATION_VERSION,  # noqa: E402
                                           evaluate, not_weaker_than)
from pgx.closure.candidate_ruleset import build_candidate_ruleset  # noqa: E402
from pgx.closure.source_grounding import RETRIEVALS  # noqa: E402
from pgx.domain.enums import Phenotype  # noqa: E402
from pgx.validation.access import AccessContext, AccessLedger  # noqa: E402
from pgx.validation.separation import audit_partition  # noqa: E402
from pgx.validation.vocabulary import (AccessAction, AccessContextKind,  # noqa: E402
                                       ValidationCaseRole)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_ROOT = os.path.join(REPO, "data", "closure", "wave-03-candidate-release")

# The actor identifier is format-restricted, so the "not a human" statement
# cannot fit inside it. It travels in every purpose string instead, which the
# ledger records beside the actor on every single event.
ACTOR = "pgx-closure-wave03-automated-pass"
_LEDGER_INSTANT = _dt.datetime(2026, 9, 6, 12, 0, 0, tzinfo=_dt.timezone.utc)
NOT_A_HUMAN = "actor is an automated pass, not a person"


def _canonical(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True,
                      ensure_ascii=False) + "\n"


def _write(relative: str, payload: object) -> dict:
    path = os.path.join(OUTPUT_ROOT, relative)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = _canonical(payload)
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    raw = text.encode("utf-8")
    return {"relative_path": relative, "byte_length": len(raw),
            "sha256": "sha256:" + hashlib.sha256(raw).hexdigest()}


def main() -> int:
    ruleset = build_candidate_ruleset()
    cases = build_catalogue()
    audit = audit_partition([case.metadata for case in cases])
    if audit.issues:
        sys.stderr.write("refusing: separation audit reported %d issue(s)\n"
                         % len(audit.issues))
        for issue in audit.issues:
            sys.stderr.write("  %s %s\n" % (issue.code, issue.detail))
        return 2

    # A fixed clock, so the ledger's own bytes are reproducible. The ledger's
    # value is the *order* of accesses and the hash chain over them, neither of
    # which a wall-clock reading contributes to; a real reading would only make
    # the artifact differ from itself on every rebuild.
    ledger = AccessLedger(clock=lambda: _LEDGER_INSTANT)
    validation_context = AccessContext(
        actor=ACTOR, kind=AccessContextKind.VALIDATION_RUN,
        purpose=("evaluate the candidate ruleset against the open "
                 "partitions; " + NOT_A_HUMAN))
    audit_context = AccessContext(
        actor=ACTOR, kind=AccessContextKind.AUDIT,
        purpose=("list the sealed expert partition without reading "
                 "it; " + NOT_A_HUMAN))

    results = []
    failures = []
    for case in cases:
        if case.metadata.role is ValidationCaseRole.EXPERT_HOLDOUT:
            ledger.attempt(case.metadata, audit_context,
                           AccessAction.LIST_METADATA)
            results.append({
                "case_id": case.metadata.case_id.value,
                "role": case.metadata.role.value,
                "evaluated": False,
                "reason": ("sealed for external review; this wave listed its "
                           "metadata and did not evaluate the build against "
                           "it"),
            })
            continue

        ledger.attempt(case.metadata, validation_context,
                       AccessAction.READ_PAYLOAD)
        content = case.content
        if case.metadata.role is ValidationCaseRole.DEVELOPMENT:
            observed = evaluate(
                ruleset, drug=content["drug"],
                phenotypes={content["gene"]: Phenotype(content["phenotype"])})
            expected_level = case.expected["attention_level"]
            passed = (observed.outcome == "ATTENTION"
                      and observed.attention_level is not None
                      and observed.attention_level.value == expected_level)
            detail = ("expected %s, observed %s"
                      % (expected_level,
                         observed.attention_level.value
                         if observed.attention_level else observed.outcome))
            claim = "SOFTWARE_VERIFICATION"
        else:
            observed = evaluate(
                ruleset, drug=content["drug"],
                phenotypes={"CYP2C19": Phenotype(content["CYP2C19"]),
                            "CYP2D6": Phenotype(content["CYP2D6"])})
            required, _reason = attention_for_recommendation(
                case.expected["joint_recommendation"])
            passed = (observed.outcome == "ATTENTION"
                      and observed.attention_level is not None
                      and not_weaker_than(observed.attention_level, required))
            detail = ("guideline joint answer implies at least %s; combining "
                      "the single-gene candidate rules gives %s"
                      % (required.value,
                         observed.attention_level.value
                         if observed.attention_level else observed.outcome))
            claim = "INTERNAL_VALIDATION"

        row = {
            "case_id": case.metadata.case_id.value,
            "role": case.metadata.role.value,
            "claim_supported": claim,
            "evaluated": True,
            "passed": passed,
            "detail": detail,
            "observed": observed.to_json(),
        }
        results.append(row)
        if not passed:
            failures.append(row)

    chain_ok, broken_at = ledger.verify_chain()

    evaluated = [r for r in results if r.get("evaluated")]
    summary = {
        "authority_state": CandidateAuthorityState.INTERNAL_VALIDATION.value,
        "case_total": len(cases),
        "catalogue_limitations": list(CATALOGUE_LIMITATIONS),
        "catalogue_version": CATALOGUE_VERSION,
        "development_count": audit.development_count,
        "evaluated_count": len(evaluated),
        "evaluation_version": EVALUATION_VERSION,
        "expert_holdout_count": audit.expert_holdout_count,
        "expert_payloads_read": 0,
        "failed_count": len(failures),
        "internal_holdout_count": audit.internal_holdout_count,
        "ledger_chain_ok": chain_ok,
        "ledger_chain_broken_at": broken_at,
        "passed_count": len(evaluated) - len(failures),
        "permitted_channels": list(ruleset.permitted_channels),
        "review_state":
            CandidateAuthorityState.PENDING_EXTERNAL_EXPERT_REVIEW.value,
        "ruleset_content_hash": ruleset.content_hash(),
        "separation_issue_count": len(audit.issues),
    }

    artifacts = [
        _write("candidate-ruleset.json", ruleset.to_json()),
        _write("case-catalogue.json", [case.to_json() for case in cases]),
        _write("separation-audit.json", audit.to_json()),
        _write("evaluation-results.json", results),
        _write("access-ledger.json", ledger.to_json()),
        _write("evaluation-summary.json", summary),
    ]

    manifest = {
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "authority_state": CandidateAuthorityState.INTERNAL_VALIDATION.value,
        "citations": ["%s (%s), PMID %s, DOI %s"
                      % (item.title, item.guideline_version_label,
                         item.pmid, item.doi) for item in RETRIEVALS],
        "is_governed_release": False,
        "permitted_channels": list(ruleset.permitted_channels),
        "release_key": "PGX-CANDIDATE-RELEASE-WAVE03",
        "release_version": "pgx-wave03-candidate-release/1",
        "review_state":
            CandidateAuthorityState.PENDING_EXTERNAL_EXPERT_REVIEW.value,
        "scope_note": (
            "A candidate release. It is not a governed release bundle, is not "
            "registered with WP-13, is executable in DEMO and VALIDATION "
            "only, and has been reviewed by nobody outside this project."),
        "summary": summary,
    }
    manifest_entry = _write("manifest.json", manifest)

    lines = sorted("%s  %s" % (item["sha256"].split(":", 1)[1],
                               item["relative_path"])
                   for item in artifacts + [manifest_entry])
    with io.open(os.path.join(OUTPUT_ROOT, "checksums.sha256"), "w",
                 encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")

    sys.stdout.write(
        "candidate release built\n"
        "  cases            %d (dev %d / internal %d / expert %d)\n"
        "  evaluated        %d, passed %d, failed %d\n"
        "  expert payloads  %d read\n"
        "  separation       %d issue(s)\n"
        "  ledger chain     %s\n"
        "  ruleset hash     %s\n"
        % (len(cases), audit.development_count, audit.internal_holdout_count,
           audit.expert_holdout_count, len(evaluated),
           len(evaluated) - len(failures), len(failures), 0,
           len(audit.issues), "intact" if chain_ok else "BROKEN",
           ruleset.content_hash()))
    for row in failures:
        sys.stdout.write("  FAILED %s: %s\n" % (row["case_id"],
                                                row["detail"]))
    return 0 if not failures and chain_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
