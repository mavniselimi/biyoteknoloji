# -*- coding: utf-8 -*-
"""WP-C03: historical human decision checkpoints, packaged for review.

These packages were created under the original intermediate-human-gate policy.
They remain review and audit inputs, but unsigned packages no longer block the
candidate prototype under ``docs/closure/current-execution-policy.md``.
Source-grounded internal decisions are recorded separately and remain pending
final external expert evaluation.

What a package contains is deliberately limited. It states what the
repository can be made to show, what the project proposes, and what is not
known. It does not contain an approval, a signature, a name or a date, and
the approval form ships blank: a form with a name already in it is not a
record of a decision, it is a forgery of one. Every ``status`` in every
generated file stays at ``PENDING_REVIEW`` and nothing in this module can
move it.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from pgx.closure.research_findings import (FIRST_RELEASE_AXES,
                                           PHENOTYPE_SCOPE,
                                           SCOPE_CONTRADICTIONS,
                                           SOURCE_FINDINGS,
                                           TARGET_SOURCE_KEYS, coverage_rows)

__all__ = ["CHECKPOINTS", "PACKAGE_FILES", "build_all", "render_csv"]

PACKAGE_FILES: Tuple[str, ...] = (
    "README.md", "decision-context.md", "evidence-table.csv",
    "proposed-decisions.csv", "unresolved-questions.md", "risk-summary.md",
    "approval-form.md")

#: Files a particular checkpoint adds beyond the common seven.
EXTRA_PACKAGE_FILES: Dict[str, Tuple[str, ...]] = {
    "H02-curation-protocol": ("clinical-review-table.csv",),
}

_PENDING = "PENDING_REVIEW"


def render_csv(header: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    """CSV with a fixed dialect, so a rebuild is byte-identical."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(list(header))
    for row in rows:
        writer.writerow(["" if value is None else str(value)
                         for value in row])
    return buffer.getvalue()


def _approval_form(checkpoint: Mapping[str, Any]) -> str:
    """A blank form. It is blank on purpose and stays blank until a person.

    Nothing generated may pre-fill a name, a date or a verdict. A reviewer
    fills this in, commits it, and only then does anything downstream change.
    An unfilled form is not an approval and must never be read as one.
    """
    lines = [
        "# %s - approval form" % checkpoint["id"],
        "",
        "**This form is blank and unsigned. An unfilled form is not an "
        "approval, and no automated process may treat it as one.**",
        "",
        "Filling this in is a human act with consequences: it moves the "
        "decisions in `proposed-decisions.csv` out of `PENDING_REVIEW` and "
        "lets work downstream begin. Do not sign it on the strength of the "
        "proposal alone - the proposal is what the project would like to be "
        "true, and your job is to say whether it is.",
        "",
        "## Decision",
        "",
        "| Field | Value |",
        "| --- | --- |",
        "| Checkpoint | `%s` |" % checkpoint["id"],
        "| Reviewer name | |",
        "| Reviewer role | |",
        "| Qualification relied on | |",
        "| Date (UTC, ISO 8601) | |",
        "| Verdict | APPROVED / REJECTED / APPROVED WITH CHANGES |",
        "| Proposal file reviewed (`content_hash`) | |",
        "",
        "## Per-decision verdicts",
        "",
        "Copy each `decision_id` from `proposed-decisions.csv` and record a "
        "verdict. A decision with no row here is not approved.",
        "",
        "| decision_id | verdict | changed to | reason |",
        "| --- | --- | --- | --- |",
        "| | | | |",
        "",
        "## Conditions attached to this approval",
        "",
        "_List anything that must be true for this approval to hold. If "
        "there are none, write \"none\" - do not leave it empty._",
        "",
        "## What this approval does not cover",
        "",
    ]
    for item in checkpoint["not_covered"]:
        lines.append("- %s" % item)
    lines += [
        "",
        "## Signature",
        "",
        "_Sign in whatever way this project has agreed constitutes a "
        "signature. A typed name with no agreed meaning behind it is not "
        "one._",
        "",
    ]
    return "\n".join(lines) + "\n"


def _readme(checkpoint: Mapping[str, Any]) -> str:
    lines = [
        "# %s - %s" % (checkpoint["id"], checkpoint["title"]),
        "",
        "> **Historical checkpoint notice (2026-09-06):** This package was "
        "created under the original intermediate-human-gate policy. Its "
        "evidence and any genuine human response remain valid audit inputs, "
        "but an unsigned form no longer blocks construction of the candidate "
        "prototype. Open questions must be resolved in traceable "
        "`SOURCE_GROUNDED_INTERNAL_DECISION` or `PROJECT_TEAM_PROVISIONAL` "
        "records and remain `PENDING_EXTERNAL_EXPERT_REVIEW`. See "
        "`../../current-execution-policy.md`.",
        "",
        "**Status: %s.** Nothing in this package is approved." % _PENDING,
        "",
        checkpoint["summary"],
        "",
        "## Who decides",
        "",
        "| Field | Value |",
        "| --- | --- |",
        "| Decision owner | %s |" % checkpoint["owner"],
        "| Cannot be decided by | %s |" % checkpoint["not_owner"],
        "| Blocks | %s |" % ", ".join(checkpoint["blocks"]),
        "| Blocked by | %s |" % (", ".join(checkpoint["depends_on"])
                                 or "nothing; this can be decided now"),
        "",
        "## The files",
        "",
        "| File | What it is |",
        "| --- | --- |",
        "| `decision-context.md` | What has to be decided and why it cannot "
        "be decided by code. |",
        "| `evidence-table.csv` | What the repository and the primary "
        "documents actually show. Each row cites where it was read. |",
        "| `proposed-decisions.csv` | What the project proposes. Every row "
        "is `%s`. |" % _PENDING,
        "| `unresolved-questions.md` | What is not known, and what would "
        "have to happen to know it. |",
        "| `risk-summary.md` | What goes wrong if this is decided wrongly, "
        "or not decided. |",
        "| `approval-form.md` | Blank. A reviewer fills it in. |",
    ]
    for extra in EXTRA_PACKAGE_FILES.get(checkpoint["id"], ()):
        lines.append("| `%s` | %s |"
                     % (extra, "Every decision in seven parts: what the "
                               "source says, what this repository assumes, "
                               "what the owner directed, what is proposed, "
                               "what goes wrong, what is unknown, and what "
                               "you are being asked to decide."))
    lines += [
        "",
        "## How to use this",
        "",
        "Read `decision-context.md`, then check `proposed-decisions.csv` "
        "against `evidence-table.csv` rather than against the prose - the "
        "prose is the project's reading and the evidence is what it read. "
        "Then fill in `approval-form.md`. Approving something the evidence "
        "table does not support is the failure mode this layout exists to "
        "make visible.",
        "",
    ]
    return "\n".join(lines).rstrip("\n") + "\n"


def _document(title: str, intro: str,
              sections: Sequence[Tuple[str, Sequence[str]]]) -> str:
    lines = ["# %s" % title, "", intro, ""]
    for heading, body in sections:
        lines.append("## %s" % heading)
        lines.append("")
        lines.extend(body)
        lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# H01 - source policy (carries the WP-C04 research)
# ---------------------------------------------------------------------------

