# -*- coding: utf-8 -*-
"""SQLAlchemy adapter for the WP-14 assessment port.

A repository and a unit-of-work mixin, not ORM classes: every mapped class
lives in :mod:`pgx.infrastructure.db.models`, and the boundary test asserting
that is worth more than the convenience of defining one here.

Three things are load-bearing.

**The repository has no update and no delete.** Not private ones, not disabled
ones: the methods do not exist, so a caller reaching for one gets an
``AttributeError`` at the point of the mistake. Migration 0009 installs
triggers that refuse ``UPDATE`` and ``DELETE`` on every assessment table, so
the guarantee survives a ``psql`` prompt as well as a code review.

**One assessment is one transaction.** The assessment, its medications, its
axes, its findings, the evidence links and the audit event are staged together
and committed together. There is no path that writes a finding without its
assessment, and none that records ``ASSESSMENT_COMPLETED`` for a calculation
that did not commit.

**Release metadata is checked before the insert, not after.**
:meth:`Assessment.require_complete_release_metadata` runs first, so an
assessment missing a pinned version never reaches a database that would have to
reject it - and the NOT NULL columns are the second line, not the first
(``SAFETY-INV-007``).
"""

from __future__ import annotations

import datetime as _dt
import uuid
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from pgx.domain.enums import AuditAction
from pgx.domain.identifiers import AssessmentId
from pgx.domain.models import Assessment
from pgx.engine.risk_errors import AssessmentPersistenceError

__all__ = [
    "ASSESSMENT_AUDIT_ACTIONS",
    "SqlAlchemyAssessmentRepository",
    "assessment_to_rows",
]

#: WP-15 preflight 3.4. ``get`` returns a summary; ``read_model`` returns the
#: complete, verified render source. Both stay: the summary is what a listing
#: wants, and a listing that had to reconstruct every axis to show a row count
#: would be slower for no benefit. The names say which is which.

#: The two audit actions WP-14 writes. A success is recorded only in the same
#: transaction as the assessment it describes; a refusal carries a stable code
#: and no case content.
ASSESSMENT_AUDIT_ACTIONS: Tuple[str, ...] = ("ASSESSMENT_COMPLETED",
                                             "ASSESSMENT_REFUSED")


