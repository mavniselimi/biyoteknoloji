# -*- coding: utf-8 -*-
"""WP-C04: what the source research established, as data.

Every row here was read from a primary document - a licence file, a terms
page, a regulator's own label, a provider's own API description - and not
from a search-result snippet or a secondary summary. Where a document could
not be retrieved, the row says so and the field stays ``UNKNOWN``. Silence is
never read as permission.

Two things are kept apart on purpose, because conflating them is the mistake
this file exists to prevent:

*Scientific authority* is whether a source is a body whose statements this
project would cite. *Legal permission* is whether this project may retrieve,
store, transform or republish that source's material. CPIC is authoritative
and permissive; DPWG is authoritative and its terms are unknown; a source can
be either without being the other, and one is never evidence for the other.

API terms and website terms are also kept apart, for the same provider,
because they routinely differ.

Nothing here is an approval. Every proposal is addressed to a named human who
has not yet decided, and no status moves out of ``PENDING_REVIEW`` in this
file or in anything it generates.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

__all__ = ["FIRST_RELEASE_AXES", "PHENOTYPE_SCOPE", "SCOPE_CONTRADICTIONS",
           "SOURCE_FINDINGS", "TARGET_SOURCE_KEYS", "coverage_rows"]

#: The source registry keys the first release actually depends on. Everything
#: else in the registry is proposed for deferral, which is a scope decision
#: and not a judgement about the source.
TARGET_SOURCE_KEYS: Tuple[str, ...] = (
    "clinpgx.api", "clinpgx.website", "cpic.api", "cpic.database",
    "cpic.publications", "dpwg.knmp", "druglabel.fda", "druglabel.titck")

FIRST_RELEASE_AXES: Tuple[str, ...] = (
    "CYP2C19::amitriptyline", "CYP2C19::clopidogrel", "CYP2C19::omeprazole",
    "CYP2D6::amitriptyline", "CYP2D6::codeine")

PHENOTYPE_SCOPE: Tuple[str, ...] = ("POOR", "INTERMEDIATE", "NORMAL", "RAPID",
                                    "ULTRARAPID")

#: One record per researched source. ``licence`` is what the primary document
#: says; ``licence_evidence`` is where that was read; ``verification`` says
#: whether the project has confirmed it from the authoritative location or
#: only from a mirror.
SOURCE_FINDINGS: Tuple[Dict[str, Any], ...] = (
    {
        "source_key": "cpic.database",
        "scientific_authority": "PRIMARY_GUIDELINE_BODY",
        "licence": "CC0-1.0",
        "licence_evidence": "the LICENSE.md file in the cpicpgx/cpic-data "
                            "repository, which is the distribution CPIC "
                            "publishes its database from",
        "verification": "READ_FROM_DISTRIBUTION_NOT_FROM_THE_LIVE_POLICY_PAGE",
        "verification_gap": "the live data-usage policy page is a "
                            "client-rendered application and did not render "
                            "to readable text, so the CC0 declaration is "
                            "confirmed from the distribution CPIC publishes "
                            "rather than from the policy page itself. A "
                            "human should confirm the policy page agrees.",
        "reuse_supported_by_licence": ("LOCAL_STORAGE", "INTERNAL_ANALYSIS",
                                       "DERIVED_WORK_CREATION",
                                       "AGGREGATED_REDISTRIBUTION",
                                       "VERBATIM_REDISTRIBUTION",
                                       "COMMERCIAL_USE", "BULK_DOWNLOAD",
                                       "THIRD_PARTY_SHARING",
                                       "PUBLIC_DISPLAY"),
        "reuse_still_unknown": ("AUTOMATED_ACQUISITION",),
        "reuse_note": "CC0 waives copyright; it says nothing about the rate "
                      "at which a server may be queried, so automated "
                      "acquisition stays UNKNOWN until the API's own terms "
                      "are read.",
        "conflict": None,
    },
    {
        "source_key": "cpic.api",
        "scientific_authority": "PRIMARY_GUIDELINE_BODY",
        "licence": "CC0-1.0",
        "licence_evidence": "the same CPIC data licence; the API serves the "
                            "database this licence covers",
        "verification": "INHERITED_FROM_THE_DATABASE_LICENCE",
        "verification_gap": "the API's own terms of use, as distinct from "
                            "the data licence, were not located. Terms for "
                            "an interface and terms for its content are "
                            "different documents and are not assumed to "
                            "agree.",
        "reuse_supported_by_licence": ("LOCAL_STORAGE", "INTERNAL_ANALYSIS",
                                       "DERIVED_WORK_CREATION"),
        "reuse_still_unknown": ("AUTOMATED_ACQUISITION", "BULK_DOWNLOAD",
                                "AGGREGATED_REDISTRIBUTION",
                                "VERBATIM_REDISTRIBUTION", "COMMERCIAL_USE",
                                "THIRD_PARTY_SHARING", "PUBLIC_DISPLAY"),
        "reuse_note": "The content licence does not license the service. "
                      "Query-rate and bulk-access permissions are a separate "
                      "question and remain unanswered.",
        "conflict": None,
    },
    {
        "source_key": "cpic.publications",
        "scientific_authority": "PRIMARY_GUIDELINE_BODY",
        "licence": "UNKNOWN",
        "licence_evidence": "CPIC guidelines are published in journals whose "
                            "terms are the publisher's, not CPIC's; no "
                            "single licence covers the set",
        "verification": "NOT_ESTABLISHED",
        "verification_gap": "each guideline would have to be checked against "
                            "its own publisher. The project does not need "
                            "the publication text if it uses the database, "
                            "which is why this is proposed for deferral "
                            "rather than research.",
        "reuse_supported_by_licence": (),
        "reuse_still_unknown": ("LOCAL_STORAGE", "INTERNAL_ANALYSIS",
                                "DERIVED_WORK_CREATION",
                                "AGGREGATED_REDISTRIBUTION",
                                "VERBATIM_REDISTRIBUTION", "COMMERCIAL_USE",
                                "AUTOMATED_ACQUISITION", "BULK_DOWNLOAD",
                                "THIRD_PARTY_SHARING", "PUBLIC_DISPLAY"),
        "reuse_note": "Citing a guideline is not reusing its text. The "
                      "distinction matters for what the platform may display.",
        "conflict": None,
    },
    {
        "source_key": "clinpgx.website",
        "scientific_authority": "SUPPORTING_ANNOTATION_RESOURCE",
        "licence": "CC-BY-SA-4.0 WITH AN INCOMPATIBLE OVERLAY",
        "licence_evidence": "the site's own data-usage statement, which "
                            "names CC-BY-SA-4.0 and, in the same statement, "
                            "restricts use to research purposes and forbids "
                            "sale",
        "verification": "READ_FROM_THE_PROVIDERS_OWN_PAGE",
        "verification_gap": None,
        "reuse_supported_by_licence": ("LOCAL_STORAGE", "INTERNAL_ANALYSIS"),
        "reuse_still_unknown": ("DERIVED_WORK_CREATION",
                                "AGGREGATED_REDISTRIBUTION",
                                "VERBATIM_REDISTRIBUTION", "COMMERCIAL_USE",
                                "AUTOMATED_ACQUISITION", "BULK_DOWNLOAD",
                                "THIRD_PARTY_SHARING", "PUBLIC_DISPLAY"),
        "reuse_note": "The two halves of the statement cannot both be "
                      "honoured: CC-BY-SA-4.0 permits commercial use and "
                      "forbids adding restrictions, and the overlay does "
                      "both. This is not a question a maintainer should "
                      "answer.",
        "conflict": "LICENCE_CONTRADICTS_ITS_OWN_USE_RESTRICTION",
    },
    {
        "source_key": "clinpgx.api",
        "scientific_authority": "SUPPORTING_ANNOTATION_RESOURCE",
        "licence": "UNKNOWN",
        "licence_evidence": "no API-specific terms document was located; the "
                            "site statement addresses data, not the service",
        "verification": "NOT_ESTABLISHED",
        "verification_gap": "the API terms are a separate document from the "
                            "website terms and were not found. The evidence "
                            "build already in this repository was acquired "
                            "through this API, which makes the question "
                            "retrospective as well as prospective.",
        "reuse_supported_by_licence": (),
        "reuse_still_unknown": ("LOCAL_STORAGE", "INTERNAL_ANALYSIS",
                                "DERIVED_WORK_CREATION",
                                "AGGREGATED_REDISTRIBUTION",
                                "VERBATIM_REDISTRIBUTION", "COMMERCIAL_USE",
                                "AUTOMATED_ACQUISITION", "BULK_DOWNLOAD",
                                "THIRD_PARTY_SHARING", "PUBLIC_DISPLAY"),
        "reuse_note": "The quarantined evidence build in "
                      "data/evidence/PGX-DATA-20260830-900 carries "
                      "provider_source_key clinpgx.api throughout. Whatever "
                      "is decided here applies to material already held.",
        "conflict": "MATERIAL_ALREADY_ACQUIRED_UNDER_UNDETERMINED_TERMS",
    },
    {
        "source_key": "dpwg.knmp",
        "scientific_authority": "PRIMARY_GUIDELINE_BODY",
        "licence": "UNKNOWN",
        "licence_evidence": "no licence or reuse statement is published for "
                            "the DPWG recommendations by KNMP",
        "verification": "SEARCHED_AND_NOT_FOUND",
        "verification_gap": "absence of a statement is not permission. The "
                            "machine-readable form of these recommendations "
                            "reaches most consumers through the G-Standaard, "
                            "which is licensed commercially by Z-Index and "
                            "whose terms prohibit reproduction.",
        "reuse_supported_by_licence": (),
        "reuse_still_unknown": ("LOCAL_STORAGE", "INTERNAL_ANALYSIS",
                                "DERIVED_WORK_CREATION",
                                "AGGREGATED_REDISTRIBUTION",
                                "VERBATIM_REDISTRIBUTION", "COMMERCIAL_USE",
                                "AUTOMATED_ACQUISITION", "BULK_DOWNLOAD",
                                "THIRD_PARTY_SHARING", "PUBLIC_DISPLAY"),
        "reuse_note": "DPWG's scientific standing is not in question. Its "
                      "reuse terms are simply not stated anywhere the "
                      "project could find, and the commercial channel that "
                      "does carry the structured data forbids reproduction.",
        "conflict": "AUTHORITATIVE_BUT_NO_STATED_TERMS",
    },
    {
        "source_key": "druglabel.fda",
        "scientific_authority": "REGULATOR",
        "licence": "CC0-1.0 FOR THE API, UNKNOWN FOR THE LABEL TEXT",
        "licence_evidence": "openFDA publishes its data under CC0; the "
                            "label text it serves is written by the "
                            "manufacturer, and NLM's own guidance warns that "
                            "third-party copyright may subsist in it",
        "verification": "READ_FROM_THE_PROVIDERS_OWN_TERMS",
        "verification_gap": "17 U.S.C. 105 removes copyright from works of "
                            "the United States government. A label authored "
                            "by a sponsor and filed with the agency is not "
                            "obviously such a work. The API terms and the "
                            "content status are different questions and only "
                            "the first is answered.",
        "reuse_supported_by_licence": ("LOCAL_STORAGE", "INTERNAL_ANALYSIS",
                                       "AUTOMATED_ACQUISITION",
                                       "BULK_DOWNLOAD"),
        "reuse_still_unknown": ("DERIVED_WORK_CREATION",
                                "AGGREGATED_REDISTRIBUTION",
                                "VERBATIM_REDISTRIBUTION", "COMMERCIAL_USE",
                                "THIRD_PARTY_SHARING", "PUBLIC_DISPLAY"),
        "reuse_note": "Reading a label to decide what a rule says is not the "
                      "same as republishing its wording, and the second is "
                      "the one that is unresolved.",
        "conflict": "OPEN_API_TERMS_OVER_POSSIBLY_COPYRIGHTED_CONTENT",
    },
    {
        "source_key": "druglabel.titck",
        "scientific_authority": "REGULATOR",
        "licence": "UNKNOWN",
        "licence_evidence": "none retrieved",
        "verification": "RETRIEVAL_FAILED",
        "verification_gap": "every attempt to reach the site failed before "
                            "any document was read: the robots policy itself "
                            "returned a server error or timed out. With no "
                            "readable robots policy there is no "
                            "robots-compliant automated route, and no terms "
                            "document was seen at all.",
        "reuse_supported_by_licence": (),
        "reuse_still_unknown": ("LOCAL_STORAGE", "INTERNAL_ANALYSIS",
                                "DERIVED_WORK_CREATION",
                                "AGGREGATED_REDISTRIBUTION",
                                "VERBATIM_REDISTRIBUTION", "COMMERCIAL_USE",
                                "AUTOMATED_ACQUISITION", "BULK_DOWNLOAD",
                                "THIRD_PARTY_SHARING", "PUBLIC_DISPLAY"),
        "reuse_note": "The Turkish regulator is the one source a Turkish "
                      "deployment would be expected to carry, and it is the "
                      "one the project currently cannot reach at all.",
        "conflict": "REQUIRED_FOR_JURISDICTION_BUT_UNREACHABLE",
    },
)

#: What the sources say about the declared axes, and where they do not agree
#: with how the project has described its own scope. These are questions for
#: the scientific reviewer, not decisions this file makes.
SCOPE_CONTRADICTIONS: Tuple[Dict[str, str], ...] = (
    {
        "id": "SC-01",
        "subject": "amitriptyline is one two-gene decision, not two axes",
        "finding": "CPIC's amitriptyline recommendations are keyed by a "
                   "CYP2D6 and CYP2C19 pair together; every recommendation "
                   "record carries both gene keys. The project's scope names "
                   "CYP2C19::amitriptyline and CYP2D6::amitriptyline as two "
                   "independent axes.",
        "why_it_matters": "A rule that answers for one gene while the source "
                          "answered for both is not a subset of the source's "
                          "recommendation; it is a different claim. Splitting "
                          "the matrix is a scientific decision.",
        "decision_needed": "Whether the first release models amitriptyline as "
                           "a two-gene matrix, restricts itself to the "
                           "single-gene cells the source states separately, "
                           "or removes amitriptyline from the first release.",
        "owner": "clinical pharmacogenomics reviewer",
    },
    {
        "id": "SC-02",
        "subject": "clopidogrel recommendations depend on indication",
        "finding": "CPIC states clopidogrel recommendations separately for "
                   "cardiovascular indications with acute coronary syndrome "
                   "and percutaneous coronary intervention, for other "
                   "cardiovascular indications, and for neurovascular "
                   "indications. The project's scope has no indication axis.",
        "why_it_matters": "Collapsing three population-specific "
                          "recommendations into one loses the condition each "
                          "was stated under. Presenting the strongest of them "
                          "as the answer would overstate the source.",
        "decision_needed": "Whether the first release carries an indication "
                           "axis, restricts itself to one indication and says "
                           "so, or defers clopidogrel.",
        "owner": "clinical pharmacogenomics reviewer",
    },
    {
        "id": "SC-03",
        "subject": "the five-phenotype vocabulary does not fit CYP2D6",
        "finding": "CPIC does not assign a RAPID phenotype for CYP2D6, and "
                   "it does emit Likely Poor, Likely Intermediate and "
                   "Indeterminate, none of which the project's five-value "
                   "vocabulary can express. CYP2D6 recommendations are keyed "
                   "by activity score, not by a phenotype label alone.",
        "why_it_matters": "A vocabulary that cannot represent what the source "
                          "said will either drop cases silently or map them "
                          "to a neighbouring value. Both are "
                          "misrepresentation.",
        "decision_needed": "Whether the phenotype vocabulary is extended, "
                           "whether unrepresentable phenotypes are refused "
                           "explicitly, and whether CYP2D6 carries an "
                           "activity score.",
        "owner": "clinical pharmacogenomics reviewer",
    },
    {
        "id": "SC-04",
        "subject": "the FDA does not cover one declared axis",
        "finding": "FDA labelling addresses four of the five declared axes. "
                   "CYP2C19 with amitriptyline is absent. Of those it does "
                   "address, only clopidogrel and codeine carry "
                   "boxed-warning-strength language.",
        "why_it_matters": "A design that expects a regulator statement for "
                          "every axis will find none for this one, and a "
                          "reader who sees four covered may assume the fifth "
                          "is too.",
        "decision_needed": "Whether an axis without regulator labelling may "
                           "still be released, and how its absence is shown.",
        "owner": "clinical pharmacogenomics reviewer",
    },
    {
        "id": "SC-05",
        "subject": "the clopidogrel boxed warning no longer says "
                   "'poor metabolizer'",
        "finding": "The current clopidogrel boxed warning is worded around "
                   "carrying two loss-of-function alleles of CYP2C19 rather "
                   "than around the phenotype term.",
        "why_it_matters": "Any extraction keyed on the phrase 'poor "
                          "metabolizer' will silently return nothing for the "
                          "single most important warning in the first "
                          "release, and silence looks the same as absence.",
        "decision_needed": "How label extraction is keyed, and how a "
                           "zero-result extraction is distinguished from a "
                           "genuine absence.",
        "owner": "clinical pharmacogenomics reviewer",
    },
)


def coverage_rows() -> List[Dict[str, str]]:
    """Which researched source states something on each declared axis."""
    covered = {
        "cpic.database": dict.fromkeys(FIRST_RELEASE_AXES, "STATED"),
        "dpwg.knmp": dict.fromkeys(FIRST_RELEASE_AXES, "STATED"),
        "druglabel.fda": {
            "CYP2C19::amitriptyline": "ABSENT",
            "CYP2C19::clopidogrel": "STATED_BOXED_WARNING",
            "CYP2C19::omeprazole": "STATED",
            "CYP2D6::amitriptyline": "STATED",
            "CYP2D6::codeine": "STATED_BOXED_WARNING",
        },
        "druglabel.titck": dict.fromkeys(FIRST_RELEASE_AXES, "UNKNOWN"),
    }
    rows: List[Dict[str, str]] = []
    for source_key in sorted(covered):
        for axis in FIRST_RELEASE_AXES:
            rows.append({"source_key": source_key, "axis": axis,
                         "coverage": covered[source_key][axis]})
    return rows