#: The source keys the H01 review actually covered.
#:
#: Pinned rather than read from the live registry, because the H01 checkpoint
#: is a record of what a named pharmacist was shown on 2026-09-06, and the
#: reviewed-content files are bound to that record by sha256. Regenerating them
#: from a registry that has since gained a source would change those hashes and
#: drive H01 into AWAITING_REATTESTATION - which is the drift protocol working,
#: but the drift would be entirely spurious: a source registered afterwards was
#: never part of the decision, and pretending it was would be worse than
#: leaving it out.
#:
#: A source registered after H01 is therefore absent from this checkpoint by
#: construction, which is also the accurate statement about its authority: H01
#: did not review it and does not authorise it.
H01_REVIEWED_SOURCE_KEYS: Tuple[str, ...] = (
    "aha.publications",
    "ausnz.publications",
    "clinpgx.api",
    "clinpgx.website",
    "cpic.api",
    "cpic.database",
    "cpic.publications",
    "cpnds.publications",
    "dpwg.knmp",
    "druglabel.ema",
    "druglabel.fda",
    "druglabel.hcsc",
    "druglabel.pmda",
    "druglabel.swissmedic",
    "druglabel.titck",
    "internal.legacy_mvp_seed",
    "internal.legacy_probe_outputs",
    "internal.manual_normalization",
    "pubmed.literature",
    "rnpgx.publications",
)