def _uuid(value: Any) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def assessment_to_rows(*, assessment: Assessment, computation: Any,
                       input_snapshot: Mapping[str, Any],
                       output_snapshot: Mapping[str, Any], actor: str,
                       created_at: _dt.datetime) -> Dict[str, Any]:
    """Turn one completed assessment into the rows that persist it.

    Pure: it builds row payloads and touches no session, so the mapping can be
    tested without a database. Ordinals are assigned from the already-sorted
    collections, so the stored order is the canonical order rather than
    whatever order rows happened to be inserted in.
    """
    provenance = assessment.require_complete_release_metadata()
    assessment_uuid = _uuid(assessment.id.to_json())

    medication_rows: List[Dict[str, Any]] = []
    axis_rows: List[Dict[str, Any]] = []
    finding_rows: List[Dict[str, Any]] = []
    evidence_rows: List[Dict[str, Any]] = []

    coverage_by_drug = {
        item.medication.drug_canonical_key or item.medication.requested_value:
            item
        for item in computation.coverage_result.medications}

    for ordinal, medication in enumerate(computation.medications):
        medication_uuid = uuid.uuid4()
        medication_rows.append({
            "id": medication_uuid,
            "assessment_id": assessment_uuid,
            "ordinal": ordinal,
            "drug_canonical_key": medication.drug_canonical_key,
            "requested_value": medication.requested_value,
            "attention_level": medication.attention_level.value,
            "coverage_status": medication.coverage_status.value,
            "coverage_reason_codes": [code.value for code
                                      in medication.coverage_reason_codes],
            "axis_count": medication.axis_count,
            "conflicted_axis_count": medication.conflicted_axis_count,
        })

        coverage = coverage_by_drug.get(medication.drug_canonical_key)
        axes = coverage.axes if coverage is not None else ()
        for axis_ordinal, axis in enumerate(axes):
            axis_rows.append({
                "id": uuid.uuid4(),
                "assessment_id": assessment_uuid,
                "medication_id": medication_uuid,
                "ordinal": axis_ordinal,
                "drug_canonical_key": axis.drug_canonical_key,
                "gene_canonical_key": axis.gene_canonical_key,
                "observed_phenotype": (axis.observed_phenotype.value
                                       if axis.observed_phenotype else None),
                "observation_state": axis.observation_state or "NOT_EVALUATED",
                "coverage_status": axis.status.value,
                "coverage_reason_codes": [code.value
                                          for code in axis.reason_codes],
                "rule_references": [dict(item)
                                    for item in axis.rule_references],
                "evidence_references": list(axis.evidence_references),
                "conflict_references": list(axis.conflict_references),
            })

        for finding_ordinal, finding in enumerate(medication.findings):
            finding_uuid = uuid.uuid4()
            finding_rows.append({
                "id": finding_uuid,
                "assessment_id": assessment_uuid,
                "medication_id": medication_uuid,
                "ordinal": finding_ordinal,
                "drug_canonical_key": finding.drug_canonical_key,
                "gene_canonical_key": finding.gene_canonical_key,
                "phenotype": finding.phenotype.value,
                "attention_level": finding.attention_level.value,
                "rule_id": _uuid(finding.rule_id),
                "rule_family_id": finding.rule_family_id,
                "rule_version": finding.rule_version,
                "rule_content_hash": finding.rule_content_hash,
                "rationale_reference": finding.rationale_reference,
                "curation_revision_id": finding.curation_revision_id,
                "curation_revision_hash": finding.curation_revision_hash,
                "effect_code": finding.effect_code,
                "explanation_code": finding.explanation_code,
            })
            for reference in finding.evidence_references:
                evidence_rows.append({
                    "finding_id": finding_uuid,
                    "evidence_record_id": _uuid(reference),
                    "assessment_id": assessment_uuid,
                })

    return {
        "assessment": {
            "id": assessment_uuid,
            "release_id": _uuid(assessment.release_bundle_id.to_json()),
            "mode": assessment.mode.value,
            "input_kind": assessment.input_kind.value,
            "case_id": assessment.case_id,
            "actor": actor,
            "input_snapshot": dict(input_snapshot),
            "input_hash": assessment.input_hash,
            "output_snapshot": dict(output_snapshot),
            "output_hash": assessment.output_hash,
            "overall_coverage": computation.overall_coverage.value,
            "overall_attention": computation.overall_attention.value,
            "release_public_id": provenance.release_public_id,
            "release_manifest_hash": provenance.release_manifest_hash,
            "active_pointer_generation": provenance.active_pointer_generation,
            "software_version_id": _uuid(
                provenance.software_version_id.to_json()),
            "software_version": provenance.software_version,
            "software_source_tree_hash": provenance.software_source_tree_hash,
            "dataset_version_id": _uuid(
                provenance.dataset_version_id.to_json()),
            "dataset_public_id": provenance.dataset_public_id,
            "canonical_build_content_hash":
                provenance.canonical_build_content_hash,
            "ruleset_version_id": _uuid(
                provenance.ruleset_version_id.to_json()),
            "ruleset_public_id": provenance.ruleset_public_id,
            "ruleset_content_hash": provenance.ruleset_content_hash,
            "evidence_build_key": provenance.evidence_build_key,
            "evidence_build_content_hash":
                provenance.evidence_build_content_hash,
            "coverage_manifest_hash": provenance.coverage_manifest_hash,
            "protocol_version": provenance.protocol_version,
            "protocol_content_hash": provenance.protocol_content_hash,
            "source_policy_version": provenance.source_policy_version,
            "source_policy_content_hash":
                provenance.source_policy_content_hash,
            "created_at": created_at,
            "completed_at": created_at,
        },
        "medications": medication_rows,
        "axes": axis_rows,
        "findings": finding_rows,
        "evidence": evidence_rows,
    }


