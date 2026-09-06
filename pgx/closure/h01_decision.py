# -*- coding: utf-8 -*-
"""The recorded human decision on H01, and what it does and does not license.

A person reviewed the H01 source-policy package and decided. This module
records that decision. It does not make one, and it cannot: every field here
was supplied by the reviewer or measured from the repository, and the two are
kept apart so a later reader can tell which is which.

**The binding is enforced, not asserted.** The reviewer attested to specific
bytes. This module re-measures those bytes every time it runs and refuses to
emit a recorded approval if they have changed - it emits an re-attestation
request instead, naming the old and new digests. An approval that silently
followed an edited evidence table would be worse than no approval, because it
would carry a real reviewer's name on content they never saw.

**What this decision is about.** The reviewer read this project's H01 package:
the evidence table, the proposed decisions, and the supporting documents. That
is a different act from reading each source's own terms page, and the
distinction matters downstream - see :data:`REGISTRY_READINESS_GAPS`, which
records what ``config/scientific-sources.json`` still needs before it can
carry this approval under its own rules.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from typing import Any, Dict, List, Mapping, Tuple

__all__ = [
    "CHECKPOINT",
    "DECISION_RECORD_VERSION",
    "DISPOSITIONS",
    "PROHIBITED_MODES",
    "REVIEWED_ARTIFACTS",
    "REVIEWED_HASHES",
    "REVIEWER",
    "SOURCE_OUTCOMES",
    "build_decision",
    "measure_hashes",
    "render_approval_form",
]

DECISION_RECORD_VERSION = "pgx-closure-human-decision/1"
CHECKPOINT = "H01-source-policy"

_PACKAGE = "docs/closure/checkpoints/H01-source-policy"

#: The two files whose content the decision is *about*. A change to either
#: invalidates the approval until a reviewer says otherwise.
REVIEWED_ARTIFACTS: Tuple[str, ...] = ("evidence-table.csv",
                                       "proposed-decisions.csv")

#: The supporting files the reviewer also read. A change here is reported but
#: does not by itself void the decision, because the decision was recorded
#: against the two files above.
SUPPORTING_ARTIFACTS: Tuple[str, ...] = ("decision-context.md",
                                         "unresolved-questions.md",
                                         "risk-summary.md")

#: What the reviewer attested to, exactly. Supplied with the attestation.
REVIEWED_HASHES: Dict[str, str] = {
    "evidence-table.csv":
        "7a87b5e9fe488d53abc7afaa1b77ea3b6ff013b3db5db60a6ebc28abae87c7c8",
    "proposed-decisions.csv":
        "4be498a25e819822343c85d9b8433abda2b26842b31d5e36481aa917ee23e0b2",
    "decision-context.md":
        "6301a248f6d4f498df54b4347b0c353a7ce150629e916dd3cd633e239456d39c",
    "unresolved-questions.md":
        "be31d352758d9a322c586b1fe7acaeb8ceb8a3b7f900ab1f433dbf7038ab8dcc",
    "risk-summary.md":
        "1356061cdeb9cf0e1e64af3fb914aa61551aa055d926422a0d460d5ee308a7d2",
}

#: The approval form's digest before this decision was written into it. Kept
#: so a reader can see the form changed for the reason it was supposed to.
APPROVAL_FORM_HASH_BEFORE = \
    "6d9b4c150c45385d1efee971693b83e4d02a79d3de0ac4766ce898821cfb01f1"

REVIEWER: Dict[str, str] = {
    "name": "Mehmet Yetiş",
    "qualification": "Pharmacist / Eczacı",
    "role_in_this_decision": "H01 scientific source policy reviewer",
    "decision_date_supplied_by_reviewer": "2026-09-06",
    "signature_text_supplied": "M.Yetiş",
    "signature_method": "TYPED_NAME",
    "provenance": "typed human attestation relayed to this repository by the "
                  "project owner",
    "identity_verification": "NONE_PERFORMED",
    "identity_verification_note":
        "No electronic identity verification was performed and this is not a "
        "cryptographic signature. What is recorded is that the project owner "
        "relayed a typed attestation naming this reviewer.",
    "decision": "APPROVED WITH CONDITIONS",
    "repository_decision_enum": "APPROVE_WITH_RESTRICTIONS",
    "repository_status_enum": "APPROVED_WITH_RESTRICTIONS",
}

#: The reviewer's own words. Preserved verbatim, in the language written.
ATTESTATION_VERBATIM = """Ben Mehmet Yetiş; eczacı olarak, H01 bilimsel kaynak politikası paketini,
evidence table'ı, proposed decisions dosyasını ve belirtilen SHA-256
hashlerini inceledim.
CPIC, ClinPGx ve DPWG kaynaklarının yalnızca formda belirtilen dar,
non-commercial, private araştırma ve citation/normalized-derivation koşulları
altında kullanılmasını APPROVED WITH CONDITIONS olarak onaylıyorum.
Bilinmeyen API koşullarına sahip otomatik erişimi, scraping'i, bulk download'ı
ve tam metin yeniden dağıtımını onaylamıyorum.
FDA, TITCK ve diğer kaynakların ilk release dışına ertelenmesini kabul
ediyorum.
Bu onay herhangi bir klinik öneriyi, kuralı, hasta kullanımını veya kaynak
metninin yeniden dağıtımını onaylamaz.
Ad soyad: Mehmet Yetiş
Mesleki yeterlilik: Eczacı
Tarih: 06/09/2026
İmza: M.Yetiş"""

#: The conditions the reviewer attached, in the project's own words. These are
#: what ``APPROVE_WITH_RESTRICTIONS`` requires a record to name.
RESTRICTIONS: Tuple[str, ...] = (
    "private, non-commercial research use only",
    "manual review and citation only; no automated access whose terms are "
    "unknown",
    "normalized internal derivation permitted; verbatim full-text "
    "redistribution is not",
    "no scraping, crawling or bulk download",
    "pre-existing legacy material derived from an approved source is not "
    "thereby provenance-approved and must pass the repository's own "
    "provenance and evidence checks independently",
)

#: What the reviewer did *not* approve. Written as its own list because a
#: reader looking for the boundary should not have to infer it from silence.
PROHIBITED_MODES: Tuple[str, ...] = (
    "OFFICIAL_API access to any source whose service terms remain unknown",
    "automated acquisition of any kind under unknown terms",
    "scraping or crawling any source",
    "bulk download of any source",
    "verbatim redistribution of publication or label full text",
    "commercial use of any approved source",
    "treating deferral of FDA or TITCK as evidence that a first-release axis "
    "is regulator-supported",
    "expanding the approved source set by implication",
)

#: One row per H01 decision, in the reviewer's mapping. ``registry_status``
#: is the vocabulary this repository already has; the reviewer's own wording
#: is kept beside it rather than turned into a new enum value.
_D = "H01-D%02d"
DISPOSITIONS: Tuple[Dict[str, str], ...] = (
    {"decision_id": _D % 1, "source_key": "aha.publications",
     "outcome": "ACCEPT_PROPOSED_DEFERRAL", "registry_status": "PENDING_REVIEW",
     "reviewer_wording": "accept proposed deferral"},
    {"decision_id": _D % 2, "source_key": "ausnz.publications",
     "outcome": "ACCEPT_PROPOSED_DEFERRAL", "registry_status": "PENDING_REVIEW",
     "reviewer_wording": "accept proposed deferral"},
    {"decision_id": _D % 3, "source_key": "clinpgx.api",
     "outcome": "DEFER_API_UNTIL_TERMS", "registry_status": "PENDING_REVIEW",
     "reviewer_wording": "approve only as DEFER_API_UNTIL_TERMS"},
    {"decision_id": _D % 4, "source_key": "clinpgx.website",
     "outcome": "APPROVE_MANUAL_PRIVATE_NONCOMMERCIAL_ONLY",
     "registry_status": "APPROVED_WITH_RESTRICTIONS",
     "reviewer_wording": "approve manual/private/non-commercial review and "
                         "citation only"},
    {"decision_id": _D % 5, "source_key": "cpic.api",
     "outcome": "DEFER_API_UNTIL_TERMS", "registry_status": "PENDING_REVIEW",
     "reviewer_wording": "change to DEFER_API_UNTIL_TERMS"},
    {"decision_id": _D % 6, "source_key": "cpic.database",
     "outcome": "APPROVE_WITH_LICENSE_ATTRIBUTION_DERIVATION_CONDITIONS",
     "registry_status": "APPROVED_WITH_RESTRICTIONS",
     "reviewer_wording": "approve with recorded license, attribution and "
                         "derivation conditions"},
    {"decision_id": _D % 7, "source_key": "cpic.publications",
     "outcome": "APPROVE_CITATION_AND_MANUAL_REVIEW_ONLY",
     "registry_status": "APPROVED_WITH_RESTRICTIONS",
     "reviewer_wording": "approve citation/manual review only; no full-text "
                         "redistribution"},
    {"decision_id": _D % 8, "source_key": "cpnds.publications",
     "outcome": "ACCEPT_PROPOSED_DEFERRAL", "registry_status": "PENDING_REVIEW",
     "reviewer_wording": "accept proposed deferral"},
    {"decision_id": _D % 9, "source_key": "dpwg.knmp",
     "outcome": "APPROVE_OFFICIAL_PUBLICATION_MANUAL_REVIEW_AND_CITATION_ONLY",
     "registry_status": "APPROVED_WITH_RESTRICTIONS",
     "reviewer_wording": "approve official-publication manual review and "
                         "citation only"},
    {"decision_id": _D % 10, "source_key": "druglabel.ema",
     "outcome": "ACCEPT_PROPOSED_DEFERRAL", "registry_status": "PENDING_REVIEW",
     "reviewer_wording": "accept proposed deferral"},
    {"decision_id": _D % 11, "source_key": "druglabel.fda",
     "outcome": "DEFER_OUTSIDE_FIRST_RELEASE_SCOPE",
     "registry_status": "PENDING_REVIEW",
     "reviewer_wording": "defer outside first-release scope"},
    {"decision_id": _D % 12, "source_key": "druglabel.hcsc",
     "outcome": "ACCEPT_PROPOSED_DEFERRAL", "registry_status": "PENDING_REVIEW",
     "reviewer_wording": "accept proposed deferral"},
    {"decision_id": _D % 13, "source_key": "druglabel.pmda",
     "outcome": "ACCEPT_PROPOSED_DEFERRAL", "registry_status": "PENDING_REVIEW",
     "reviewer_wording": "accept proposed deferral"},
    {"decision_id": _D % 14, "source_key": "druglabel.swissmedic",
     "outcome": "ACCEPT_PROPOSED_DEFERRAL", "registry_status": "PENDING_REVIEW",
     "reviewer_wording": "accept proposed deferral"},
    {"decision_id": _D % 15, "source_key": "druglabel.titck",
     "outcome": "DEFER_OUTSIDE_FIRST_RELEASE_SCOPE",
     "registry_status": "PENDING_REVIEW",
     "reviewer_wording": "defer outside first-release scope"},
    {"decision_id": _D % 16, "source_key": "internal.legacy_mvp_seed",
     "outcome": "ACCEPT_PROPOSED_DEFERRAL_NO_AUTOMATIC_PROVENANCE_APPROVAL",
     "registry_status": "PENDING_REVIEW",
     "reviewer_wording": "accept proposed deferral; no automatic provenance "
                         "approval"},
    {"decision_id": _D % 17, "source_key": "internal.legacy_probe_outputs",
     "outcome": "ACCEPT_PROPOSED_DEFERRAL_NO_AUTOMATIC_PROVENANCE_APPROVAL",
     "registry_status": "PENDING_REVIEW",
     "reviewer_wording": "accept proposed deferral; no automatic provenance "
                         "approval"},
    {"decision_id": _D % 18, "source_key": "internal.manual_normalization",
     "outcome": "ACCEPT_PROPOSED_DEFERRAL", "registry_status": "PENDING_REVIEW",
     "reviewer_wording": "accept proposed deferral"},
    {"decision_id": _D % 19, "source_key": "pubmed.literature",
     "outcome": "ACCEPT_PROPOSED_FIRST_RELEASE_DEFERRAL",
     "registry_status": "PENDING_REVIEW",
     "reviewer_wording": "accept proposed first-release deferral"},
    {"decision_id": _D % 20, "source_key": "rnpgx.publications",
     "outcome": "ACCEPT_PROPOSED_DEFERRAL", "registry_status": "PENDING_REVIEW",
     "reviewer_wording": "accept proposed deferral"},
)

#: For each source the reviewer approved: what may be done, in this project's
#: existing AcquisitionMode and ReuseDimension vocabulary.
SOURCE_OUTCOMES: Tuple[Dict[str, Any], ...] = (
    {
        "source_key": "cpic.database",
        "permitted_acquisition_modes": ["MANUAL_DOWNLOAD",
                                        "INTERNAL_DERIVATION"],
        "prohibited_acquisition_modes": ["OFFICIAL_API",
                                         "LICENSED_BULK_EXPORT"],
        "permitted_reuse": ["LOCAL_STORAGE", "INTERNAL_ANALYSIS",
                            "DERIVED_WORK_CREATION"],
        "prohibited_reuse": ["COMMERCIAL_USE", "AUTOMATED_ACQUISITION",
                             "BULK_DOWNLOAD", "VERBATIM_REDISTRIBUTION"],
        "condition": "recorded licence, attribution and derivation "
                     "conditions; private non-commercial research only",
    },
    {
        "source_key": "cpic.publications",
        "permitted_acquisition_modes": ["MANUAL_DOWNLOAD"],
        "prohibited_acquisition_modes": ["OFFICIAL_API",
                                         "LICENSED_BULK_EXPORT",
                                         "PUBLICATION_TRANSCRIPTION"],
        "permitted_reuse": ["LOCAL_STORAGE", "INTERNAL_ANALYSIS"],
        "prohibited_reuse": ["VERBATIM_REDISTRIBUTION", "COMMERCIAL_USE",
                             "AUTOMATED_ACQUISITION", "BULK_DOWNLOAD"],
        "condition": "citation and manual scientific review only; full text "
                     "is not redistributed",
    },
    {
        "source_key": "clinpgx.website",
        "permitted_acquisition_modes": ["MANUAL_DOWNLOAD",
                                        "INTERNAL_DERIVATION"],
        "prohibited_acquisition_modes": ["OFFICIAL_API",
                                         "LICENSED_BULK_EXPORT"],
        "permitted_reuse": ["LOCAL_STORAGE", "INTERNAL_ANALYSIS",
                            "DERIVED_WORK_CREATION"],
        "prohibited_reuse": ["COMMERCIAL_USE", "AUTOMATED_ACQUISITION",
                             "BULK_DOWNLOAD", "VERBATIM_REDISTRIBUTION",
                             "THIRD_PARTY_SHARING"],
        "condition": "manual, private, non-commercial scientific review, "
                     "citation and normalized internal derivation only. The "
                     "reviewer did not resolve the contradiction in this "
                     "source's own terms; the approval stays inside the "
                     "intersection both readings permit.",
    },
    {
        "source_key": "dpwg.knmp",
        "permitted_acquisition_modes": ["MANUAL_DOWNLOAD"],
        "prohibited_acquisition_modes": ["OFFICIAL_API",
                                         "LICENSED_BULK_EXPORT",
                                         "PUBLICATION_TRANSCRIPTION"],
        "permitted_reuse": ["LOCAL_STORAGE", "INTERNAL_ANALYSIS"],
        "prohibited_reuse": ["VERBATIM_REDISTRIBUTION", "COMMERCIAL_USE",
                             "AUTOMATED_ACQUISITION", "BULK_DOWNLOAD",
                             "THIRD_PARTY_SHARING"],
        "condition": "official public scientific publications only, manual "
                     "review and citation. G-Standaard and other licensed "
                     "datasets are not covered and may not be reproduced.",
    },
)

#: What this approval does not touch. Named so nobody has to infer it.
NOT_APPROVED_BY_THIS_DECISION: Tuple[str, ...] = (
    "H02 curation protocol and scientific interpretation decisions",
    "H03 intended-purpose and claims-boundary decisions",
    "any drug, gene or phenotype recommendation",
    "any patient-facing or clinician-facing clinical use",
    "any generated pharmacogenetic rule",
    "any dose or treatment-selection statement",
    "any evidence extracted after this review",
    "any legacy data lacking acceptable provenance",
    "redistribution of any source's text",
    "automated access whose terms are unknown",
)

#: Project-owner decisions this approval leaves standing. They belong to later
#: scientific and clinical gates and are recorded here so that nothing in the
#: source-policy approval is read as having settled them.
PRESERVED_OWNER_DECISIONS: Tuple[str, ...] = (
    "amitriptyline stays in the planned first release and must be modelled "
    "as a scientifically reviewed joint CYP2C19 and CYP2D6 decision, not two "
    "falsely independent axes",
    "clopidogrel stays restricted to an explicitly represented ACS/PCI "
    "context",
    "CYP2D6 RAPID must not be used as an expected phenotype",
    "likely, indeterminate and unrepresentable activity-score cases fail "
    "closed",
    "no FDA-supported claim may be made for an axis FDA evidence does not "
    "cover",
    "the long-term 40-50 drug roadmap remains future scope and is not "
    "validated by this approval",
)


#: Why `config/scientific-sources.json` is not changed by this decision.
#:
#: The reviewer approved this project's H01 package. The registry demands
#: something different and stricter: for a source to carry an approving
#: status, ``pgx.scientific.validation`` requires a version policy, a citation
#: policy, a licence identifier, approved claim categories, every reuse
#: dimension answered, and at least one official evidence reference that this
#: project has *itself retrieved* - "naming a URL is not reading the document
#: at it", in the validator's own words, and a VERIFIED reference must carry
#: the retrieval instant.
#:
#: WP-C04 established what each source's terms say. It did not capture, per
#: document, the retrieval instant and content hash the registry requires, and
#: those cannot be reconstructed after the fact without inventing them. The
#: reviewer also attested to the package rather than to each source's own
#: terms page, so their name does not belong in a field that means "the
#: official evidence URLs this reviewer read".
#:
#: So the decision is recorded here in full, and the registry stays as it is.
#: Writing an approving status into it would make the repository assert
#: provenance nobody has, which is the single thing this whole subsystem
#: exists to prevent.
REGISTRY_READINESS_GAPS: Tuple[Dict[str, Any], ...] = (
    {
        "gap": "EVIDENCE_NOT_VERIFIED",
        "applies_to": ["cpic.database", "cpic.publications",
                       "clinpgx.website", "dpwg.knmp"],
        "what_is_missing": "an official evidence reference this project "
                           "retrieved itself, carrying the official URL and "
                           "the retrieval instant",
        "why_it_cannot_be_filled_now": "WP-C04 read the primary documents but "
                                       "did not record a per-document "
                                       "retrieval instant or content hash. "
                                       "Writing one now would be inventing "
                                       "the provenance the field exists to "
                                       "carry.",
        "who_clears_it": "whoever re-retrieves each source's terms document "
                         "and records url, instant and hash",
    },
    {
        "gap": "MISSING_VERSION_POLICY",
        "applies_to": ["cpic.database", "cpic.publications",
                       "clinpgx.website", "dpwg.knmp"],
        "what_is_missing": "how a version of this source is identified",
        "why_it_cannot_be_filled_now": "neither the research nor the "
                                       "attestation states it, and the "
                                       "validator never infers it",
        "who_clears_it": "source policy owner",
    },
    {
        "gap": "MISSING_CITATION_POLICY",
        "applies_to": ["cpic.database", "cpic.publications",
                       "clinpgx.website", "dpwg.knmp"],
        "what_is_missing": "how this source must be cited",
        "why_it_cannot_be_filled_now": "neither the research nor the "
                                       "attestation states it",
        "who_clears_it": "source policy owner",
    },
    {
        "gap": "NO_CLAIM_CATEGORY_APPROVED",
        "applies_to": ["cpic.database", "cpic.publications",
                       "clinpgx.website", "dpwg.knmp"],
        "what_is_missing": "which claim categories each source may be cited "
                           "for, from the project's ClaimCategory vocabulary",
        "why_it_cannot_be_filled_now": "the attestation approves manual "
                                       "review, citation and normalized "
                                       "derivation, which is a use "
                                       "restriction rather than a claim-scope "
                                       "decision. Choosing between "
                                       "PRIMARY_GUIDELINE_RECOMMENDATION, "
                                       "PHENOTYPE_MAPPING and the rest is a "
                                       "scientific scoping act.",
        "who_clears_it": "the reviewer, or the H02 scientific reviewer",
    },
    {
        "gap": "REUSE_PERMISSION_UNKNOWN",
        "applies_to": ["cpic.database", "cpic.publications",
                       "clinpgx.website", "dpwg.knmp"],
        "what_is_missing": "all ten reuse dimensions answered ALLOWED, "
                           "RESTRICTED, PROHIBITED or NOT_APPLICABLE",
        "why_it_cannot_be_filled_now": "the attestation answers the "
                                       "dimensions it names and is silent on "
                                       "the others; UNKNOWN blocks exactly as "
                                       "PROHIBITED does",
        "who_clears_it": "source policy owner, with the reviewer",
    },
    {
        "gap": "REVIEW_EVIDENCE_URLS_MISMATCH",
        "applies_to": ["cpic.database", "cpic.publications",
                       "clinpgx.website", "dpwg.knmp"],
        "what_is_missing": "an approving ReviewRecord must cite the official "
                           "evidence URLs the reviewer relied on",
        "why_it_cannot_be_filled_now": "this reviewer read the project's H01 "
                                       "package, not each source's own terms "
                                       "page. Listing source URLs there would "
                                       "misstate what they read.",
        "who_clears_it": "the reviewer, by reviewing the retrieved terms "
                         "documents directly, or a second reviewer who has",
    },
)


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with io.open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def measure_hashes(root: str) -> Dict[str, str]:
    """The package's digests as they are on disk right now."""
    measured: Dict[str, str] = {}
    for name in sorted(set(REVIEWED_ARTIFACTS) | set(SUPPORTING_ARTIFACTS)):
        path = os.path.join(root, *(_PACKAGE.split("/") + [name]))
        measured[name] = _sha256(path) if os.path.isfile(path) else ""
    return measured


