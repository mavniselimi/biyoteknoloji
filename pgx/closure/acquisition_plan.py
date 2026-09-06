# -*- coding: utf-8 -*-
"""WP-C05: what may be acquired, by whom, and how.

The plan is derived from the recorded H01 decision and from nothing else. It
cannot be broader than that decision, and two properties are enforced rather
than intended: every source in the plan appears in the decision's approved
set, and every acquisition mode in the plan appears in that source's
permitted list.

**Nothing here acquires anything.** Every approved mode is manual - a person
downloads a document and puts it somewhere - so this module produces a matrix
and a checklist for that person. Automating a retrieval because it is small
would be substituting a mode nobody approved: a one-page fetch by a script is
still automated acquisition, and automated acquisition is prohibited for
every source in this plan.

The canonical entry points below are the interfaces the approval names. The
exact document and its version are for the operator to confirm at retrieval
time and to record with the checksum, because this project has not retrieved
them and must not write down a version it has not seen.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Tuple

from pgx.closure.h01_decision import SOURCE_OUTCOMES, build_decision
from pgx.closure.research_findings import FIRST_RELEASE_AXES

__all__ = ["ACQUISITION_PLAN_VERSION", "INTERFACES", "build_plan",
           "render_checklist"]

ACQUISITION_PLAN_VERSION = "pgx-wpc05-acquisition-plan/1"

#: Where the destination artifacts would go. One directory per source, so a
#: snapshot never mixes two sources under one key.
_DESTINATION = "data/raw/wp-c05/<new-dataset-id>/%s/"

#: What the approval names, per source. ``canonical_entry_point`` is the
#: interface the approval covers - not a deep link to a document this project
#: has not opened.
INTERFACES: Dict[str, Dict[str, Any]] = {
    "cpic.database": {
        "source_family": "CPIC",
        "approved_interface": "the published CPIC guideline database "
                              "distribution",
        "canonical_entry_point": "https://cpicpgx.org/",
        "version_identifier": "the distribution's own release identifier, to "
                              "be read at retrieval and recorded verbatim",
        "allowed_local_artifact": "the distributed structured data file as "
                                  "downloaded, unmodified",
        "citation_requirement": "cite CPIC as the source of every "
                                "recommendation derived from it, with the "
                                "recorded release identifier",
        "redistribution_limitation": "no verbatim redistribution; normalized "
                                     "internal derivation only",
        "intended_axes": list(FIRST_RELEASE_AXES),
    },
    "cpic.publications": {
        "source_family": "CPIC",
        "approved_interface": "the published guideline papers, read as "
                              "literature",
        "canonical_entry_point": "https://cpicpgx.org/guidelines/",
        "version_identifier": "the DOI and publication year of each "
                              "guideline consulted",
        "allowed_local_artifact": "a citation record only - author, title, "
                                  "journal, year, DOI. Not the article text.",
        "citation_requirement": "full citation with DOI",
        "redistribution_limitation": "full text is neither stored nor "
                                     "redistributed",
        "intended_axes": list(FIRST_RELEASE_AXES),
    },
    "clinpgx.website": {
        "source_family": "ClinPGx",
        "approved_interface": "the website, read manually by a person",
        "canonical_entry_point": "https://www.clinpgx.org/",
        "version_identifier": "the page's own last-updated date and the "
                              "retrieval instant",
        "allowed_local_artifact": "a normalized internal derivation and a "
                                  "citation record; not a copy of the page",
        "citation_requirement": "cite ClinPGx with the retrieval instant",
        "redistribution_limitation": "no redistribution of any kind; the "
                                     "source's own terms contradict "
                                     "themselves and the approval stays "
                                     "inside the intersection both readings "
                                     "permit",
        "intended_axes": list(FIRST_RELEASE_AXES),
    },
    "dpwg.knmp": {
        "source_family": "DPWG / KNMP",
        "approved_interface": "the official public scientific publications",
        "canonical_entry_point": "https://www.knmp.nl/",
        "version_identifier": "the publication identifier and date of each "
                              "recommendation consulted",
        "allowed_local_artifact": "a citation record only",
        "citation_requirement": "cite the DPWG recommendation and its "
                                "publication",
        "redistribution_limitation": "no reproduction of the G-Standaard or "
                                     "any licensed dataset; publications are "
                                     "cited, never redistributed",
        "intended_axes": list(FIRST_RELEASE_AXES),
    },
}


def build_plan(root: str = ".") -> Dict[str, Any]:
    """The matrix, derived from the recorded decision and checked against it."""
    decision = build_decision(root)
    approved = {item["source_key"]: item for item in SOURCE_OUTCOMES}

    rows: List[Dict[str, Any]] = []
    for source_key in sorted(INTERFACES):
        if source_key not in approved:
            raise ValueError(
                "%s is in the acquisition plan but not in the H01 approved "
                "set; a plan may never be broader than its approval"
                % source_key)
        outcome = approved[source_key]
        interface = INTERFACES[source_key]
        permitted = [mode for mode in outcome["permitted_acquisition_modes"]
                     if mode != "INTERNAL_DERIVATION"]
        for mode in permitted:
            if mode not in outcome["permitted_acquisition_modes"]:
                raise ValueError("%s: %s is not a permitted mode"
                                 % (source_key, mode))
        rows.append({
            "source_key": source_key,
            "source_family": interface["source_family"],
            "approved_interface": interface["approved_interface"],
            "canonical_entry_point": interface["canonical_entry_point"],
            "version_identifier": interface["version_identifier"],
            "permitted_acquisition_modes": permitted,
            "derivation_permitted": "INTERNAL_DERIVATION"
                                    in outcome["permitted_acquisition_modes"],
            "allowed_local_artifact": interface["allowed_local_artifact"],
            "prohibited_acquisition_modes":
                list(outcome["prohibited_acquisition_modes"]),
            "prohibited_reuse": list(outcome["prohibited_reuse"]),
            "citation_requirement": interface["citation_requirement"],
            "redistribution_limitation":
                interface["redistribution_limitation"],
            "intended_first_release_axes": interface["intended_axes"],
            "operator_action_required":
                "a person retrieves the document, records the URL, the "
                "retrieval instant in UTC, the version identifier and the "
                "SHA-256 of the bytes, and places it in the destination",
            "expected_destination": _DESTINATION % source_key.replace(".", "-"),
            "automation_permitted": False,
            "why_not_automated":
                "the approval permits manual retrieval only. A script "
                "fetching one page is still automated acquisition, which is "
                "prohibited for this source.",
        })

    payload: Dict[str, Any] = {
        "acquisition_plan_version": ACQUISITION_PLAN_VERSION,
        "work_package": "WP-C05",
        "derived_from": {
            "h01_decision_state": decision["state"],
            "h01_decision_content_hash": decision["content_hash"],
            "h01_reviewer": decision["reviewer"]["name"],
            "h01_decision": decision["reviewer"]["decision"],
        },
        "first_release_axes": list(FIRST_RELEASE_AXES),
        "acquisition_executed": False,
        "acquisition_executed_reason":
            "every approved mode is manual, so no acquisition may be "
            "performed by this project's software. What is produced here is "
            "the matrix and the checklist a person works through.",
        "dataset_identity": {
            "allocated": False,
            "note": "a new dataset id is allocated through the canonical "
                    "mechanism at the moment real material exists. The "
                    "quarantined legacy id PGX-DATA-20260830-900 is never "
                    "reused, relabelled or copied.",
        },
        "rows": rows,
        "prohibited_everywhere": list(decision["prohibited_modes"]),
        "note": "This plan grants nothing. It restates an approval already "
                "recorded and names what a person must do to act on it.",
    }
    payload["content_hash"] = "sha256:" + hashlib.sha256(json.dumps(
        payload, indent=2, sort_keys=True,
        ensure_ascii=False).encode("utf-8")).hexdigest()
    return payload


def render_checklist(payload: Dict[str, Any]) -> str:
    """The checklist, for the person who has to do the retrieving."""
    lines = [
        "# WP-C05 manual acquisition checklist",
        "",
        "Generated by `scripts/build_closure_wave02_acquisition.py` from the "
        "recorded H01 decision (`%s`). Do not edit by hand."
        % payload["derived_from"]["h01_decision_content_hash"],
        "",
        "**Nothing has been acquired.** %s"
        % payload["acquisition_executed_reason"],
        "",
        "## Before you start",
        "",
        "- Every retrieval below is **manual**. Do not script it, do not use "
        "an API client, do not bulk download. A small automated fetch is "
        "still automated acquisition and is not approved.",
        "- Do not bypass a robots policy, a rate limit, a login or a terms "
        "acceptance. If a source refuses, stop and record the refusal.",
        "- Record, for every file: the exact URL, the retrieval instant in "
        "UTC, the version identifier the source itself states, the content "
        "type, the SHA-256 of the bytes, and your own name as the operator.",
        "- The use approved is private, non-commercial research. Nothing "
        "retrieved here may be redistributed.",
        "",
        "## Per source",
        "",
    ]
    for row in payload["rows"]:
        lines += [
            "### `%s` — %s" % (row["source_key"], row["source_family"]),
            "",
            "| Field | Value |",
            "| --- | --- |",
            "| Approved interface | %s |" % row["approved_interface"],
            "| Entry point | %s |" % row["canonical_entry_point"],
            "| Version to record | %s |" % row["version_identifier"],
            "| Permitted mode | %s |"
            % ", ".join("`%s`" % mode
                        for mode in row["permitted_acquisition_modes"]),
            "| May be normalized internally | %s |"
            % ("yes" if row["derivation_permitted"] else "no"),
            "| What you may keep locally | %s |" % row["allowed_local_artifact"],
            "| Prohibited modes | %s |"
            % ", ".join("`%s`" % mode
                        for mode in row["prohibited_acquisition_modes"]),
            "| Citation | %s |" % row["citation_requirement"],
            "| Redistribution | %s |" % row["redistribution_limitation"],
            "| Put it in | `%s` |" % row["expected_destination"],
            "",
            "- [ ] retrieved manually",
            "- [ ] URL, UTC instant, version and SHA-256 recorded",
            "- [ ] placed in the destination above",
            "- [ ] operator name recorded",
            "",
        ]
    lines += [
        "## Never, for any source in this plan",
        "",
    ]
    for item in payload["prohibited_everywhere"]:
        lines.append("- %s" % item)
    lines += [
        "",
        "## After the retrievals",
        "",
        "Bring the files back and the software takes over: a new dataset id "
        "is allocated through the canonical mechanism, the raw snapshot is "
        "sealed and independently verified, canonicalization and the "
        "evidence build run, and the data-quality report is generated. None "
        "of that starts until real material exists, and the quarantined "
        "legacy dataset is never reused as a substitute for it.",
        "",
    ]
    return "\n".join(lines) + "\n"