def _h01_sources(registry: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """The registry rows H01 reviewed, in a stable order."""
    reviewed = set(H01_REVIEWED_SOURCE_KEYS)
    return sorted((entry for entry in registry["sources"]
                   if entry["source_key"] in reviewed),
                  key=lambda item: item["source_key"])


def _h01_evidence(registry: Mapping[str, Any]) -> str:
    rows: List[List[Any]] = []
    findings = {item["source_key"]: item for item in SOURCE_FINDINGS}
    for entry in _h01_sources(registry):
        key = entry["source_key"]
        found = findings.get(key)
        rows.append([
            key, entry["role"], entry["status"],
            "RESEARCHED" if found else "NOT_RESEARCHED_THIS_WAVE",
            (found or {}).get("scientific_authority", "NOT_ASSESSED"),
            (found or {}).get("licence", "UNKNOWN"),
            (found or {}).get("verification", "NOT_ATTEMPTED"),
            (found or {}).get("licence_evidence", ""),
            (found or {}).get("verification_gap", "") or "",
            (found or {}).get("conflict", "") or "",
            len((found or {}).get("reuse_supported_by_licence", ())),
            len((found or {}).get("reuse_still_unknown",
                                  tuple(entry["reuse"]))),
            entry["acquisition_mode"],
        ])
    coverage = [[row["source_key"], row["axis"], row["coverage"]]
                for row in coverage_rows()]
    return (render_csv(
        ["source_key", "registry_role", "registry_status", "researched",
         "scientific_authority", "licence_identifier_found",
         "verification_level", "read_from", "verification_gap",
         "conflict_code", "reuse_dimensions_supported",
         "reuse_dimensions_unknown", "current_acquisition_mode"], rows)
        + "\n"
        + render_csv(["source_key", "first_release_axis", "coverage"],
                     coverage))


def _h01_proposals(registry: Mapping[str, Any]) -> str:
    findings = {item["source_key"]: item for item in SOURCE_FINDINGS}
    rows: List[List[Any]] = []
    for position, entry in enumerate(
            _h01_sources(registry), 1):
        key = entry["source_key"]
        found = findings.get(key)
        if key not in TARGET_SOURCE_KEYS:
            proposal = "DEFER_OUTSIDE_FIRST_RELEASE_SCOPE"
            rationale = ("Not required by any of the five first-release "
                         "axes. Deferring is a scope decision and says "
                         "nothing about the source's quality or terms.")
        elif found and found["licence"] == "CC0-1.0":
            proposal = "APPROVE_FOR_ACQUISITION_SUBJECT_TO_NAMED_CONDITIONS"
            rationale = ("A public-domain dedication was read from the "
                         "provider's own distribution. The conditions are "
                         "in unresolved-questions.md and are not waived by "
                         "this proposal.")
        elif found and found.get("conflict"):
            proposal = "ESCALATE_BEFORE_ANY_ACQUISITION"
            rationale = ("The source's own terms contradict themselves or "
                         "are unreachable. A maintainer cannot resolve "
                         "this; %s" % found["conflict"].lower().replace(
                             "_", " ") + ".")
        else:
            proposal = "RESEARCH_FURTHER_BEFORE_DECIDING"
            rationale = ("Required by the first release but its terms are "
                         "not established. Absence of a statement is not "
                         "permission.")
        rows.append([
            "H01-D%02d" % position, key, entry["status"], _PENDING, proposal,
            rationale,
            (found or {}).get("licence", "UNKNOWN"),
            "; ".join((found or {}).get("reuse_supported_by_licence", ()))
            or "none established",
            "source policy approver",
        ])
    return render_csv(
        ["decision_id", "source_key", "current_status", "target_status",
         "proposed_disposition", "rationale", "licence_as_read",
         "reuse_dimensions_the_licence_would_support", "decision_owner"],
        rows)


def _h01_context() -> str:
    return _document(
        "H01 - source policy: what has to be decided",
        "Twenty sources sit in `config/scientific-sources.json`, every one of "
        "them `PENDING_REVIEW`, every reuse dimension `UNKNOWN`, and no "
        "acquisition mode decided. Nothing may be acquired until somebody "
        "with the standing to do so says which sources this project may use "
        "and on what terms. WP-C04 did the reading; it did not and could not "
        "do the deciding.",
        [
            ("What was read, and what was not", [
                "Each researched source was read from a primary document - a "
                "licence file, a provider's own terms page, a regulator's "
                "own labelling. No row in `evidence-table.csv` rests on a "
                "search-result snippet or a secondary summary. Where a "
                "document could not be retrieved, the row says "
                "`RETRIEVAL_FAILED` or `NOT_ESTABLISHED` and the licence "
                "stays `UNKNOWN`.",
                "",
                "Twelve of the twenty sources were not researched at all, "
                "because the first release does not depend on them. That is "
                "recorded as `NOT_RESEARCHED_THIS_WAVE` rather than left to "
                "look like an absence of findings.",
            ]),
            ("Two things this package refuses to merge", [
                "**Scientific authority** is whether this project would cite "
                "a source. **Legal permission** is whether it may hold, "
                "transform or republish that source's material. DPWG scores "
                "high on the first and is entirely unestablished on the "
                "second; neither fact is evidence for the other.",
                "",
                "**API terms** and **website terms** are separate documents "
                "even for one provider, and this package keeps them in "
                "separate rows. `clinpgx.website` publishes a data statement; "
                "`clinpgx.api` has no terms document the project could find, "
                "and the evidence build already in this repository was "
                "acquired through it.",
            ]),
            ("What the proposals mean", [
                "`APPROVE_FOR_ACQUISITION_SUBJECT_TO_NAMED_CONDITIONS` means "
                "the project read a licence that would permit the use it "
                "needs, and still wants a person to say so. The named "
                "conditions are not waived by the proposal.",
                "",
                "`ESCALATE_BEFORE_ANY_ACQUISITION` means the source's own "
                "terms contradict each other, or the source cannot be "
                "reached at all. These are not maintainer decisions.",
                "",
                "`RESEARCH_FURTHER_BEFORE_DECIDING` means the source is "
                "needed and its terms are unknown. Nothing may be acquired "
                "from it in the meantime.",
                "",
                "`DEFER_OUTSIDE_FIRST_RELEASE_SCOPE` is a statement about "
                "this release's scope, not about the source.",
            ]),
            ("Why code cannot decide this", [
                "Every one of these turns on a reading of terms, a "
                "jurisdictional judgement, or an appetite for risk that "
                "belongs to whoever answers for the project. The ClinPGx "
                "row is the clearest case: a licence that permits commercial "
                "use sits beside a restriction forbidding it, in the same "
                "statement, and choosing which half governs is a legal "
                "question with consequences for anything built on it.",
            ]),
        ])


def _h01_questions() -> str:
    lines: List[str] = []
    for item in SOURCE_FINDINGS:
        if not item.get("verification_gap") and not item.get("conflict"):
            continue
        lines.append("### `%s`" % item["source_key"])
        lines.append("")
        if item.get("conflict"):
            lines.append("- **Conflict:** `%s`" % item["conflict"])
        if item.get("verification_gap"):
            lines.append("- **Gap:** %s" % item["verification_gap"])
        lines.append("- **Still unknown:** %s"
                     % (", ".join("`%s`" % dimension for dimension
                                  in item["reuse_still_unknown"])
                        or "nothing"))
        lines.append("- **Note:** %s" % item["reuse_note"])
        lines.append("")
    return _document(
        "H01 - unresolved questions",
        "Everything below is unknown, not merely undecided. A reviewer who "
        "approves a source while one of its rows is open is approving the "
        "unknown, which is the specific thing this file exists to prevent.",
        [("Per source", lines),
         ("Questions that apply to every source", [
             "- Does the project accept material acquired before its source "
             "policy existed? The quarantined evidence build was acquired "
             "through `clinpgx.api` under terms nobody had established.",
             "- What does the project do when a source's terms change after "
             "acquisition? Nothing currently re-checks them.",
             "- Which jurisdiction's law governs these readings? The "
             "sources span the United States, the Netherlands and Turkey, "
             "and the deployment's jurisdiction is not recorded anywhere in "
             "the repository.",
         ])])


def _h01_risks() -> str:
    return _document(
        "H01 - risk summary",
        "What follows is what goes wrong, not how likely it is. Likelihood "
        "is the reviewer's to judge.",
        [("If this is decided wrongly", [
            "- **Acquiring under terms that forbid it.** The exposure is not "
            "the download; it is everything derived from it afterwards, "
            "which would have to be identified and withdrawn. The evidence "
            "build in this repository is already in that position.",
            "- **Treating silence as permission.** DPWG publishes no terms. "
            "Reading that as permissive is the single easiest mistake to "
            "make here, and the structured form of the same data is "
            "commercially licensed and forbids reproduction.",
            "- **Approving the API on the strength of the website.** They "
            "are different documents and routinely differ.",
            "- **Republishing label text.** Reading a regulator's label to "
            "decide what a rule says is not the same act as reproducing its "
            "wording, and the second is unresolved for FDA content.",
         ]),
         ("If this is not decided at all", [
            "- No source may be acquired, so no curated interpretation can "
            "be written, so no rule can be built and no release can be "
            "activated. H01 is the first domino; everything downstream is "
            "waiting on it.",
            "- The Turkish regulator remains unreachable, so a deployment "
            "in that jurisdiction has no local regulatory source at all.",
         ])])


# ---------------------------------------------------------------------------
# H02 - curation protocol
# ---------------------------------------------------------------------------

def _h02_review_table() -> str:
    """The seven-part review table, one row per decision."""
    from pgx.closure.h02_package import H02_DECISIONS

    return render_csv(
        ["decision_id", "subject", "authoritative_source_observation",
         "current_repository_assumption", "project_owner_direction",
         "proposed_technical_representation", "safety_consequence",
         "unresolved_scientific_question", "exact_human_decision_requested"],
        [[item["decision_id"], item["subject"], item["source_observation"],
          item["repository_assumption"], item["owner_direction"] or "none",
          item["proposed_representation"], item["safety_consequence"],
          item["open_question"], item["decision_requested"]]
         for item in H02_DECISIONS])


def _h02_evidence(protocol: Mapping[str, Any],
                  dispositions: Mapping[str, Any]) -> str:
    counts = dispositions["counts"]
    rows = [
        ["protocol_status", protocol.get("status"),
         "config/curation/protocol-v1.json"],
        ["protocol_version", protocol.get("protocol_version"),
         "config/curation/protocol-v1.json"],
        ["expert_approved", protocol.get("expert_approved"),
         "config/curation/protocol-v1.json"],
        ["vocabulary_status", protocol.get("vocabulary_status"),
         "config/curation/protocol-v1.json"],
        ["approval_record", protocol.get("approval"),
         "config/curation/protocol-v1.json"],
        ["declared_roles", len(protocol.get("roles") or ()),
         "config/curation/protocol-v1.json"],
        ["declared_requirements", len(protocol.get("requirements") or ()),
         "config/curation/protocol-v1.json"],
        ["legacy_candidates_total",
         dispositions["upstream_state"]["total_candidates"],
         "data/migration/wp11/legacy-rule-candidate-inventory.json"],
        ["legacy_candidates_eligible_for_rule_creation", 0,
         "data/migration/wp11/legacy-rule-candidate-inventory.json"],
        ["unlinked_candidates_needing_a_curator",
         counts["by_disposition"]["MISSING_EVIDENCE_REQUIRES_CURATOR"],
         "data/closure/wp-c00-legacy-candidate-dispositions.json"],
        ["first_release_axes", len(FIRST_RELEASE_AXES),
         "the declared scientific scope"],
        ["phenotype_values_in_scope", len(PHENOTYPE_SCOPE),
         "the declared scientific scope"],
        ["scope_contradictions_found", len(SCOPE_CONTRADICTIONS),
         "WP-C04 source research"],
    ]
    return render_csv(["fact", "value", "read_from"], rows)


def _h02_proposals(bindings: Mapping[str, str]) -> str:
    """One row per H02 decision, bound to the bytes it is about."""
    from pgx.closure.h02_package import H02_DECISIONS, OWNER_DIRECTION_STATUS

    rows = []
    for item in H02_DECISIONS:
        rows.append([
            item["decision_id"], item["subject"],
            (OWNER_DIRECTION_STATUS if item["owner_direction"]
             else "NOT_ADDRESSED_BY_THE_PROTOCOL"),
            _PENDING, item["decision_requested"],
            item["open_question"],
            "clinical pharmacogenomics reviewer",
            bindings.get("protocol", ""), bindings.get("dispositions", "")])
    return render_csv(
        ["decision_id", "subject", "current_state", "target_status",
         "exact_human_decision_requested", "unresolved_scientific_question",
         "decision_owner", "bound_protocol_sha256",
         "bound_disposition_report_sha256"], rows)


def _h02_context() -> str:
    return _document(
        "H02 - curation protocol: what has to be decided",
        "`config/curation/protocol-v1.json` says of itself that it is not "
        "scientifically approved and that every vocabulary in it is draft "
        "until a named scientist records an approval against its content "
        "hash. Its `approval` field is null. Until that changes, every "
        "curation work item in the repository stays `RAW`, and it is right "
        "that they do.",
        [
            ("What approving this protocol means", [
                "It means a person with the standing to do so says: this is "
                "how a curator turns a source statement into a curated "
                "interpretation in this project, these are the fields, these "
                "are the vocabularies, and a conclusion reached this way is "
                "one I would defend. It is not a formality and it is not a "
                "document review.",
            ]),
            ("Five things the protocol does not currently address", [
                "WP-C04's reading of the primary sources turned up five "
                "places where the sources do not fit the shape the project "
                "has described. None is a defect in the protocol; each is a "
                "question the protocol is silent on, and a curator who meets "
                "one mid-task will invent an answer if nobody has given one.",
                "",
                "They are set out in `unresolved-questions.md` and carried "
                "as decisions `H02-D03` through `H02-D07`.",
            ]),
            ("The H01 approval is not an H02 approval", [
                "A pharmacist has approved this project's source policy. "
                "That decision says which sources may be used and on what "
                "terms. It says nothing about how a source's content becomes "
                "a clinical representation, and it must not be reused here: "
                "the reviewer was not asked, and did not answer, any of the "
                "questions in this package.",
                "",
                "Each row of `proposed-decisions.csv` is bound to the "
                "content hash of the protocol and of the legacy disposition "
                "report it depends on, so an approval recorded here cannot "
                "later attach to different bytes.",
            ]),
            ("What must not happen", [
                "The 1,559 legacy candidates carry the previous project's "
                "own risk levels, phenotype strings and plain-language "
                "hints. None of that is evidence, and a curation protocol "
                "that permitted a curator to start from a legacy row's "
                "wording would launder an unreviewed opinion into a curated "
                "interpretation. The protocol should be read with that "
                "specific failure in mind.",
            ]),
        ])


def _h02_questions() -> str:
    lines: List[str] = []
    for item in SCOPE_CONTRADICTIONS:
        lines.append("### %s - %s" % (item["id"], item["subject"]))
        lines.append("")
        lines.append("- **What the sources say:** %s" % item["finding"])
        lines.append("- **Why it matters:** %s" % item["why_it_matters"])
        lines.append("- **The decision:** %s" % item["decision_needed"])
        lines.append("- **Owner:** %s" % item["owner"])
        lines.append("")
    return _document(
        "H02 - unresolved questions",
        "These came out of reading the primary sources for the five declared "
        "axes. Each is a place where the source's own structure and the "
        "project's declared scope do not line up. None of them can be "
        "settled by looking at the repository, because the repository is "
        "what encodes the assumption in question.",
        [("Where the sources and the declared scope disagree", lines)])


def _h02_risks() -> str:
    return _document(
        "H02 - risk summary",
        "The protocol governs how a source statement becomes something this "
        "project will show a clinician. The risks are of that kind.",
        [("If this is decided wrongly, or too quickly", [
            "- **A curator invents a mapping mid-task.** Where the protocol "
            "is silent - a two-gene recommendation, an indication-specific "
            "one, a phenotype the vocabulary cannot express - the curator "
            "still has to produce something, and what they produce becomes "
            "the project's answer.",
            "- **Legacy text becomes evidence.** The single largest body of "
            "text in this repository is the previous project's unreviewed "
            "opinion. A protocol that does not forbid starting from it will "
            "get it back, laundered.",
            "- **A phenotype is mapped to its nearest neighbour.** CPIC "
            "emits values the five-value vocabulary cannot hold. Silent "
            "coercion of Likely Poor to Poor is a clinical claim nobody "
            "made.",
         ]),
         ("If this is not decided at all", [
            "- No curated interpretation can exist, so no rule can be built "
            "from evidence, so the platform has nothing real to assess "
            "against. This is the state the repository is in now, and it is "
            "correctly reported rather than worked around.",
         ])])


# ---------------------------------------------------------------------------
# H03 - claims boundary
# ---------------------------------------------------------------------------

def _h03_evidence(boundary: Mapping[str, Any]) -> str:
    rows = [
        ["claim_boundary_status", boundary["status"], "pgx/domain/claims.py"],
        ["claim_boundary_version", boundary["version"],
         "pgx/domain/claims.py"],
        ["phase", boundary["phase"], "pgx/domain/claims.py"],
        ["enabled_modes", "; ".join(boundary["enabled_modes"]),
         "pgx/domain/claims.py"],
        ["permitted_input_kinds", "; ".join(boundary["permitted_input_kinds"]),
         "pgx/domain/claims.py"],
        ["prohibited_claim_categories",
         "; ".join(boundary["prohibited_categories"]),
         "pgx/domain/claims.py"],
        ["warning_languages", "; ".join(boundary["warning_languages"]),
         "pgx/domain/claims.py"],
        ["blocking_gate_code_reporting",
         "REPORT_CLAIM_BOUNDARY_NOT_APPROVED", "pgx/reporting/errors.py"],
        ["blocking_gate_code_security",
         "SECURITY_CLAIM_BOUNDARY_NOT_APPROVED", "pgx/security/gate_status.py"],
    ]
    return render_csv(["fact", "value", "read_from"], rows)


def _h03_proposals(boundary: Mapping[str, Any]) -> str:
    rows = [
        ["H03-D01", "the boundary document itself", boundary["status"],
         _PENDING, "APPROVE_THE_BOUNDARY_AS_WRITTEN_OR_NAME_THE_CHANGES",
         "It is version %s and declares itself draft awaiting human and "
         "scientific review. Two gates block on its approval."
         % boundary["version"], "clinical and legal approver, jointly"],
        ["H03-D02", "the clinical warning text, both languages",
         "DRAFT", _PENDING, "APPROVE_THE_EXACT_WORDING",
         "The warning is what stands between a traceable attention finding "
         "and a reader taking it as advice. Its exact wording, in both "
         "languages, is the thing being approved - not its gist.",
         "clinical and legal approver, jointly"],
        ["H03-D03", "the eleven prohibited claim categories",
         "DRAFT", _PENDING, "CONFIRM_THE_LIST_IS_COMPLETE",
         "The scanner enforces exactly this list. A category nobody thought "
         "of is a category nothing blocks.",
         "clinical and legal approver, jointly"],
        ["H03-D04", "the permitted input kinds",
         "DRAFT", _PENDING, "CONFIRM_NO_REAL_PATIENT_INPUT_IS_PERMITTED",
         "Five input kinds are permitted and all are synthetic, public or "
         "protocol-defined. This is the control that keeps real genotype and "
         "patient data out, and it should be read as such.",
         "clinical and legal approver, jointly"],
        ["H03-D05", "the enabled operation modes",
         "DRAFT", _PENDING, "CONFIRM_DEMO_AND_VALIDATION_ONLY",
         "No production or clinical mode is enabled. Approving the boundary "
         "is not approving clinical use, and the form says so.",
         "clinical and legal approver, jointly"],
    ]
    return render_csv(
        ["decision_id", "subject", "current_state", "target_status",
         "proposed_disposition", "rationale", "decision_owner"], rows)


def _h03_context(boundary: Mapping[str, Any]) -> str:
    return _document(
        "H03 - claims boundary: what has to be decided",
        "The claims boundary is the sentence this platform is allowed to "
        "say, and the eleven kinds of sentence it is not. It is version %s "
        "and says of itself: %s. Two gates block on it, in reporting and in "
        "security, and they are right to."
        % (boundary["version"], boundary["status"]),
        [
            ("What is being approved", [
                "Not a policy in the abstract. The specific wording of the "
                "clinical warning in Turkish and English, the eleven "
                "prohibited claim categories the scanner enforces, the five "
                "permitted input kinds, and the two enabled operation modes. "
                "Each is enforced literally by code, so each is approved "
                "literally.",
            ]),
            ("What approving this does not do", [
                "It does not approve clinical use. The enabled modes are "
                "demonstration and validation, and no production or clinical "
                "mode exists to enable. It does not approve any particular "
                "output; it approves the boundary those outputs must stay "
                "inside.",
            ]),
            ("Why the wording and not the gist", [
                "The warning is the only thing standing between a traceable "
                "attention finding and a reader who takes it as advice. A "
                "reviewer who approves the idea of a warning has approved "
                "nothing enforceable. The scanner compares text.",
            ]),
        ])


def _h03_questions() -> str:
    return _document(
        "H03 - unresolved questions",
        "The boundary is written and enforced. What is missing is a person "
        "who has read it and said so, plus answers to the following.",
        [("Open", [
            "- Is the eleven-category prohibition list complete for the "
            "jurisdictions this will run in? The list was written by "
            "maintainers, not by counsel.",
            "- Is the Turkish warning a translation of the English one, or "
            "an independently drafted statement? If they diverge in effect, "
            "the platform says different things to different readers.",
            "- Who is accountable for the warning's adequacy once it is "
            "approved? The repository records no such role.",
            "- Does approving a boundary at `P0` commit anything about "
            "later phases? Nothing in the document says.",
         ])])


def _h03_risks() -> str:
    return _document(
        "H03 - risk summary",
        "This boundary is the control that keeps a research demonstrator "
        "from reading as clinical advice.",
        [("If this is decided wrongly", [
            "- **A warning that is present but not read as binding.** "
            "Wording that hedges achieves nothing; the reader takes the "
            "finding and leaves the caveat.",
            "- **An incomplete prohibition list.** The scanner blocks "
            "exactly what it is told to block, and a missing category is a "
            "sentence that passes.",
            "- **Approving the boundary as though it approved the "
            "platform.** It approves the limits, not the outputs, and an "
            "approval read the other way would license exactly the use the "
            "boundary exists to forbid.",
         ]),
         ("If this is not decided at all", [
            "- Reporting and security stay blocked, which is the correct "
            "behaviour, and no report may be issued.",
         ])])


# ---------------------------------------------------------------------------
# H00 - repository identity
# ---------------------------------------------------------------------------

def _h00_evidence(baseline: Mapping[str, Any]) -> str:
    rows = [[key, baseline[key], "measured from the repository during WP-C00"]
            for key in sorted(baseline)]
    return render_csv(["fact", "value", "read_from"], rows)


def _h00_proposals(baseline: Mapping[str, Any]) -> str:
    rows = [
        ["H00-D01", "the author identity on the baseline commit",
         "%s <%s>" % (baseline["author_name"], baseline["author_email"]),
         _PENDING, "CONFIRM_THIS_IS_THE_INTENDED_PROJECT_IDENTITY",
         "The repository had no configured Git identity. This one was "
         "supplied for this wave and is now written into the baseline "
         "commit and tag, where it cannot be changed without rewriting "
         "history.", "repository owner"],
        ["H00-D02", "the baseline tag as the closure starting point",
         baseline["tag"], _PENDING,
         "CONFIRM_THE_BASELINE_IS_THE_REFERENCE_FOR_ALL_CLOSURE_EVIDENCE",
         "Every later closure artifact is described relative to this "
         "commit. If the wrong tree was frozen, everything downstream "
         "describes the wrong thing.", "repository owner"],
        ["H00-D03", "publishing to a remote",
         "no remote is configured", _PENDING,
         "DECIDE_WHETHER_AND_WHERE_THIS_REPOSITORY_IS_PUBLISHED",
         "The repository is local only. Nothing has been pushed and nothing "
         "will be without an explicit instruction. The tree contains "
         "quarantined legacy data and unapproved source material, so where "
         "it may be published is a real question rather than a formality.",
         "repository owner"],
        ["H00-D04", "the quarantined legacy dataset in the committed tree",
         "committed, labelled QUARANTINED", _PENDING,
         "CONFIRM_THE_QUARANTINED_DATA_MAY_REMAIN_IN_THE_COMMITTED_TREE",
         "The legacy evidence build is in the baseline commit. It is "
         "labelled and nothing promotes it, but it was acquired before any "
         "source policy existed - which is decision H01-D04's subject.",
         "repository owner, with the source policy approver"],
    ]
    return render_csv(
        ["decision_id", "subject", "current_state", "target_status",
         "proposed_disposition", "rationale", "decision_owner"], rows)


def _h00_context(baseline: Mapping[str, Any]) -> str:
    return _document(
        "H00 - repository identity: what has to be decided",
        "Before WP-C00 this repository had no commit, no tag, no configured "
        "author and no version anything could reference. A release bundle "
        "cannot name a software version that does not exist, so the first "
        "thing the closure needed was a starting point that could be pointed "
        "at. That now exists. What it does not yet have is anybody's "
        "confirmation that it is the right one.",
        [
            ("What was created", [
                "| Field | Value |",
                "| --- | --- |",
                "| Baseline commit | `%s` |" % baseline["commit"],
                "| Tree | `%s` |" % baseline["tree"],
                "| Tag | `%s` |" % baseline["tag"],
                "| Files | %s |" % baseline["file_count"],
                "| Author | %s |" % baseline["author_name"],
                "| Remotes | %s |" % baseline["remote_count"],
                "",
                "The commit was built from an explicit list of paths, never "
                "from `git add .`, and the staged set was scanned for "
                "secrets and for absolute paths before it was written.",
            ]),
            ("Why an identity is a decision", [
                "An author identity on a commit is a claim about who made "
                "it, and it is written into the object hash. Changing it "
                "later means rewriting history. The identity used here was "
                "supplied for this wave; whether it is the identity this "
                "project should carry is not something a maintainer should "
                "assume.",
            ]),
            ("Why publication is a separate decision", [
                "The tree contains a quarantined legacy dataset and material "
                "acquired before any source policy existed. Where such a "
                "repository may be published is exactly the sort of question "
                "that should be asked before the first push rather than "
                "after it. No remote is configured and nothing has been "
                "pushed.",
            ]),
        ])


def _h00_questions() -> str:
    return _document(
        "H00 - unresolved questions",
        "The baseline exists and is measured. These are the things about it "
        "that a person still has to settle.",
        [("Open", [
            "- Is the author identity on the baseline commit the identity "
            "this project should carry? It cannot be changed without "
            "rewriting history.",
            "- Where, if anywhere, is this repository published? The answer "
            "interacts with the quarantined data in the tree.",
            "- Does the version the baseline tag names match how this "
            "project intends to number releases?",
            "- Three files under `docs/examples/wp04/` record a "
            "session-scoped cache path from the machine that produced them. "
            "They are recorded drill output with a content hash and were "
            "committed unmodified rather than edited after the fact. Should "
            "the producer scrub that field before writing, and should the "
            "existing files be regenerated?",
         ])])


def _h00_risks() -> str:
    return _document(
        "H00 - risk summary",
        "A baseline is load-bearing in a quiet way: everything after it is "
        "described relative to it, so an error here is inherited by every "
        "later artifact rather than being visible on its own.",
        [("If this is decided wrongly", [
            "- **The wrong identity is now in history.** Correcting it means "
            "rewriting every object that descends from the baseline.",
            "- **The wrong tree was frozen.** Every closure artifact "
            "afterwards describes a starting point nobody meant.",
            "- **Publication without a decision.** A push would put "
            "quarantined legacy data and material acquired under "
            "undetermined terms wherever it was pushed to, and a push cannot "
            "be taken back.",
         ]),
         ("If this is not decided at all", [
            "- Less than the others. The baseline works as a reference "
            "whether or not anybody has confirmed it. The risk is that it is "
            "confirmed implicitly, by everything downstream depending on it, "
            "rather than deliberately.",
         ])])


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

CHECKPOINTS: Tuple[Dict[str, Any], ...] = (
    {
        "id": "H00-repository-identity",
        "title": "repository identity and baseline",
        "owner": "repository owner",
        "not_owner": "a maintainer acting alone; the identity is written "
                     "into history",
        "blocks": ["release bundle versioning", "any push to a remote"],
        "depends_on": [],
        "summary": "A baseline commit, tree and tag now exist and are "
                   "measured. What is open is whether they are the ones this "
                   "project meant, and where - if anywhere - this repository "
                   "is published.",
        "not_covered": [
            "This does not approve any source, protocol or claim.",
            "This does not authorise a push. Publication is decision "
            "`H00-D03` and needs an explicit destination.",
            "This does not clear the quarantined legacy dataset for any use.",
        ],
    },
    {
        "id": "H01-source-policy",
        "title": "scientific source policy",
        "owner": "source policy approver, with legal counsel on the "
                 "conflicting terms",
        "not_owner": "a maintainer; these are readings of licences and "
                     "jurisdictional judgements",
        "blocks": ["all acquisition", "curated interpretation", "rule "
                   "creation", "release activation"],
        "depends_on": [],
        "summary": "Twenty registered sources, all `PENDING_REVIEW`, every "
                   "reuse dimension `UNKNOWN`. Eight were researched against "
                   "primary documents this wave; twelve are proposed for "
                   "deferral because the first release does not need them. "
                   "Four carry conflicts that a maintainer must not resolve.",
        "not_covered": [
            "This does not approve any scientific conclusion drawn from an "
            "approved source.",
            "This does not decide the curation protocol (H02) or the claims "
            "boundary (H03).",
            "Approving a source for acquisition does not approve "
            "republishing its text.",
            "This does not retrospectively authorise the evidence build "
            "already acquired through `clinpgx.api`; that is decision "
            "`H01-D04`'s subject and stays open.",
        ],
    },
    {
        "id": "H02-curation-protocol",
        "title": "curation protocol and scientific scope",
        "owner": "curation protocol approver and clinical pharmacogenomics "
                 "reviewer",
        "not_owner": "a maintainer; the protocol says explicitly that owning "
                     "it is not approving the science it governs",
        "blocks": ["every curated interpretation", "rule creation",
                   "validation"],
        "depends_on": ["H01-source-policy, for anything to curate from"],
        "summary": "The protocol declares itself draft and its `approval` "
                   "field is null. Beyond approving it, five places were "
                   "found where the primary sources do not fit the shape the "
                   "project has described its scope in, and the protocol is "
                   "silent on all five.",
        "not_covered": [
            "This does not approve any individual curated interpretation.",
            "This does not make a legacy candidate eligible for rule "
            "creation.",
            "This does not approve the claims boundary (H03).",
        ],
    },
    {
        "id": "H04-dataset-quality-decision",
        "title": "dataset quality decision mechanism and its first decision",
        "owner": "a named data owner",
        "not_owner": "the quality report, which reports numbers and decides "
                     "nothing",
        "blocks": ["dataset publication", "release activation"],
        "depends_on": ["a non-legacy dataset, which WP-C05 has not produced"],
        "summary": "WP-07 already carried the transition an approval causes. "
                   "What was missing was the decision: no verdict field, so "
                   "no way to record a rejection; no reviewer role; no "
                   "binding to the source policy. Wave 2 implemented those "
                   "and left the working parts alone. Nobody has been named "
                   "as data owner and there is no legitimate dataset to "
                   "decide about.",
        "not_covered": [
            "This does not approve any dataset; none is eligible.",
            "A passing quality gate is a precondition for a decision, never "
            "a decision.",
            "This does not approve any source (H01), protocol (H02) or "
            "claim (H03).",
        ],
    },
    {
        "id": "H03-claims-boundary",
        "title": "claims boundary and clinical warning",
        "owner": "clinical and legal approver, jointly",
        "not_owner": "a maintainer; this is what the platform is permitted "
                     "to say",
        "blocks": ["report issuance", "the security gate", "release "
                   "activation"],
        "depends_on": [],
        "summary": "The boundary is written and enforced literally by code, "
                   "at version 0.1.0-draft, and declares itself awaiting "
                   "human and scientific review. What is approved is the "
                   "exact wording and the exact lists, because that is what "
                   "the scanner compares.",
        "not_covered": [
            "This does not approve clinical use. Only demonstration and "
            "validation modes exist.",
            "This does not approve any particular output, only the limits "
            "outputs must stay inside.",
            "This does not approve any source (H01) or curated "
            "interpretation (H02).",
        ],
    },
)


def build_all(root: str, baseline: Mapping[str, Any]) -> Dict[str, str]:
    """Every checkpoint file, as ``relative path -> text``."""
    def read(*parts: str) -> Dict[str, Any]:
        path = os.path.join(root, *parts)
        with io.open(path, encoding="utf-8") as handle:
            return json.load(handle)

    registry = read("config", "scientific-sources.json")
    protocol = read("config", "curation", "protocol-v1.json")
    dispositions = read("data", "closure",
                        "wp-c00-legacy-candidate-dispositions.json")
    from pgx.domain.claims import DEFAULT_CLAIM_BOUNDARY as _boundary
    boundary = {
        "status": _boundary.status,
        "version": _boundary.version,
        "phase": str(getattr(_boundary.phase, "value", _boundary.phase)),
        "enabled_modes": sorted(str(getattr(item, "value", item))
                                for item in _boundary.enabled_modes),
        "permitted_input_kinds": sorted(
            str(getattr(item, "value", item))
            for item in _boundary.permitted_input_kinds),
        "prohibited_categories": sorted(
            str(getattr(item, "value", item))
            for item in _boundary.prohibited_categories),
        "warning_languages": sorted(_boundary.warning_by_language),
    }

    bodies = {
        "H00-repository-identity": {
            "decision-context.md": _h00_context(baseline),
            "evidence-table.csv": _h00_evidence(baseline),
            "proposed-decisions.csv": _h00_proposals(baseline),
            "unresolved-questions.md": _h00_questions(),
            "risk-summary.md": _h00_risks(),
        },
        "H01-source-policy": {
            "decision-context.md": _h01_context(),
            "evidence-table.csv": _h01_evidence(registry),
            "proposed-decisions.csv": _h01_proposals(registry),
            "unresolved-questions.md": _h01_questions(),
            "risk-summary.md": _h01_risks(),
        },
        "H02-curation-protocol": {
            "decision-context.md": _h02_context(),
            "evidence-table.csv": _h02_evidence(protocol, dispositions),
            "clinical-review-table.csv": _h02_review_table(),
            "proposed-decisions.csv": _h02_proposals({
                "protocol": str(protocol.get("content_hash") or ""),
                "dispositions": str(dispositions.get("content_hash") or ""),
            }),
            "unresolved-questions.md": _h02_questions(),
            "risk-summary.md": _h02_risks(),
        },
        "H04-dataset-quality-decision": {
            "decision-context.md": _h04_context(),
            "evidence-table.csv": _h04_evidence(),
            "proposed-decisions.csv": _h04_proposals(),
            "unresolved-questions.md": _h04_questions(),
            "risk-summary.md": _h04_risks(),
        },
        "H03-claims-boundary": {
            "decision-context.md": _h03_context(boundary),
            "evidence-table.csv": _h03_evidence(boundary),
            "proposed-decisions.csv": _h03_proposals(boundary),
            "unresolved-questions.md": _h03_questions(),
            "risk-summary.md": _h03_risks(),
        },
    }

    files: Dict[str, str] = {}
    for checkpoint in CHECKPOINTS:
        directory = "docs/closure/checkpoints/%s" % checkpoint["id"]
        files["%s/README.md" % directory] = _readme(checkpoint)
        files["%s/approval-form.md" % directory] = _approval_form(checkpoint)
        for name, text in bodies[checkpoint["id"]].items():
            files["%s/%s" % (directory, name)] = text
    files["docs/closure/checkpoints/README.md"] = _index(root)
    return files


def _decided(root: str, checkpoint_id: str) -> bool:
    """Has a person filled this checkpoint's form in?

    Compared against the blank template rather than scanned for words like
    "approved": the template offers APPROVED as one of the verdicts to
    choose, so a substring rule would match its own instructions.
    """
    path = os.path.join(root, "docs", "closure", "checkpoints", checkpoint_id,
                        "approval-form.md")
    if not os.path.isfile(path):
        return False
    with io.open(path, encoding="utf-8") as handle:
        current = handle.read()
    blank = next(_approval_form(item) for item in CHECKPOINTS
                 if item["id"] == checkpoint_id)
    return current != blank


def _index(root: str = ".") -> str:
    decided = {item["id"]: _decided(root, item["id"])
               for item in CHECKPOINTS}
    outstanding = sum(1 for value in decided.values() if not value)
    lines = [
        "# Human decision checkpoints",
        "",
        "> **Current execution-policy notice (2026-09-06):** These packages "
        "are preserved historical review/audit inputs. Missing intermediate "
        "external signatures no longer block candidate construction. Their "
        "open questions must be resolved through transparent internal "
        "decision records and remain pending the final whole-project external "
        "expert evaluation. See `../current-execution-policy.md`.",
        "",
        "%d checkpoint packages were created under the original policy. "
        "%d of them %s a recorded human decision; %d %s unsigned."
        % (len(CHECKPOINTS), len(CHECKPOINTS) - outstanding,
           "carries" if len(CHECKPOINTS) - outstanding == 1 else "carry",
           outstanding, "is" if outstanding == 1 else "are"),
        "",
        "| Checkpoint | Decision | Original owner | Original downstream effect | Decided |",
        "| --- | --- | --- | --- | :---: |",
    ]
    for checkpoint in CHECKPOINTS:
        lines.append("| [`%s`](%s/README.md) | %s | %s | %s | %s |"
                     % (checkpoint["id"], checkpoint["id"],
                        checkpoint["title"], checkpoint["owner"],
                        ", ".join(checkpoint["blocks"]),
                        "yes" if decided[checkpoint["id"]] else "no"))
    lines += [
        "",
        "Each package holds the same seven files: a README, the decision "
        "context, an evidence table citing where each fact was read, the "
        "proposed decisions, the unresolved questions, a risk summary, and an "
        "approval form.",
        "",
        "**The `proposed-decisions.csv` files record what the project "
        "proposed, not what was decided.** Every row in them stays "
        "`PENDING_REVIEW`; a decision lives in that checkpoint's approval "
        "form and, where one has been recorded, in a decision record under "
        "`data/closure/`. An approval form that is still blank is not an "
        "approval and no automated process may read it as one.",
        "",
        "Generated by `scripts/build_closure_wave01_checkpoints.py`. Edit "
        "the producer, not these files - except `approval-form.md`, which a "
        "reviewer fills in by hand and which the producer will not overwrite "
        "once it stops being blank.",
        "",
    ]
    return "\n".join(lines).rstrip("\n") + "\n"


# ---------------------------------------------------------------------------
# H04 - dataset quality decision (WP-C06)
# ---------------------------------------------------------------------------

#: The WP-C06 audit, as data. Each row is one requirement, what the repository
#: already had, whether it had been executed, what was actually missing, and
#: what Wave 2 did about it. Rows where the existing implementation was
#: sufficient say so: the instruction was to implement only proven gaps, and
#: a table that claimed everything was missing would have justified rewriting
#: machinery that already worked.
WP_C06_AUDIT: Tuple[Tuple[str, str, str, str, str], ...] = (
    ("explicit APPROVED/REJECTED decision semantics",
     "none - QualityCheckRequest carries no verdict field",
     "not executed",
     "a rejection could not be expressed at all, so the only recordable "
     "outcome was approval",
     "IMPLEMENTED: QualityDecision with exactly two values, and "
     "permits_transition false for REJECTED"),
    ("dataset id",
     "QualityCheckRequest.dataset_public_id, guarded against the manifest",
     "exercised by tests/unit/normalization/test_quality_transition.py",
     "nothing", "REUSED"),
    ("named reviewer identity",
     "QualityCheckRequest.reviewed_by, required, no default",
     "exercised", "nothing", "REUSED"),
    ("reviewer role",
     "none - only a name string is recorded",
     "not executed",
     "who the reviewer was speaking as was not recorded, so a name could not "
     "be checked against an authority",
     "IMPLEMENTED: reviewer_role, required, no default"),
    ("rationale", "QualityCheckRequest.rationale, required", "exercised",
     "nothing", "REUSED"),
    ("decision timestamp",
     "QualityCheckRequest.reviewed_at, required", "exercised",
     "no timezone requirement", "IMPLEMENTED: a naive instant is refused"),
    ("exact DQ artifact hash",
     "read from the build and written into the audit event",
     "exercised",
     "it was recorded but not bound - nothing re-checked it later",
     "IMPLEMENTED: dq_artifact_hash is bound and re-measured on use"),
    ("exact source-policy hash",
     "none - the snapshot manifest has source_policy_content_hash, the "
     "quality decision has nothing",
     "not executed",
     "a decision could not say which source policy was in force when the "
     "data it approves was acquired",
     "IMPLEMENTED: source_policy_hash, bound and re-measured"),
    ("immutable / audited storage",
     "AuditEvent DATASET_QUALITY_CHECKED through the unit of work",
     "exercised with a fake unit of work; never against a real database",
     "the audit row lives only in a database nobody here can reach, so there "
     "was no durable record in the repository",
     "IMPLEMENTED: an append-only NDJSON ledger beside the data, in addition "
     "to the audit event"),
    ("replay / idempotency refusal",
     "expected_current_state guard, applied inside the transaction",
     "exercised",
     "the guard refuses a second transition but not a second decision",
     "IMPLEMENTED: a second verdict on the same dataset and report is "
     "refused and names the standing decision"),
    ("stale-hash refusal",
     "verify_build, compare_with_artifacts and schema validation before the "
     "transaction opens",
     "exercised",
     "these check the build against itself, not a decision against the build",
     "IMPLEMENTED: a decision whose bound digests no longer match is refused "
     "and the problem names both halves"),
    ("rejected-decision behaviour", "none", "not executed",
     "there was no rejection path",
     "IMPLEMENTED: recorded, audited, transitions nothing, and the record "
     "says the dataset is not release-eligible"),
    ("authorization boundary",
     "the service refuses to invent a reviewer; the CLI states it cannot "
     "record a decision",
     "exercised",
     "no role or authority check, because no role was recorded",
     "PARTIAL: the role is now recorded; checking it against an authority "
     "needs the WP-23 role assignments, which are empty by design"),
    ("dataset lifecycle wiring",
     "CanonicalDatasetService.record_quality_check performs BUILDING -> "
     "QUALITY_CHECKED",
     "exercised with a fake unit of work",
     "nothing connected a decision to it",
     "IMPLEMENTED: record_dataset_quality_decision records first, then "
     "attempts the existing transition only for an approval"),
    ("database persistence",
     "the unit of work writes the row and the audit event", "never executed",
     "no PostgreSQL driver is installable in either available environment",
     "BLOCKED_BY_EXTERNAL_ACCESS: the path exists and is unit-tested; it has "
     "not been run against a real database"),
    ("operator CLI / API path",
     "pgx-normalize quality-gate reports the gate and says it cannot record "
     "a decision",
     "exercised",
     "there was no command that could record one",
     "NOT IMPLEMENTED IN THIS WAVE: a command that records a real decision "
     "should not be added before a real dataset and a named data owner "
     "exist. The service is callable and tested; the operator surface is a "
     "deliberate gap, named here rather than filled with a stub."),
    ("machine-readable decision artifact", "none", "not executed",
     "the audit event was the only record and it is not in the repository",
     "IMPLEMENTED: data/canonical/dataset-quality-decisions.ndjson"),
    ("human-readable review record", "none", "not executed",
     "nothing rendered the ledger for a reader",
     "IMPLEMENTED: render_review_record, and this checkpoint package"),
)


def _h04_evidence() -> str:
    return render_csv(
        ["requirement", "existing_implementation", "executed_evidence",
         "missing_piece", "action"],
        [list(row) for row in WP_C06_AUDIT])


def _h04_proposals() -> str:
    rows = [
        ["H04-D01", "who may record a dataset quality decision",
         "nobody is named", _PENDING,
         "NAME_THE_DATA_OWNER_AND_THEIR_ROLE",
         "The mechanism requires a reviewer name and a role and invents "
         "neither. Until a person is named, no decision can be recorded at "
         "all.", "repository owner, naming a data owner"],
        ["H04-D02", "the dataset a first decision would be about",
         "none exists", _PENDING,
         "AWAIT_A_NON_LEGACY_DATASET",
         "The only dataset in this repository is the quarantined legacy "
         "build, which must never be promoted. WP-C05 has not produced a "
         "replacement, so there is nothing legitimate to decide about.",
         "whoever completes the acquisition"],
        ["H04-D03", "whether a role check is required before recording",
         "role is recorded but not checked", _PENDING,
         "DECIDE_WHETHER_AN_AUTHORITY_CHECK_IS_REQUIRED",
         "WP-23's production role assignment set is empty by design, so "
         "there is nothing to check a role against yet. Whether a decision "
         "may be recorded before that exists is a governance choice.",
         "repository owner"],
        ["H04-D04", "what a rejection obliges",
         "recorded, transitions nothing", _PENDING,
         "CONFIRM_THE_REJECTION_SEMANTICS",
         "A rejection is recorded and moves nothing. Whether it should also "
         "close the build, require a new build key, or permit a later "
         "approval of the same report is not decided.",
         "data owner, with the repository owner"],
    ]
    return render_csv(
        ["decision_id", "subject", "current_state", "target_status",
         "proposed_disposition", "rationale", "decision_owner"], rows)


def _h04_context() -> str:
    return _document(
        "H04 - dataset quality decision: what has to be decided",
        "A dataset does not become usable because a report says its numbers "
        "are fine. Somebody has to read the report and decide, and this "
        "checkpoint is where that decision is recorded. WP-C06 asked for the "
        "mechanism; Wave 2 audited what already existed, implemented the "
        "parts that were genuinely missing, and left the rest alone.",
        [
            ("What already worked", [
                "WP-07 has carried the transition a decision causes since it "
                "was written: `BUILDING -> QUALITY_CHECKED`, guarded inside "
                "the transaction, refusing a replay, verifying the build's "
                "digests and its schemas before opening one, and refusing to "
                "invent a reviewer. None of that was rebuilt.",
            ]),
            ("What was missing", [
                "The decision itself. `QualityCheckRequest` has no verdict "
                "field, so the only outcome it could express was approval - "
                "a data owner who read the report and said no had nowhere to "
                "put that. Nothing recorded the reviewer's role, nothing "
                "bound the decision to the source policy in force, and the "
                "only record of a decision was an audit row in a database "
                "nobody in this environment can reach.",
                "",
                "The full audit is `evidence-table.csv`, one row per "
                "requirement, including the rows where the answer was that "
                "nothing was missing.",
            ]),
            ("What is decided here", [
                "Not the quality of any dataset - there is no legitimate "
                "dataset to decide about yet. What this checkpoint needs "
                "first is a named data owner and a decision about whether a "
                "role may be recorded before there is any authority to check "
                "it against.",
            ]),
        ])


def _h04_questions() -> str:
    return _document(
        "H04 - unresolved questions",
        "The mechanism is implemented and tested. What is open is who uses "
        "it, on what, and under what authority.",
        [("Open", [
            "- Who is the data owner? The mechanism requires a name and a "
            "role and will not supply either.",
            "- May a decision be recorded while WP-23's role assignment set "
            "is empty, so that the recorded role can be checked against "
            "nothing?",
            "- After a rejection, may the same report be approved later, or "
            "does a rejection require a new build?",
            "- Should the ledger live beside the data, in the database, or "
            "both? It is currently a file, because the database is not "
            "reachable from either environment here and a decision that "
            "exists only in an unreachable database is not evidence.",
            "- Does a decision expire? A source policy read once is not a "
            "policy forever, and the same argument applies to a dataset "
            "somebody approved a year ago.",
         ])])


def _h04_risks() -> str:
    return _document(
        "H04 - risk summary",
        "This is the control that stops a generated report from becoming an "
        "approval by default.",
        [("If this is decided wrongly", [
            "- **A passing gate read as an approval.** The report says the "
            "numbers are within contract. It says nothing about whether the "
            "data should be used, and the two are easy to conflate.",
            "- **A decision nobody can attribute.** A name with no role "
            "behind it cannot be checked against any authority, and reads as "
            "accountability without being it.",
            "- **A silent rejection.** A system where saying no leaves no "
            "trace shows only approvals, which makes the record of decisions "
            "systematically optimistic.",
            "- **An approval that outlived its subject.** A regenerated "
            "report is a different report; the binding exists so an old "
            "approval cannot quietly attach to it.",
         ]),
         ("If this is not decided at all", [
            "- No dataset can become `QUALITY_CHECKED`, so none can be "
            "published, so no release can be activated. That is the current "
            "state and it is correct: there is no legitimate dataset to "
            "decide about.",
         ])])
