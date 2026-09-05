# -*- coding: utf-8 -*-
"""One synthetic assessment world, built once per test class that needs it.

A frozen WP-11 ruleset on a temporary path, a verified WP-13 coverage manifest
over it, an ACTIVE synthetic release naming both, an approved synthetic claim
boundary, and an in-memory assessment store - assembled through each work
package's own services rather than hand-built, so what this exercises is the
real path and not a shape resembling it.
"""

from __future__ import annotations

import datetime as _dt
import os
import shutil
import tempfile
from typing import Any, Dict, Mapping, Optional, Sequence

from pgx.application.execution_context import audit_context_fields
from pgx.application.assessment_models import AssessmentInput
from pgx.application.assessment_service import AssessmentService
from pgx.domain.claims import OperationMode, PermittedInputKind
from pgx.domain.identifiers import AssessmentId
from tests.fixtures.wp13.synthetic import (DRUG_1, DRUG_2, GENE_1, GENE_2,
                                           GENE_3, SYNTHETIC_DRUG_CATALOGUE,
                                           UNKNOWN_DRUG,
                                           synthetic_evidence_resolver,
                                           synthetic_frozen_ruleset,
                                           synthetic_manifest,
                                           synthetic_profile)
from tests.fixtures.wp14.synthetic import (NOW, TEST_ACTOR,
                                           RecordingAuditSink,
                                           SyntheticReleaseResolver,
                                           frozen_ruleset_with_levels,
                                           synthetic_claim_boundary,
                                           synthetic_release_bundle)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

#: A resolver over the WP-11 fixture's evidence uuids. Module level rather
#: than a class attribute: a plain function assigned to a class becomes a
#: bound method on access, and the engine would be handed a two-argument
#: callable where it expects one.
RESOLVER = synthetic_evidence_resolver()


def assessment_row_mapping(stored: Dict[str, Any]) -> Dict[str, Any]:
    """The assessment row's columns, as the database would hold them."""
    assessment = stored["assessment"]
    provenance = stored["provenance"]
    row = {
        "assessment_id": assessment.id.to_json(),
        "mode": assessment.mode.value,
        "input_kind": assessment.input_kind.value,
        "case_id": assessment.case_id,
        "actor": stored["actor"],
        "input_hash": assessment.input_hash,
        "output_hash": assessment.output_hash,
        "input_snapshot": dict(stored["input_snapshot"]),
        "output_snapshot": dict(stored["output_snapshot"]),
        "overall_coverage": assessment.overall_coverage.value,
        "overall_attention": assessment.calculated_overall_attention.value,
        "created_at": stored["created_at"],
        "completed_at": assessment.completed_at,
    }
    document = provenance.to_json()
    for name in ("release_public_id", "release_manifest_hash",
                 "active_pointer_generation", "software_version",
                 "software_source_tree_hash", "dataset_public_id",
                 "canonical_build_content_hash", "ruleset_public_id",
                 "ruleset_content_hash", "evidence_build_key",
                 "evidence_build_content_hash", "coverage_manifest_hash",
                 "protocol_version", "protocol_content_hash",
                 "source_policy_version", "source_policy_content_hash"):
        row[name] = document[name]
    return row


def medication_row_mappings(computation):
    return [{
        "ordinal": ordinal,
        "drug_canonical_key": item.drug_canonical_key,
        "requested_value": item.requested_value,
        "attention_level": item.attention_level.value,
        "coverage_status": item.coverage_status.value,
        "coverage_reason_codes": [code.value
                                  for code in item.coverage_reason_codes],
        "axis_count": item.axis_count,
        "conflicted_axis_count": item.conflicted_axis_count,
    } for ordinal, item in enumerate(computation.medications)]