def _binding(root: str) -> Dict[str, Any]:
    """Re-check what the reviewer attested to, every run.

    The reviewed artifacts decide. A supporting document that has drifted is
    reported and does not void the decision, because the decision was recorded
    against the evidence table and the proposed decisions; a reviewed artifact
    that has drifted voids it until somebody re-attests.
    """
    measured = measure_hashes(root)
    rows: List[Dict[str, Any]] = []
    for name in sorted(REVIEWED_HASHES):
        expected = REVIEWED_HASHES[name]
        actual = measured.get(name, "")
        rows.append({
            "artifact": "%s/%s" % (_PACKAGE, name),
            "role": ("REVIEWED_CONTENT" if name in REVIEWED_ARTIFACTS
                     else "SUPPORTING"),
            "attested_sha256": expected,
            "measured_sha256": actual or None,
            "matches": actual == expected,
        })
    reviewed_ok = all(row["matches"] for row in rows
                      if row["role"] == "REVIEWED_CONTENT")
    return {
        "rows": rows,
        "reviewed_content_matches": reviewed_ok,
        "supporting_drift": [row["artifact"] for row in rows
                             if row["role"] == "SUPPORTING"
                             and not row["matches"]],
    }


def build_decision(root: str = ".") -> Dict[str, Any]:
    """The recorded decision, or a re-attestation request if bytes changed."""
    binding = _binding(root)
    recorded = binding["reviewed_content_matches"]

    payload: Dict[str, Any] = {
        "decision_record_version": DECISION_RECORD_VERSION,
        "checkpoint": CHECKPOINT,
        "state": "RECORDED" if recorded else "AWAITING_REATTESTATION",
        "hash_binding": binding,
        "approval_form_sha256_before_recording": APPROVAL_FORM_HASH_BEFORE,
        "reviewer": dict(REVIEWER),
        "attestation_verbatim": ATTESTATION_VERBATIM,
        "restrictions": list(RESTRICTIONS),
        "prohibited_modes": list(PROHIBITED_MODES),
        "dispositions": [dict(item) for item in DISPOSITIONS],
        "source_outcomes": [dict(item) for item in SOURCE_OUTCOMES],
        "not_approved_by_this_decision": list(NOT_APPROVED_BY_THIS_DECISION),
        "preserved_owner_decisions": list(PRESERVED_OWNER_DECISIONS),
        "registry_change": {
            "config_scientific_sources_changed": False,
            "reason": "the registry's own rules require provenance this "
                      "project has not captured; see registry_readiness_gaps",
            "gaps": [dict(item) for item in REGISTRY_READINESS_GAPS],
        },
        "note": "A human approved the H01 package under stated conditions. "
                "That is recorded here. It does not by itself make any source "
                "usable: the registry has its own completeness rules and they "
                "are not met.",
    }
    if not recorded:
        payload["reattestation_request"] = {
            "why": "content the reviewer attested to has changed since the "
                   "attestation was given",
            "changed": [row for row in binding["rows"]
                        if row["role"] == "REVIEWED_CONTENT"
                        and not row["matches"]],
            "what_is_needed": "a fresh attestation naming the new digests. "
                              "The previous approval is not transferred and "
                              "no substitute decision is recorded.",
        }
    payload["content_hash"] = "sha256:" + hashlib.sha256(json.dumps(
        payload, indent=2, sort_keys=True,
        ensure_ascii=False).encode("utf-8")).hexdigest()
    return payload