#: Row -> plain mapping. Written as free functions rather than ORM methods so
#: the read model can be built and tested from plain dictionaries in an
#: environment with no database, which is the environment this repository is
#: developed in.
def _assessment_row_to_mapping(row: Any) -> Dict[str, Any]:
    return {
        "assessment_id": str(row.id),
        "mode": row.mode,
        "input_kind": row.input_kind,
        "case_id": row.case_id,
        "actor": row.actor,
        "input_hash": row.input_hash,
        "output_hash": row.output_hash,
        "input_snapshot": row.input_snapshot,
        "output_snapshot": row.output_snapshot,
        "overall_coverage": row.overall_coverage,
        "overall_attention": row.overall_attention,
        "release_public_id": row.release_public_id,
        "release_manifest_hash": row.release_manifest_hash,
        "active_pointer_generation": row.active_pointer_generation,
        "software_version": row.software_version,
        "software_source_tree_hash": row.software_source_tree_hash,
        "dataset_public_id": row.dataset_public_id,
        "canonical_build_content_hash": row.canonical_build_content_hash,
        "ruleset_public_id": row.ruleset_public_id,
        "ruleset_content_hash": row.ruleset_content_hash,
        "evidence_build_key": row.evidence_build_key,
        "evidence_build_content_hash": row.evidence_build_content_hash,
        "coverage_manifest_hash": row.coverage_manifest_hash,
        "protocol_version": row.protocol_version,
        "protocol_content_hash": row.protocol_content_hash,
        "source_policy_version": row.source_policy_version,
        "source_policy_content_hash": row.source_policy_content_hash,
        "created_at": row.created_at,
        "completed_at": row.completed_at,
    }


def _medication_row_to_mapping(row: Any) -> Dict[str, Any]:
    return {
        "ordinal": row.ordinal,
        "drug_canonical_key": row.drug_canonical_key,
        "requested_value": row.requested_value,
        "attention_level": row.attention_level,
        "coverage_status": row.coverage_status,
        "coverage_reason_codes": list(row.coverage_reason_codes or ()),
        "axis_count": row.axis_count,
        "conflicted_axis_count": row.conflicted_axis_count,
    }


def _axis_row_to_mapping(row: Any) -> Dict[str, Any]:
    return {
        "ordinal": row.ordinal,
        "drug_canonical_key": row.drug_canonical_key,
        "gene_canonical_key": row.gene_canonical_key,
        "observed_phenotype": row.observed_phenotype,
        "observation_state": row.observation_state,
        "coverage_status": row.coverage_status,
        "coverage_reason_codes": list(row.coverage_reason_codes or ()),
        "rule_references": [dict(item) for item in (row.rule_references or ())],
        "evidence_references": list(row.evidence_references or ()),
        "conflict_references": list(row.conflict_references or ()),
    }


def _finding_row_to_mapping(row: Any,
                            evidence_record_ids: Sequence[str]
                            ) -> Dict[str, Any]:
    return {
        "ordinal": row.ordinal,
        "drug_canonical_key": row.drug_canonical_key,
        "gene_canonical_key": row.gene_canonical_key,
        "phenotype": row.phenotype,
        "attention_level": row.attention_level,
        "rule_id": str(row.rule_id),
        "rule_family_id": row.rule_family_id,
        "rule_version": row.rule_version,
        "rule_content_hash": row.rule_content_hash,
        "rationale_reference": row.rationale_reference,
        "curation_revision_id": row.curation_revision_id,
        "curation_revision_hash": row.curation_revision_hash,
        "effect_code": row.effect_code,
        "explanation_code": row.explanation_code,
        "evidence_record_ids": list(evidence_record_ids),
    }