def axis_row_mappings(computation):
    rows = []
    for medication in computation.coverage_result.medications:
        for ordinal, axis in enumerate(medication.axes):
            rows.append({
                "ordinal": ordinal,
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
    return rows


def finding_row_mappings(computation):
    rows = []
    for medication in computation.medications:
        for ordinal, finding in enumerate(medication.findings):
            rows.append({
                "ordinal": ordinal,
                "drug_canonical_key": finding.drug_canonical_key,
                "gene_canonical_key": finding.gene_canonical_key,
                "phenotype": finding.phenotype.value,
                "attention_level": finding.attention_level.value,
                "rule_id": finding.rule_id,
                "rule_family_id": finding.rule_family_id,
                "rule_version": finding.rule_version,
                "rule_content_hash": finding.rule_content_hash,
                "rationale_reference": finding.rationale_reference,
                "curation_revision_id": finding.curation_revision_id,
                "curation_revision_hash": finding.curation_revision_hash,
                "effect_code": finding.effect_code,
                "explanation_code": finding.explanation_code,
                "evidence_record_ids": list(finding.evidence_references),
            })
    return rows


class InMemoryAssessmentRepository:
    """The AssessmentRepository port, in memory.

    Append-only by construction: there is no update method and no delete
    method, so a caller reaching for one gets an ``AttributeError`` at the
    point of the mistake rather than a silently-mutated stored assessment.
    """

    def __init__(self) -> None:
        self._rows: Dict[str, Dict[str, Any]] = {}

    def add(self, *, assessment, computation, input_snapshot, output_snapshot,
            actor, created_at, context=None) -> None:
        provenance = assessment.require_complete_release_metadata()
        key = assessment.id.to_json()
        if key in self._rows:
            raise ValueError("assessment %s already stored" % key)
        self._rows[key] = {
            "assessment": assessment,
            "computation": computation,
            "input_snapshot": dict(input_snapshot),
            "output_snapshot": dict(output_snapshot),
            "actor": actor,
            "created_at": created_at,
            "provenance": provenance,
            "context": context,
        }

    def get(self, assessment_id: AssessmentId):
        row = self._rows.get(assessment_id.to_json())
        return None if row is None else row["assessment"]

    def read_model(self, assessment_id: AssessmentId):
        """The WP-15 preflight 3.4 render source, over in-memory rows.

        Shapes the same column mapping the SQLAlchemy adapter shapes and hands
        it to the same builder, so what is exercised here is the real
        reconstruction and not a shortcut around it. The two column shapes are
        asserted to agree by a test that reads the adapter's source, because
        SQLAlchemy cannot be installed in this environment and a fake that had
        quietly drifted would prove nothing.
        """
        from pgx.application.assessment_read_model import (
            build_assessment_read_model)
        stored = self._rows.get(assessment_id.to_json())
        if stored is None:
            return None
        return build_assessment_read_model(
            row=assessment_row_mapping(stored),
            medications=medication_row_mappings(stored["computation"]),
            axes=axis_row_mappings(stored["computation"]),
            findings=finding_row_mappings(stored["computation"]))

    def row(self, assessment_id: AssessmentId):
        return self._rows.get(assessment_id.to_json())

    def summary(self, assessment_id: AssessmentId):
        """The WP-14 summary shape, kept so the two can be compared."""
        stored = self._rows.get(assessment_id.to_json())
        if stored is None:
            return None
        assessment = stored["assessment"]
        return {
            "assessment_id": assessment.id.to_json(),
            "input_hash": assessment.input_hash,
            "output_hash": assessment.output_hash,
            "input_snapshot": dict(stored["input_snapshot"]),
            "output_snapshot": dict(stored["output_snapshot"]),
            "overall_coverage": assessment.overall_coverage.value,
            "overall_attention":
                assessment.calculated_overall_attention.value,
            "release_public_id": stored["provenance"].release_public_id,
            "medication_count": len(stored["computation"].medications),
            "finding_count": len(stored["computation"].findings),
        }

    def list_ids(self):
        return tuple(sorted(self._rows))

    def __len__(self) -> int:
        return len(self._rows)


class InMemoryUnitOfWork:
    """One transaction, in memory, with the same all-or-nothing contract."""

    def __init__(self, store: InMemoryAssessmentRepository, *,
                 fail_on_commit: bool = False,
                 audit: Optional[RecordingAuditSink] = None) -> None:
        self._store = store
        self._fail_on_commit = fail_on_commit
        self._staged: list = []
        self._audit = audit
        self.committed = False
        self.assessments = self

    # -- repository surface (staged, not applied) ------------------------

    def add(self, **kwargs) -> None:
        self._staged.append(kwargs)

    # -- context management ---------------------------------------------

    def __enter__(self) -> "InMemoryUnitOfWork":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self.committed:
            self._staged = []

    def commit(self) -> None:
        if self._fail_on_commit:
            raise RuntimeError("synthetic persistence failure")
        for staged in self._staged:
            self._store.add(**staged)
            if self._audit is not None:
                # Mirrors SqlAlchemyAssessmentRepository: the completion event
                # carries the request context's fields and no case content.
                record = {
                    "action": "ASSESSMENT_COMPLETED",
                    "actor": staged["actor"],
                    "assessment_id": staged["assessment"].id.to_json(),
                    "output_hash": staged["assessment"].output_hash,
                }
                record.update(audit_context_fields(staged.get("context")))
                self._audit.record_completion(record)
        self._staged = []
        self.committed = True


class SyntheticAssessmentWorld:
    """A whole governed world, synthetic end to end."""

    def __init__(self, *, expected_extra_gene: bool = True,
                 fail_on_commit: bool = False, persist: bool = True,
                 clock: Optional[Any] = None,
                 attention_levels: Optional[Sequence[Any]] = None):
        self.tmp = tempfile.mkdtemp()
        destination = os.path.join(self.tmp, "rulesets",
                                   "PGX-RULESET-29991231-001")
        if attention_levels is None:
            self.frozen, self.definitions = synthetic_frozen_ruleset(
                destination, count=2)
        else:
            # Rules carrying chosen governed outcomes, built through the same
            # WP-11 chain. Varying the outcome is what makes an aggregation
            # test test aggregation rather than a fixture constant.
            self.frozen, self.definitions = frozen_ruleset_with_levels(
                destination, tuple(attention_levels))
        self.manifest = synthetic_manifest(
            self.frozen, expected_extra_gene=expected_extra_gene)
        self.release = synthetic_release_bundle()
        self.resolver = SyntheticReleaseResolver(
            release=self.release, frozen_ruleset=self.frozen,
            coverage_manifest=self.manifest,
            drug_catalogue=SYNTHETIC_DRUG_CATALOGUE,
            evidence_resolver=RESOLVER)
        self.store = InMemoryAssessmentRepository()
        self.audit = RecordingAuditSink()
        self.boundary = synthetic_claim_boundary()
        self._fail_on_commit = fail_on_commit
        factory = (self._uow if persist else None)
        self.service = AssessmentService(
            release_resolver=self.resolver, uow_factory=factory,
            claim_boundary=self.boundary,
            clock=clock or (lambda: NOW), audit_sink=self.audit)

    def _uow(self) -> InMemoryUnitOfWork:
        return InMemoryUnitOfWork(self.store,
                                  fail_on_commit=self._fail_on_commit,
                                  audit=self.audit)

    def close(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- building requests ----------------------------------------------

    def input(self, *, medications: Sequence[str] = (DRUG_1,),
              phenotypes: Optional[Mapping[str, Any]] = None,
              mode: OperationMode = OperationMode.DEMO,
              input_kind: PermittedInputKind =
              PermittedInputKind.SYNTHETIC_PHENOTYPE_PROFILE,
              case_id: Optional[str] = "TEST-CASE-1",
              release_id: Optional[str] = None) -> AssessmentInput:
        values = phenotypes if phenotypes is not None else {GENE_1: "POOR",
                                                            GENE_2: "POOR"}
        return AssessmentInput(
            mode=mode, input_kind=input_kind,
            profile=synthetic_profile(values),
            medications=tuple(medications), case_id=case_id,
            requested_release_public_id=release_id)

    def execute(self, *, actor: str = TEST_ACTOR, **kwargs):
        return self.service.execute(self.input(**kwargs), actor=actor)

    def dry_run(self, **kwargs):
        return self.service.dry_run(self.input(**kwargs))
