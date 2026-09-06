#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Register the CPIC guideline capture interface in the source registry.

**Registered, not approved.** The record is written with
``status: PENDING_REVIEW`` and ``review: null``, and it stays that way.

The reason is exact. H01 is a real human source-policy decision by a named
pharmacist, and its recorded outcome for ``cpic.database`` permits
``MANUAL_DOWNLOAD`` and ``INTERNAL_DERIVATION`` and nothing else, under the
condition "manual review and citation only". Its prohibited-mode list includes
"expanding the approved source set by implication". An agent reading published
pages is not a manual download, and ``AGENT_TARGETED_RETRIEVAL`` did not exist
when that decision was made, so nothing in H01 authorises it. Writing an
approving status here - or synthesising a ``ReviewRecord``, whose docstring
says every field is "a thing a forged approval would have to invent" - would
extend a named person's decision past the scope they actually recorded.

What registration *does* accomplish is worth having on its own: the project now
knows and has verified real things about this interface - the CC0-1.0
dedication quoted from CPIC's own LICENSE.md, the robots directives, the fact
that the API's terms could not be read - and a registry that holds none of that
would let the next wave rediscover it or, worse, guess. It also changes the
data-quality report's answer from "no source policy is on record" to "the
source policy is not approved", which is the more precise of the two truths.
"""

from __future__ import annotations

import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pgx.closure.source_grounding import LICENCE_BASES, RETRIEVALS  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY = os.path.join(REPO, "config", "scientific-sources.json")

SOURCE_KEY = "cpic.guideline-capture"

_CC0 = [b for b in LICENCE_BASES if b.basis_key == "cpic.cc0"][0]
_BOUND = sorted(RETRIEVALS, key=lambda r: r.retrieval_key)[0].observed_not_later_than


def record() -> dict:
    return {
        "source_key": SOURCE_KEY,
        "display_name": ("CPIC guideline recommendation tables, read one "
                         "document at a time via the ClinPGx public pages"),
        "role": "PRIMARY_GUIDELINE",
        "status": "PENDING_REVIEW",
        "acquisition_mode": "AGENT_TARGETED_RETRIEVAL",
        "provider": "Clinical Pharmacogenetics Implementation Consortium",
        "jurisdiction": None,
        "version_policy": ("each retrieval records the guideline's own version "
                           "label and the annotation identifier it was read "
                           "from; no version is inferred"),
        "citation_policy": ("cite the CPIC guideline publication by PMID and "
                            "DOI and name the ClinPGx annotation identifier "
                            "the rows were read from"),
        "license_identifier": _CC0.licence_identifier,
        "reuse": {
            "LOCAL_STORAGE": "ALLOWED",
            "INTERNAL_ANALYSIS": "ALLOWED",
            "DERIVED_WORK_CREATION": "ALLOWED",
            "AGGREGATED_REDISTRIBUTION": "ALLOWED",
            "VERBATIM_REDISTRIBUTION": "ALLOWED",
            "COMMERCIAL_USE": "ALLOWED",
            # Not a licence question. The CC0 dedication covers reuse of the
            # content and says nothing about how it may be obtained, and H01
            # prohibits both of these outright for every source.
            "AUTOMATED_ACQUISITION": "PROHIBITED",
            "BULK_DOWNLOAD": "PROHIBITED",
            "THIRD_PARTY_SHARING": "ALLOWED",
            "PUBLIC_DISPLAY": "ALLOWED",
        },
        # Empty, and it must stay empty while the record is unapproved: a
        # category list is a statement about what a source has been cleared
        # for, and this one has been cleared for nothing.
        "permitted_claim_categories": [],
        "evidence": [
            {
                "evidence_type": "OFFICIAL_LICENSE_FILE",
                "official_url": _CC0.evidence_url,
                "retrieved_at": _BOUND,
                "content_hash": None,
                "summary": ("CPIC's own LICENSE.md: %r. Retrieved by this "
                            "project. content_hash is null because the "
                            "retrieval preserved rendered text rather than "
                            "the response body, so no byte-level digest of "
                            "what the server served exists."
                            % _CC0.statement_verbatim),
                "verification": "VERIFIED",
                "blocked_reason": None,
            },
            {
                "evidence_type": "OFFICIAL_TERMS_PAGE",
                "official_url": "https://www.clinpgx.org/robots.txt",
                "retrieved_at": _BOUND,
                "content_hash": None,
                "summary": ("Disallows only /literature/, and only for "
                            "SiteimproveBot. Nothing disallows the guideline "
                            "or guidelineAnnotation paths that were read, and "
                            "/literature/ was not fetched."),
                "verification": "VERIFIED",
                "blocked_reason": None,
            },
            {
                "evidence_type": "OFFICIAL_API_DOCUMENTATION",
                "official_url": "https://api.clinpgx.org",
                "retrieved_at": None,
                "content_hash": None,
                "summary": None,
                "verification": "BLOCKED",
                "blocked_reason": ("the API's terms could not be read, so the "
                                   "interface may not be called. An interface "
                                   "whose terms are unknown has no "
                                   "permissions rather than unlimited ones."),
            },
        ],
        "interpretation": {
            "summary": ("Content reuse rests on CPIC's CC0-1.0 dedication, "
                        "quoted verbatim from CPIC's own LICENSE.md. The "
                        "manner of acquisition rests on nothing yet: no human "
                        "decision authorises AGENT_TARGETED_RETRIEVAL for any "
                        "source, and H01's recorded outcome for cpic.database "
                        "permits MANUAL_DOWNLOAD and INTERNAL_DERIVATION only, "
                        "under the condition 'manual review and citation "
                        "only'. This record therefore registers what was done "
                        "and does not claim it was permitted."),
            "interpreted_by": ("pgx-closure-wave03b automated pass "
                               "(NOT A HUMAN REVIEWER)"),
            "interpreted_at": _BOUND,
        },
        "review": None,
        "legacy_aliases": [],
        "blocking_reasons": [
            "No named human reviewer has made a decision about this record.",
            "The acquisition mode AGENT_TARGETED_RETRIEVAL is not among the "
            "modes H01 permitted for any source, and H01 prohibits expanding "
            "the approved source set by implication.",
            "No byte-level hash of any retrieved document exists, so the "
            "evidence pins this project's transcription rather than the "
            "publisher's response.",
        ],
        "notes": ("Registered by Wave 3B so the project's verified knowledge "
                  "of this interface is recorded rather than rediscovered. "
                  "Registration is not approval."),
        "active": True,
    }


def main() -> int:
    with io.open(REGISTRY, encoding="utf-8") as handle:
        registry = json.load(handle)
    keys = [item["source_key"] for item in registry["sources"]]
    if SOURCE_KEY in keys:
        sys.stdout.write("%s is already registered\n" % SOURCE_KEY)
        return 0
    registry["sources"].append(record())
    registry["sources"].sort(key=lambda item: item["source_key"])
    text = json.dumps(registry, indent=2, sort_keys=False,
                      ensure_ascii=False) + "\n"
    with io.open(REGISTRY, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    sys.stdout.write("registered %s as PENDING_REVIEW (%d sources total)\n"
                     % (SOURCE_KEY, len(registry["sources"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
