# -*- coding: utf-8 -*-
"""Failure types for the reporting layer (WP-15).

Same shape and same reasoning as :mod:`pgx.engine.risk_errors`: every refusal
carries a stable machine-readable code, because "this report dropped a fact",
"this text tripped the claim scanner" and "this artifact already exists with
different content" have different owners and different remedies.

Note what is absent, again deliberately. There is no error for "nothing could
be reported". An assessment whose every axis was ``NOT_ASSESSED`` produces a
complete, correct report that says so at length. Absence is rendered, never
raised - a reporting layer that could throw on absence would eventually be
wrapped in a ``try`` by somebody who wanted a report anyway.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

__all__ = [
    "REPORT_FAILURE_CODES",
    "ReportArtifactError",
    "ReportClaimError",
    "ReportError",
    "ReportFactError",
    "ReportInputError",
    "ReportRenderError",
]

#: Every refusal this work package can produce, with what each means.
REPORT_FAILURE_CODES: Mapping[str, str] = {
    "REPORT_INPUT_INVALID":
        "the assessment facts handed to reporting could not be read as a "
        "canonical result",
    "REPORT_UNKNOWN_FIELD":
        "the document carries a field the report contract does not name; an "
        "unnamed field cannot be shown, checked or refused",
    "REPORT_CLAIM_BOUNDARY_NOT_APPROVED":
        "the claim boundary carries no approval from named humans, so no "
        "report of a real assessment may be produced in any mode",
    "REPORT_SYNTHETIC_DESTINATION_REFUSED":
        "a synthetic report was directed at a production artifact directory; "
        "synthetic output is never filed where real output is read from",
    "REPORT_ASSESSMENT_NOT_FOUND":
        "no stored assessment carries the requested identity, and reporting "
        "does not calculate one to fill the gap",
    "REPORT_HASH_MISMATCH":
        "a hash recomputed from the supplied facts disagrees with the hash "
        "recorded beside them",
    "REPORT_COVERAGE_UNVERIFIABLE":
        "the coverage result is absent or does not match the hash recorded "
        "beside it, so what could be evaluated cannot be stated",
    "REPORT_FACT_LOST":
        "a fact the assessment recorded is missing from the report built "
        "from it",
    "REPORT_EVIDENCE_MISSING":
        "a finding reached the report without the evidence that backs it "
        "(SAFETY-INV-006)",
    "REPORT_RULE_PROVENANCE_MISSING":
        "a finding reached the report without naming the governed rule and "
        "version that produced it",
    "REPORT_RELEASE_PROVENANCE_MISSING":
        "the report does not name every version the assessment executed "
        "against (SAFETY-INV-007)",
    "REPORT_ROW_SNAPSHOT_DISAGREEMENT":
        "the stored row and the stored snapshot describe different results",
    "REPORT_ENTITY_NOT_PRESENT":
        "the report references an entity the assessment does not contain",
    "REPORT_CONFLICT_REFERENCE_LOST":
        "an unresolved source conflict was recorded and is not in the report "
        "(SAFETY-INV-008)",
    "REPORT_STATUS_RENDERING_UNSAFE":
        "a status would be displayed in a way that reads as reassurance; "
        "missing data is never low, safe, normal or suitable "
        "(SAFETY-INV-001)",
    "REPORT_PROHIBITED_CLAIM":
        "the rendered text contains language the claim boundary prohibits, so "
        "it is not published (SAFETY-INV-010)",
    "REPORT_TEMPLATE_UNKNOWN":
        "the requested template version is not one this build ships",
    "REPORT_LOCALE_NOT_SUPPORTED":
        "the requested locale has no controlled label set; nothing is "
        "translated on the fly",
    "REPORT_LABEL_UNKNOWN":
        "a governed code has no controlled label in this locale, and a label "
        "is never invented for one",
    "REPORT_SCHEMA_VERSION_UNKNOWN":
        "the document names a report schema version this build cannot read",
    "REPORT_ARTIFACT_CONFLICT":
        "an artifact with this name already exists carrying different "
        "content; a published report is never silently overwritten",
    "REPORT_ARTIFACT_INCOMPLETE":
        "the artifact directory holds a report without its manifest, or a "
        "manifest naming a report that is not there",
    "REPORT_ARTIFACT_HASH_MISMATCH":
        "an artifact read back does not hash to what its manifest records",
    "REPORT_LLM_DISABLED":
        "no language-model provider is implemented and none is enabled; P0 "
        "report generation is entirely offline",
}


class ReportError(Exception):
    """Base class for every reporting failure."""

    def __init__(self, message: str, *,
                 code: str = "REPORT_INPUT_INVALID",
                 location: str = "$",
                 detail: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.location = location
        self.detail = dict(detail or {})

    def to_json(self) -> dict:
        """The refusal as a structured record.

        Carries the code, where it happened and structured detail - never the
        text that failed. A refusal log holding the sentence that tripped the
        claim scanner would put the prohibited sentence into the log.
        """
        return {
            "refused": True,
            "code": self.code,
            "location": self.location,
            "meaning": REPORT_FAILURE_CODES.get(self.code, ""),
            "detail": dict(self.detail),
        }


class ReportInputError(ReportError):
    """The facts handed to reporting could not be read, or do not verify."""


class ReportFactError(ReportError):
    """The report and the assessment it came from disagree."""


class ReportClaimError(ReportError):
    """The rendered text carries language the claim boundary prohibits."""


class ReportRenderError(ReportError):
    """The report could not be rendered under the requested template."""


class ReportArtifactError(ReportError):
    """The artifact could not be written, or does not read back intact."""
