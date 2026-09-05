# -*- coding: utf-8 -*-
"""The report application service (WP-15).

Orchestration only, in the shape :mod:`pgx.application.assessment_service`
established: every capability arrives as an injected port, so this module
decides *what happens in what order* and never *how*.

The order is eight steps and none of them may be skipped:

1. **Gate first.** The claim boundary is checked before anything is read. A
   product not yet permitted to answer is not permitted to publish an answer
   either.
2. **Read the stored assessment**, through the lossless read port. A missing
   assessment is a refusal, never an empty report: a report of nothing looks
   exactly like a report of a case with nothing to report.
3. **Canonicalise the facts**, verifying every hash before construction.
4. **Project into a structured report** under a fixed template and locale.
5. **Check that nothing was lost**, against a fact ledger built from the
   facts rather than from the report.
6. **Check how every status is displayed**, so absence cannot read as
   reassurance.
7. **Render deterministically, then scan.** The claim gate runs over the
   finished text; a non-clean scan blocks publication.
8. **Write the artifact and its manifest**, atomically, or write nothing.

**Nothing here calculates.** There is no import of the assessment service, the
risk engine, the coverage engine, the rule registry or the release resolver,
and a boundary test asserts that by name. Rendering a stored assessment
re-reads it; it never re-runs it. If it did, a report could disagree with the
assessment it claims to describe, and the disagreement would be invisible
because both halves would look freshly computed.

**Synthetic mode is explicit and is never evidence.** :meth:`render_synthetic`
exists so the pipeline can be exercised while no real assessment exists. Its
result is flagged, its artifacts must be written outside the production
directory, and the gate status counts it as zero real reports - because it is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from pgx.domain.claims import DEFAULT_CLAIM_BOUNDARY, ClaimBoundary
from pgx.reporting.artifacts import read_artifact, write_artifact
from pgx.reporting.errors import ReportError, ReportInputError
from pgx.reporting.gate import claim_scan_evidence, require_clean_report
from pgx.reporting.models import (CanonicalAssessmentResult,
                                  canonical_result_from_document,
                                  canonical_result_from_read_model)
from pgx.reporting.render import (render_json, render_markdown,
                                  rendered_checksum)
from pgx.reporting.structured import StructuredReport, build_structured_report
from pgx.reporting.templates import DEFAULT_LOCALE, TEMPLATE_VERSION
from pgx.reporting.validator import (build_fact_ledger,
                                     validate_fact_preservation,
                                     validate_rendered_report,
                                     validate_safe_status_rendering)

__all__ = [
    "PRODUCTION_ARTIFACT_MARKER",
    "AssessmentReadPort",
    "ReportResult",
    "ReportService",
]

#: Path fragment that marks a production artifact directory. A synthetic
#: report directed at one is refused: a synthetic document filed where real
#: documents are read from is a synthetic document somebody will cite.
PRODUCTION_ARTIFACT_MARKER = "data/reports"


@dataclass(frozen=True, slots=True)
class ReportResult:
    """One produced report: the document, and everything that checked it."""

    assessment_id: str
    locale: str
    template_version: str
    report: StructuredReport
    result: CanonicalAssessmentResult
    markdown: str
    json_text: str
    fact_ledger: Mapping[str, Any]
    claim_scan: Mapping[str, Any]
    safe_status: Mapping[str, Any]
    rendered_verification: Mapping[str, Any]
    is_synthetic: bool = False
    artifact: Optional[Mapping[str, Any]] = None

    @property
    def report_hash(self) -> str:
        return self.report.report_hash()

    @property
    def output_hash(self) -> str:
        return self.report.output_hash

    def to_json(self) -> Dict[str, Any]:
        return {
            "assessment_id": self.assessment_id,
            "locale": self.locale,
            "template_version": self.template_version,
            "report_schema_version": self.report.report_schema_version,
            "output_hash": self.output_hash,
            "report_hash": self.report_hash,
            "rendered_checksum": rendered_checksum(self.markdown),
            "rendered_bytes": len(self.markdown.encode("utf-8")),
            "is_synthetic": self.is_synthetic,
            "claim_scan_is_clean": bool(self.claim_scan.get("is_clean")),
            "fact_ledger_hash": self.fact_ledger.get("ledger_hash"),
            "checked_facts": self.rendered_verification.get("checked_facts"),
            "artifact": (dict(self.artifact) if self.artifact is not None
                         else None),
        }


class AssessmentReadPort:
    """Port: return the lossless read model for one stored assessment.

    Separated from the service because *where an assessment is stored* is an
    environment question and *that a report is built only from a stored,
    verified one* is a safety question. The production implementation is
    :meth:`pgx.infrastructure.db.assessments.SqlAlchemyAssessmentRepository.read_model`.
    """

    def read_model(self, assessment_id: Any):  # pragma: no cover - protocol
        raise NotImplementedError


class ReportService:
    """Produce one report from one stored assessment, or refuse."""

    def __init__(self, *, read_port: Optional[AssessmentReadPort] = None,
                 claim_boundary: ClaimBoundary = DEFAULT_CLAIM_BOUNDARY,
                 default_locale: str = DEFAULT_LOCALE,
                 template_version: str = TEMPLATE_VERSION) -> None:
        self._read_port = read_port
        self._boundary = claim_boundary
        self._locale = default_locale
        self._template = template_version

    # -- the gate --------------------------------------------------------

    @property
    def claim_boundary(self) -> ClaimBoundary:
        return self._boundary

    def gate_state(self) -> Dict[str, Any]:
        """Whether this service may publish anything at all, and why not."""
        return {
            "claim_boundary_phase": self._boundary.phase.value,
            "claim_boundary_status": self._boundary.status,
            "claim_boundary_approved": self._boundary.is_approved,
            "may_publish": self._boundary.is_approved,
            "read_port_configured": self._read_port is not None,
            "refusal_code": (None if self._boundary.is_approved
                             else "REPORT_CLAIM_BOUNDARY_NOT_APPROVED"),
        }

    def _require_boundary(self) -> None:
        if not self._boundary.is_approved:
            raise ReportInputError(
                "the claim boundary is %r. No report of a real assessment is "
                "produced until named humans have approved the intended "
                "purpose, and no flag in this codebase sets that approval."
                % self._boundary.status,
                code="REPORT_CLAIM_BOUNDARY_NOT_APPROVED",
                location="$.claim_boundary",
                detail={"phase": self._boundary.phase.value,
                        "status": self._boundary.status})

    # -- steps 3-7, shared by every path ---------------------------------

    def build(self, result: CanonicalAssessmentResult, *,
              locale: Optional[str] = None,
              template_version: Optional[str] = None,
              is_synthetic: bool = False) -> ReportResult:
        """Steps 3-7: project, validate, render and scan. No writing."""
        key = locale or self._locale
        template = template_version or self._template
        report = build_structured_report(result, locale=key,
                                         template_version=template)
        ledger = validate_fact_preservation(result, report)
        safe_status = validate_safe_status_rendering(report)
        markdown = render_markdown(report)
        json_text = render_json(report)
        rendered_verification = validate_rendered_report(report, markdown,
                                                         ledger)
        scan = require_clean_report(markdown, boundary=self._boundary)
        # The JSON form carries the same strings, so it is scanned too. A
        # report published only as JSON would otherwise bypass the gate.
        require_clean_report(json_text, boundary=self._boundary)
        return ReportResult(
            assessment_id=result.assessment_id, locale=key,
            template_version=template, report=report, result=result,
            markdown=markdown, json_text=json_text, fact_ledger=ledger,
            claim_scan=claim_scan_evidence(scan), safe_status=safe_status,
            rendered_verification=rendered_verification,
            is_synthetic=is_synthetic)

    # -- the whole path --------------------------------------------------

    def generate(self, assessment_id: Any, *, locale: Optional[str] = None,
                 template_version: Optional[str] = None,
                 directory: Optional[str] = None) -> ReportResult:
        """Steps 1-8 for one stored, real assessment."""
        self._require_boundary()
        view = self._read(assessment_id)
        result = canonical_result_from_read_model(view)
        produced = self.build(result, locale=locale,
                              template_version=template_version)
        if directory is None:
            return produced
        return self._write(produced, directory=directory)

    def render_synthetic(self, view: Any, *, locale: Optional[str] = None,
                         template_version: Optional[str] = None,
                         directory: Optional[str] = None) -> ReportResult:
        """The same pipeline over a synthetic read model. Never evidence.

        Takes a read model directly rather than an identity, so it cannot
        accidentally reach a real store, and flags its result so nothing
        downstream can count it as a real report.
        """
        result = canonical_result_from_read_model(view)
        produced = self.build(result, locale=locale,
                              template_version=template_version,
                              is_synthetic=True)
        if directory is None:
            return produced
        return self._write(produced, directory=directory)

    def regenerate_from_document(self, document: Mapping[str, Any], *,
                                 locale: Optional[str] = None,
                                 template_version: Optional[str] = None,
                                 is_synthetic: bool = True) -> ReportResult:
        """Rebuild a report from a canonical result document.

        Used to verify that a written artifact still renders to the bytes it
        was published with. The document's own hash is checked during
        construction, so a document edited on disk is refused rather than
        re-rendered.
        """
        result = canonical_result_from_document(document)
        return self.build(result, locale=locale,
                          template_version=template_version,
                          is_synthetic=is_synthetic)

    def verify_artifact(self, manifest_path: str) -> Dict[str, Any]:
        """Read one published artifact back and verify it against its
        manifest. Reads bytes; renders nothing and calculates nothing."""
        return read_artifact(manifest_path)

    # -- internals -------------------------------------------------------

    def _read(self, assessment_id: Any):
        if self._read_port is None:
            raise ReportInputError(
                "no assessment read port is configured, so there is no "
                "stored assessment to report on. Reporting does not "
                "calculate one to fill the gap.",
                code="REPORT_ASSESSMENT_NOT_FOUND", location="$.read_port")
        view = self._read_port.read_model(assessment_id)
        if view is None:
            raise ReportInputError(
                "no stored assessment carries this identity",
                code="REPORT_ASSESSMENT_NOT_FOUND",
                location="$.assessment_id")
        return view

    def _write(self, produced: ReportResult, *, directory: str
               ) -> ReportResult:
        """Step 8, with the one destination rule synthetic output must obey."""
        import dataclasses
        import os
        normalised = os.path.normpath(directory).replace(os.sep, "/")
        if produced.is_synthetic and PRODUCTION_ARTIFACT_MARKER in normalised:
            raise ReportError(
                "a synthetic report was directed at %s. Synthetic output is "
                "never filed where real output is read from: a document in "
                "that directory will be cited as one."
                % PRODUCTION_ARTIFACT_MARKER,
                code="REPORT_SYNTHETIC_DESTINATION_REFUSED",
                location="$.directory")
        artifact = write_artifact(produced.report, rendered=produced.markdown,
                                  fact_ledger=produced.fact_ledger,
                                  claim_scan=produced.claim_scan,
                                  directory=directory)
        return dataclasses.replace(produced, artifact=artifact)