# ---------------------------------------------------------------------------
# The filled approval form
# ---------------------------------------------------------------------------

def render_approval_form(payload: Mapping[str, Any]) -> str:
    """The H01 form, filled in from the recorded decision.

    Rendered from the decision record rather than typed beside it, so the
    form and the machine-readable record cannot come to say different things
    about who decided what.
    """
    reviewer = payload["reviewer"]
    recorded = payload["state"] == "RECORDED"
    lines: List[str] = []
    add = lines.append

    add("# %s - approval form" % CHECKPOINT)
    add("")
    if recorded:
        add("**This form records a human decision. It was filled in from a "
            "typed attestation relayed by the project owner, and it is bound "
            "to the digests below.**")
    else:  # pragma: no cover - exercised by the drift test
        add("**AWAITING RE-ATTESTATION. The content the reviewer attested to "
            "has changed; the previous approval is not carried over.**")
    add("")
    add("Generated by `scripts/build_closure_wave01_h01_decision.py` from "
        "`data/closure/h01-source-policy-decision.json`. Do not edit by "
        "hand.")
    add("")
    add("## Decision")
    add("")
    add("| Field | Value |")
    add("| --- | --- |")
    add("| Checkpoint | `%s` |" % CHECKPOINT)
    add("| Reviewer name | %s |" % reviewer["name"])
    add("| Reviewer role | %s |" % reviewer["role_in_this_decision"])
    add("| Qualification relied on | %s |" % reviewer["qualification"])
    add("| Date (UTC, ISO 8601) | %s |"
        % reviewer["decision_date_supplied_by_reviewer"])
    add("| Verdict | %s |" % reviewer["decision"])
    add("| Repository decision enum | `%s` |"
        % reviewer["repository_decision_enum"])
    add("| Signature text | `%s` |" % reviewer["signature_text_supplied"])
    add("| Signature method | %s |" % reviewer["signature_method"])
    add("| Provenance | %s |" % reviewer["provenance"])
    add("| Identity verification | %s |" % reviewer["identity_verification"])
    add("")
    add("%s" % reviewer["identity_verification_note"])
    add("")
    add("## What the decision is bound to")
    add("")
    add("| Artifact | Role | Attested | Measured | Match |")
    add("| --- | --- | --- | --- | :---: |")
    for row in payload["hash_binding"]["rows"]:
        add("| `%s` | %s | `%s` | `%s` | %s |"
            % (row["artifact"], row["role"], row["attested_sha256"],
               row["measured_sha256"] or "absent",
               "yes" if row["matches"] else "**no**"))
    add("")
    add("The digests are re-measured every time the producer runs. If a "
        "reviewed artifact changes, this form is rewritten as a "
        "re-attestation request and the approval is not carried across.")
    add("")
    add("## Reviewer attestation, verbatim")
    add("")
    add("> " + payload["attestation_verbatim"].replace("\n", "\n> "))
    add("")
    add("## Per-decision verdicts")
    add("")
    add("| decision_id | source | outcome | registry status |")
    add("| --- | --- | --- | --- |")
    for item in payload["dispositions"]:
        add("| `%s` | `%s` | %s | `%s` |"
            % (item["decision_id"], item["source_key"], item["reviewer_wording"],
               item["registry_status"]))
    add("")
    add("## Conditions attached to this approval")
    add("")
    for item in payload["restrictions"]:
        add("- %s" % item)
    add("")
    add("## Explicitly not approved")
    add("")
    for item in payload["prohibited_modes"]:
        add("- %s" % item)
    add("")
    add("## What this approval does not cover")
    add("")
    for item in payload["not_approved_by_this_decision"]:
        add("- %s" % item)
    add("")
    add("## Why the source registry is unchanged")
    add("")
    add(payload["registry_change"]["reason"] + ".")
    add("")
    add("| Gap | Applies to | What is missing | Who clears it |")
    add("| --- | --- | --- | --- |")
    for gap in payload["registry_change"]["gaps"]:
        add("| `%s` | %s | %s | %s |"
            % (gap["gap"], ", ".join("`%s`" % key for key in gap["applies_to"]),
               gap["what_is_missing"], gap["who_clears_it"]))
    add("")
    add("## Owner decisions this approval leaves standing")
    add("")
    for item in payload["preserved_owner_decisions"]:
        add("- %s" % item)
    add("")
    return "\n".join(lines) + "\n"
