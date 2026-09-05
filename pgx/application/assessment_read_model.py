# -*- coding: utf-8 -*-
"""The lossless read model of a stored assessment (WP-15 preflight).

WP-14 could store an assessment and give you back a summary: two hashes, two
statuses, and the number of medications and findings. That is enough to
recognise a row and nowhere near enough to render one. A report has to name
every axis, its coverage status, its observed phenotype, its reason codes, its
rule and its evidence - and it must do so **without recomputing any of it**,
because a reporting layer that re-derives a governed fact is a second engine
whose disagreements with the first nobody would notice.

So this module reconstructs, from stored rows alone:

* the assessment's identity, actor, case label and timestamps;
* the complete canonical input, including the normalised phenotype profile;
* the complete calculated output, including the whole embedded WP-13 coverage
  result;
* every medication, axis and finding row, with its rule and evidence
  provenance;
* every pinned version, and the pointer generation recorded beside them.

**Nothing here calculates.** There is no call to the risk engine, the coverage
engine, rule selection, or active-release resolution, and a boundary test
asserts that by name. The only computation performed is *verification*:
re-hashing what was stored and refusing when it disagrees.

**Every disagreement is a refusal.** A snapshot that does not hash back, a
document that does not recompute to its own output hash, an embedded coverage
result that does not match the hash beside it, a row that contradicts the
snapshot it was written with - each raises. A render source that quietly
carried one of those would produce a report that looks exactly like a correct
one.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.application.assessment_snapshot import verify_input_snapshot
from pgx.domain.hashing import sha256_digest
from pgx.domain.immutable import freeze_json
from pgx.engine.risk import embedded_coverage_result, hashed_projection
from pgx.engine.risk_errors import (AssessmentArtifactError,
                                    AssessmentPersistenceError)

__all__ = [
    "ASSESSMENT_READ_MODEL_SCHEMA_VERSION",
    "READ_MODEL_ROW_KEYS",
    "AssessmentReadModel",
    "build_assessment_read_model",
]

ASSESSMENT_READ_MODEL_SCHEMA_VERSION = "pgx-assessment-read-model/1"

#: Columns the assessment row must supply. Enumerated so a partial row is
#: refused by name rather than surfacing later as a missing report section.
READ_MODEL_ROW_KEYS: Tuple[str, ...] = (
    "assessment_id", "mode", "input_kind", "case_id", "actor",
    "input_hash", "output_hash", "input_snapshot", "output_snapshot",
    "overall_coverage", "overall_attention", "release_public_id",
    "active_pointer_generation", "created_at", "completed_at",
)

#: Row columns that must equal the matching field of the stored computation.
#: A row and its snapshot are written in one transaction, so a disagreement
#: means one of them changed afterwards.
_ROW_AGREEMENTS: Tuple[Tuple[str, str], ...] = (
    ("input_hash", "input_hash"),
    ("output_hash", "output_hash"),
    ("overall_coverage", "overall_coverage"),
    ("overall_attention", "overall_attention"),
)

#: Provenance columns that must equal the matching pinned version in the
#: stored computation. Not every provenance field is duplicated onto the row;
#: the ones that are must agree.
_PROVENANCE_AGREEMENTS: Tuple[str, ...] = (
    "release_public_id", "release_manifest_hash", "ruleset_public_id",
    "ruleset_content_hash", "dataset_public_id",
    "canonical_build_content_hash", "evidence_build_key",
    "evidence_build_content_hash", "coverage_manifest_hash",
    "protocol_version", "protocol_content_hash", "source_policy_version",
    "source_policy_content_hash", "software_version",
    "software_source_tree_hash",
)


def _refuse(message: str, *, location: str,
            code: str = "ASSESSMENT_CONCURRENT_STATE_ERROR",
            detail: Optional[Mapping[str, Any]] = None) -> None:
    raise AssessmentPersistenceError(message, code=code, location=location,
                                     detail=detail)


def _plain(value: Any) -> Any:
    """A JSON-serialisable copy of a deeply frozen value.

    The read model freezes everything it holds so a renderer cannot edit a
    governed fact in place. Frozen mappings and tuples are not what ``json``
    knows how to write, so the JSON view thaws on the way out - into a copy,
    which is the point: a caller may do what it likes with the copy and the
    read model is unchanged.
    """
    if isinstance(value, Mapping):
        return {key: _plain(value[key]) for key in value}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _isoformat(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, _dt.datetime):
        moment = (value.replace(tzinfo=_dt.timezone.utc)
                  if value.tzinfo is None else value.astimezone(
                      _dt.timezone.utc))
        return moment.isoformat().replace("+00:00", "Z")
    return str(value)


@dataclass(frozen=True, slots=True)
class AssessmentReadModel:
    """Everything a report may read about one stored assessment.

    Deeply immutable: every mapping and sequence is frozen at construction, so
    a renderer cannot edit a governed fact on its way to the page and a
    validator that checked the object cannot be handed a different one
    afterwards.

    Deliberately absent: any attention or coverage value this type derived
    itself, any prose, any label, any locale, any template. Those are WP-15's
    presentation concerns and they are computed from this, never stored in it.
    """

    assessment_id: str
    mode: str
    input_kind: str
    case_id: Optional[str]
    actor: str
    created_at: Optional[str]
    completed_at: Optional[str]
    input_hash: str
    output_hash: str
    input_snapshot: Mapping[str, Any]
    computation: Mapping[str, Any]
    coverage_result: Mapping[str, Any]
    release_provenance: Mapping[str, Any]
    pointer_audit: Mapping[str, Any]
    medications: Tuple[Mapping[str, Any], ...]
    axes: Tuple[Mapping[str, Any], ...]
    findings: Tuple[Mapping[str, Any], ...]
    verification: Mapping[str, Any]
    read_model_schema_version: str = ASSESSMENT_READ_MODEL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("input_snapshot", "computation", "coverage_result",
                     "release_provenance", "pointer_audit", "verification"):
            object.__setattr__(self, name,
                               freeze_json(dict(getattr(self, name))))
        for name in ("medications", "axes", "findings"):
            object.__setattr__(
                self, name,
                tuple(freeze_json(dict(item)) for item in getattr(self, name)))

    # -- reading ---------------------------------------------------------

    @property
    def overall_coverage(self) -> str:
        return self.computation["overall_coverage"]

    @property
    def overall_attention(self) -> str:
        return self.computation["overall_attention"]

    @property
    def overall_coverage_reason_codes(self) -> Tuple[str, ...]:
        return tuple(self.computation.get("overall_coverage_reason_codes", ()))

    @property
    def medication_count(self) -> int:
        return len(self.medications)

    @property
    def finding_count(self) -> int:
        return len(self.findings)

    @property
    def warnings(self) -> Tuple[str, ...]:
        return tuple(self.computation.get("warnings", ()))

    def axes_for(self, drug_canonical_key: str
                 ) -> Tuple[Mapping[str, Any], ...]:
        """Every axis recorded for one medication, in canonical order."""
        return tuple(axis for axis in self.axes
                     if axis.get("drug_canonical_key") == drug_canonical_key)

    def findings_for(self, drug_canonical_key: str
                     ) -> Tuple[Mapping[str, Any], ...]:
        """Every finding recorded for one medication, in canonical order."""
        return tuple(finding for finding in self.findings
                     if finding.get("drug_canonical_key")
                     == drug_canonical_key)

    def to_json(self) -> Dict[str, Any]:
        return {
            "read_model_schema_version": self.read_model_schema_version,
            "assessment_id": self.assessment_id,
            "mode": self.mode,
            "input_kind": self.input_kind,
            "case_id": self.case_id,
            "actor": self.actor,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "input_snapshot": _plain(self.input_snapshot),
            "computation": _plain(self.computation),
            "coverage_result": _plain(self.coverage_result),
            "release_provenance": _plain(self.release_provenance),
            "pointer_audit": _plain(self.pointer_audit),
            "medication_count": self.medication_count,
            "medications": [_plain(item) for item in self.medications],
            "axis_count": len(self.axes),
            "axes": [_plain(item) for item in self.axes],
            "finding_count": self.finding_count,
            "findings": [_plain(item) for item in self.findings],
            "verification": _plain(self.verification),
        }


def build_assessment_read_model(*, row: Mapping[str, Any],
                                medications: Sequence[Mapping[str, Any]] = (),
                                axes: Sequence[Mapping[str, Any]] = (),
                                findings: Sequence[Mapping[str, Any]] = (),
                                ) -> AssessmentReadModel:
    """Reconstruct one stored assessment, or refuse.

    Args:
        row: the assessment row's columns.
        medications: medication rows, already in stored ordinal order.
        axes: axis rows, already in stored ordinal order.
        findings: finding rows, already in stored ordinal order, each carrying
            its ``evidence_record_ids``.

    Raises:
        AssessmentPersistenceError: the row is incomplete, or the row and the
            stored snapshots disagree.
        AssessmentInputError: the stored input snapshot is incomplete or does
            not hash back.
        AssessmentArtifactError: the stored computation carries no coverage
            result, or the embedded one does not match its hash.
    """
    if not isinstance(row, Mapping):
        _refuse("an assessment row is a mapping of columns", location="$")
    missing = tuple(name for name in READ_MODEL_ROW_KEYS if name not in row)
    if missing:
        _refuse("the stored assessment row is incomplete; it is missing %s"
                % ", ".join(missing), location="$",
                detail={"missing": list(missing)})

    computation = row["output_snapshot"]
    if not isinstance(computation, Mapping):
        _refuse("the stored output snapshot is an object",
                location="$.output_snapshot")

    # 1. The input still describes this question.
    snapshot_verification = verify_input_snapshot(row["input_snapshot"],
                                                  input_hash=row["input_hash"])

    # 2. The output still hashes to what the row records.
    recomputed = sha256_digest(hashed_projection(computation))
    declared = computation.get("output_hash")
    if recomputed != declared:
        _refuse("the stored computation recomputes to %s and declares %s"
                % (recomputed, declared), location="$.output_snapshot")
    if recomputed != row["output_hash"]:
        _refuse("the stored computation recomputes to %s; the assessment row "
                "records output hash %s. The row and the snapshot describe "
                "different results." % (recomputed, row["output_hash"]),
                location="$.output_hash")

    # 3. The coverage detail is present and matches the hash beside it.
    coverage_result = embedded_coverage_result(computation)

    # 4. The row's denormalised columns agree with the document.
    for column, key in _ROW_AGREEMENTS:
        if row[column] != computation.get(key):
            _refuse("the assessment row records %s=%r and the stored "
                    "computation records %r"
                    % (column, row[column], computation.get(key)),
                    location="$." + column)
    provenance = dict(computation.get("release_provenance") or {})
    if not provenance:
        _refuse("the stored computation names no pinned versions "
                "(SAFETY-INV-007)", location="$.release_provenance",
                code="ASSESSMENT_VERSION_MISMATCH")
    for name in _PROVENANCE_AGREEMENTS:
        if name in row and row[name] != provenance.get(name):
            _refuse("the assessment row records %s=%r and the stored "
                    "computation pins %r"
                    % (name, row[name], provenance.get(name)),
                    location="$." + name, code="ASSESSMENT_VERSION_MISMATCH")

    # 5. The child rows agree with the document they were written beside.
    medication_rows = [dict(item) for item in medications]
    axis_rows = [dict(item) for item in axes]
    finding_rows = [dict(item) for item in findings]
    document_medications = list(computation.get("medications") or ())
    if len(medication_rows) != len(document_medications):
        _refuse("%d medication rows are stored and the computation records "
                "%d" % (len(medication_rows), len(document_medications)),
                location="$.medications")
    document_keys = [item.get("drug_id") for item in document_medications]
    row_keys = [item.get("drug_canonical_key") for item in medication_rows]
    if row_keys != document_keys:
        _refuse("the stored medication rows name %s and the computation names "
                "%s" % (row_keys, document_keys), location="$.medications")
    document_finding_count = computation.get("finding_count")
    if len(finding_rows) != document_finding_count:
        _refuse("%d finding rows are stored and the computation records %r"
                % (len(finding_rows), document_finding_count),
                location="$.findings")
    for index, finding in enumerate(finding_rows):
        if not finding.get("evidence_record_ids"):
            raise AssessmentArtifactError(
                "stored finding %d cites no evidence; a finding without "
                "evidence is not renderable and was not persistable "
                "(SAFETY-INV-006)" % index,
                code="ASSESSMENT_EVIDENCE_MISSING",
                location="$.findings[%d].evidence_record_ids" % index)

    verification = {
        "read_model_schema_version": ASSESSMENT_READ_MODEL_SCHEMA_VERSION,
        "input_snapshot": dict(snapshot_verification),
        "recomputed_output_hash": recomputed,
        "coverage_result_hash": computation.get("coverage_result_hash"),
        "row_and_snapshot_agree": True,
        "recomputed_without_engine": True,
        "note": ("Every hash here was recomputed from stored bytes. Nothing "
                 "was recalculated: no coverage engine, no risk engine, no "
                 "rule selection and no active-release resolution ran to "
                 "produce this view."),
    }
    return AssessmentReadModel(
        assessment_id=str(row["assessment_id"]),
        mode=row["mode"],
        input_kind=row["input_kind"],
        case_id=row["case_id"],
        actor=row["actor"],
        created_at=_isoformat(row["created_at"]),
        completed_at=_isoformat(row["completed_at"]),
        input_hash=row["input_hash"],
        output_hash=row["output_hash"],
        input_snapshot=dict(row["input_snapshot"]),
        computation=dict(computation),
        coverage_result=coverage_result,
        release_provenance=provenance,
        pointer_audit={"active_pointer_generation":
                       row["active_pointer_generation"]},
        medications=tuple(medication_rows),
        axes=tuple(axis_rows),
        findings=tuple(finding_rows),
        verification=verification)