def _audit_event_metadata(*, assessment: Assessment,
                          row: Mapping[str, Any],
                          context: Any) -> Dict[str, Any]:
    """What the ``ASSESSMENT_COMPLETED`` audit event records.

    A fixed set of keys: the two hashes that identify the question and the
    answer, the release the answer was pinned to, the two governed status
    values, and - when the caller supplied one - the request context's actor,
    role, channel and correlation id.

    What is absent is the design. No medication list, no phenotype profile, no
    case narrative and no snapshot: an audit row outlives the request, is read
    by operators who have no reason to see case content, and is exported to
    places an assessment row is not. The keys here are all governed
    vocabulary, identifiers and hashes.
    """
    from pgx.application.execution_context import audit_context_fields

    document: Dict[str, Any] = {
        "output_hash": assessment.output_hash,
        "input_hash": assessment.input_hash,
        "release_public_id": row["release_public_id"],
        "overall_coverage": row["overall_coverage"],
        "overall_attention": row["overall_attention"],
    }
    document.update(audit_context_fields(context))
    return document


class SqlAlchemyAssessmentRepository:
    """Append-only persistence for completed assessments.

    No ``update`` method and no ``delete`` method. The absence is the contract.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, *, assessment: Assessment, computation: Any,
            input_snapshot: Mapping[str, Any],
            output_snapshot: Mapping[str, Any], actor: str,
            created_at: _dt.datetime, context: Any = None) -> None:
        """Stage one completed assessment and every child row.

        Args:
            context: the optional
                :class:`~pgx.application.execution_context.ExecutionContext`
                for this call. Its fields are written into the audit event's
                JSON metadata - role, channel and correlation id - and into
                nothing else. They are not columns, not part of any hash and
                not part of the assessment row: an audit row records the
                circumstances of an act, and the assessment records the act.

        Raises:
            AssessmentPersistenceError: the assessment is missing pinned
                release metadata, or an assessment with this identity is
                already stored. Neither is repaired: a duplicate identity means
                two different calculations claim to be the same one, and
                choosing between them is not a persistence decision.
        """
        from pgx.infrastructure.db.models import (AssessmentAxisORM,
                                                  AssessmentFindingEvidenceORM,
                                                  AssessmentFindingORM,
                                                  AssessmentMedicationORM,
                                                  AssessmentORM, AuditEventORM)

        rows = assessment_to_rows(
            assessment=assessment, computation=computation,
            input_snapshot=input_snapshot, output_snapshot=output_snapshot,
            actor=actor, created_at=created_at)

        existing = self._session.get(AssessmentORM, rows["assessment"]["id"])
        if existing is not None:
            raise AssessmentPersistenceError(
                "assessment %s is already stored; a completed assessment is "
                "immutable and is never rewritten"
                % assessment.id.to_json(),
                code="ASSESSMENT_PERSISTENCE_REFUSED",
                location="$.assessment_id")

        self._session.add(AssessmentORM(**rows["assessment"]))
        for row in rows["medications"]:
            self._session.add(AssessmentMedicationORM(**row))
        for row in rows["axes"]:
            self._session.add(AssessmentAxisORM(**row))
        for row in rows["findings"]:
            self._session.add(AssessmentFindingORM(**row))
        for row in rows["evidence"]:
            self._session.add(AssessmentFindingEvidenceORM(**row))
        self._session.add(AuditEventORM(
            id=uuid.uuid4(),
            action=AuditAction.ASSESSMENT_COMPLETED.value,
            actor=actor,
            object_type="assessment",
            object_id=assessment.id.to_json(),
            occurred_at=created_at,
            reason=None,
            event_metadata=_audit_event_metadata(
                assessment=assessment, row=rows["assessment"],
                context=context)))

    def get(self, assessment_id: AssessmentId) -> Optional[Dict[str, Any]]:
        """Return the stored rows for this assessment, or ``None``.

        Returns the persistence record rather than a reconstructed
        :class:`Assessment`: what a caller wants back from a stored assessment
        is the structured facts it recorded, and rebuilding the aggregate would
        mean re-deriving identities the row does not carry.
        """
        from pgx.infrastructure.db.models import (AssessmentFindingORM,
                                                  AssessmentMedicationORM,
                                                  AssessmentORM)

        row = self._session.get(AssessmentORM, _uuid(assessment_id.to_json()))
        if row is None:
            return None
        medications = self._session.execute(
            select(AssessmentMedicationORM)
            .where(AssessmentMedicationORM.assessment_id == row.id)
            .order_by(AssessmentMedicationORM.ordinal)).scalars().all()
        findings = self._session.execute(
            select(AssessmentFindingORM)
            .where(AssessmentFindingORM.assessment_id == row.id)
            .order_by(AssessmentFindingORM.ordinal)).scalars().all()
        return {
            "assessment_id": str(row.id),
            "input_hash": row.input_hash,
            "output_hash": row.output_hash,
            "input_snapshot": row.input_snapshot,
            "output_snapshot": row.output_snapshot,
            "overall_coverage": row.overall_coverage,
            "overall_attention": row.overall_attention,
            "release_public_id": row.release_public_id,
            "medication_count": len(medications),
            "finding_count": len(findings),
        }

    def read_model(self, assessment_id: AssessmentId):
        """Return the complete render source for one assessment, or ``None``.

        The lossless counterpart of :meth:`get`. It reads rows and verifies
        hashes, and it runs no engine: no coverage is recomputed, no rule is
        re-selected, no active-release pointer is consulted. What comes back
        is what was stored, checked against itself.
        """
        from pgx.application.assessment_read_model import (
            build_assessment_read_model)
        from pgx.infrastructure.db.models import (AssessmentAxisORM,
                                                  AssessmentFindingEvidenceORM,
                                                  AssessmentFindingORM,
                                                  AssessmentMedicationORM,
                                                  AssessmentORM)

        row = self._session.get(AssessmentORM, _uuid(assessment_id.to_json()))
        if row is None:
            return None
        medications = self._session.execute(
            select(AssessmentMedicationORM)
            .where(AssessmentMedicationORM.assessment_id == row.id)
            .order_by(AssessmentMedicationORM.ordinal)).scalars().all()
        axes = self._session.execute(
            select(AssessmentAxisORM)
            .where(AssessmentAxisORM.assessment_id == row.id)
            .order_by(AssessmentAxisORM.medication_id,
                      AssessmentAxisORM.ordinal)).scalars().all()
        findings = self._session.execute(
            select(AssessmentFindingORM)
            .where(AssessmentFindingORM.assessment_id == row.id)
            .order_by(AssessmentFindingORM.medication_id,
                      AssessmentFindingORM.ordinal)).scalars().all()
        evidence = self._session.execute(
            select(AssessmentFindingEvidenceORM)
            .where(AssessmentFindingEvidenceORM.assessment_id == row.id)
            ).scalars().all()
        by_finding: Dict[Any, List[str]] = {}
        for link in evidence:
            by_finding.setdefault(link.finding_id, []).append(
                str(link.evidence_record_id))
        return build_assessment_read_model(
            row=_assessment_row_to_mapping(row),
            medications=[_medication_row_to_mapping(item)
                         for item in medications],
            axes=[_axis_row_to_mapping(item) for item in axes],
            findings=[_finding_row_to_mapping(
                item, sorted(by_finding.get(item.id, ())))
                for item in findings])

    def list_for_release(self, release_public_id: str) -> Sequence[str]:
        """Assessment ids executed against one release, oldest first."""
        from pgx.infrastructure.db.models import AssessmentORM
        rows = self._session.execute(
            select(AssessmentORM.id)
            .where(AssessmentORM.release_public_id == release_public_id)
            .order_by(AssessmentORM.created_at, AssessmentORM.id)).scalars()
        return tuple(str(value) for value in rows)
