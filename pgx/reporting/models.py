# -*- coding: utf-8 -*-
"""The canonical assessment result reporting is allowed to read (WP-15).

The boundary between "what was calculated" and "what is shown" needs a value
object, and this is it. Everything downstream - the structured report, the
renderer, the validator, the artifact - reads a
:class:`CanonicalAssessmentResult` and nothing else. That is what makes the
guarantee checkable: the reporting layer cannot recompute a fact it has no
engine for, and cannot show a fact it was never given.

**Strict by construction.**

* Unknown fields are refused, not ignored. A document carrying a field this
  contract does not name is refused whole: the field cannot be rendered
  (nothing knows where it goes), cannot be validated (nothing knows what it
  means), and silently dropping it would make an added dose or an added
  recommendation invisible rather than impossible.
* Hashes are verified **before** construction, not after. An object that
  exists is an object whose facts were checked.
* No field holds clinical prose, raw source text, a supplied raw value, or any
  model-generated content. The types have nowhere to put them.
* Nothing mutable is exposed. Every mapping and sequence is frozen, so a
  renderer cannot edit a governed fact on its way to the page and a validator
  that checked an object cannot be handed a different one afterwards.

The result is built from the WP-14 read model, or from a previously written
artifact document. Both paths land in the same constructor and run the same
checks, because a report regenerated from an artifact must be the same report.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.domain.hashing import sha256_digest
from pgx.domain.immutable import freeze_json
from pgx.reporting.errors import ReportInputError

__all__ = [
    "CANONICAL_RESULT_SCHEMA_VERSION",
    "MAX_REFERENCE_LENGTH",
    "AxisFacts",
    "CanonicalAssessmentResult",
    "FindingFacts",
    "MedicationFacts",
    "canonical_result_from_document",
    "canonical_result_from_read_model",
]

CANONICAL_RESULT_SCHEMA_VERSION = "pgx-canonical-assessment-result/1"

#: The longest a governed reference may be. Identifiers, hashes, canonical
#: keys and rationale references are all far shorter; prose is not. This is a
#: blunt instrument and is documented as one - it stops a paragraph arriving
#: in a field meant for an identifier, and it does not and cannot detect a
#: short sentence pretending to be a reference.
MAX_REFERENCE_LENGTH = 512

_AXIS_KEYS: Tuple[str, ...] = (
    "drug_canonical_key", "gene_canonical_key", "coverage_status",
    "coverage_reason_codes", "observed_phenotype", "observation_state",
    "declaration_id", "rule_references", "evidence_references",
    "conflict_references")

_FINDING_KEYS: Tuple[str, ...] = (
    "drug_canonical_key", "gene_canonical_key", "phenotype",
    "attention_level", "rule_id", "rule_family_id", "rule_version",
    "rule_content_hash", "rationale_reference", "curation_revision_id",
    "curation_revision_hash", "effect_code", "explanation_code",
    "evidence_references")

_MEDICATION_KEYS: Tuple[str, ...] = (
    "drug_canonical_key", "requested_value", "attention_level",
    "coverage_status", "coverage_reason_codes", "axis_count",
    "conflicted_axis_count", "axes", "findings")


def _refuse(message: str, *, location: str,
            code: str = "REPORT_INPUT_INVALID",
            detail: Optional[Mapping[str, Any]] = None) -> None:
    raise ReportInputError(message, code=code, location=location,
                           detail=detail)


def _require_only(document: Mapping[str, Any], allowed: Sequence[str],
                  location: str) -> None:
    """Refuse a document carrying any field this contract does not name."""
    if not isinstance(document, Mapping):
        _refuse("%s must be an object" % location, location=location)
    unknown = tuple(sorted(set(document) - set(allowed)))
    if unknown:
        _refuse("%s carries field(s) the report contract does not name: %s. "
                "An unnamed field cannot be rendered, cannot be validated and "
                "must not be silently dropped."
                % (location, ", ".join(unknown)),
                location=location, code="REPORT_UNKNOWN_FIELD",
                detail={"unknown_fields": list(unknown)})


def _require_reference(value: Any, name: str, location: str) -> str:
    """A governed reference: present, one line, and not a paragraph."""
    if not isinstance(value, str) or not value.strip():
        _refuse("%s is a non-empty governed reference" % name,
                location=location)
    if "\n" in value or "\r" in value:
        _refuse("%s carries a line break, so it is prose rather than a "
                "reference. Reporting shows references; it does not carry "
                "narrative from anywhere." % name, location=location)
    if len(value) > MAX_REFERENCE_LENGTH:
        _refuse("%s is %d characters; a governed reference is at most %d"
                % (name, len(value), MAX_REFERENCE_LENGTH), location=location)
    return value


def _optional_reference(value: Any, name: str, location: str) -> Optional[str]:
    if value is None:
        return None
    return _require_reference(value, name, location)


def _string_tuple(values: Any, name: str, location: str) -> Tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values,
                                                          (list, tuple)):
        _refuse("%s is a list of strings" % name, location=location)
    return tuple(_require_reference(item, "%s[]" % name, location)
                 for item in values)


@dataclass(frozen=True, slots=True)
class AxisFacts:
    """One drug-gene axis exactly as coverage reported it.

    Carries what could be evaluated and why not. It carries no attention
    level: attention belongs to a finding, and an axis that pretended to have
    one would let a report show a level for an axis nothing was calculated
    for.
    """

    drug_canonical_key: str
    gene_canonical_key: str
    coverage_status: str
    coverage_reason_codes: Tuple[str, ...] = ()
    observed_phenotype: Optional[str] = None
    observation_state: str = ""
    declaration_id: Optional[str] = None
    rule_references: Tuple[Mapping[str, Any], ...] = ()
    evidence_references: Tuple[str, ...] = ()
    conflict_references: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        where = "$.axes[%s/%s]" % (self.drug_canonical_key,
                                   self.gene_canonical_key)
        _require_reference(self.drug_canonical_key, "drug_canonical_key",
                           where)
        _require_reference(self.gene_canonical_key, "gene_canonical_key",
                           where)
        _require_reference(self.coverage_status, "coverage_status", where)
        object.__setattr__(self, "coverage_reason_codes",
                           _string_tuple(self.coverage_reason_codes,
                                         "coverage_reason_codes", where))
        object.__setattr__(self, "evidence_references",
                           _string_tuple(self.evidence_references,
                                         "evidence_references", where))
        object.__setattr__(self, "conflict_references",
                           _string_tuple(self.conflict_references,
                                         "conflict_references", where))
        object.__setattr__(self, "rule_references",
                           tuple(freeze_json(dict(item))
                                 for item in self.rule_references))
        if self.observed_phenotype is not None:
            _require_reference(self.observed_phenotype, "observed_phenotype",
                               where)

    @property
    def axis_key(self) -> Tuple[str, str]:
        return (self.drug_canonical_key, self.gene_canonical_key)

    @property
    def is_covered(self) -> bool:
        return self.coverage_status == "FULL"

    def to_json(self) -> Dict[str, Any]:
        return {
            "drug_canonical_key": self.drug_canonical_key,
            "gene_canonical_key": self.gene_canonical_key,
            "coverage_status": self.coverage_status,
            "coverage_reason_codes": list(self.coverage_reason_codes),
            "observed_phenotype": self.observed_phenotype,
            "observation_state": self.observation_state,
            "declaration_id": self.declaration_id,
            "rule_references": [dict(item) for item in self.rule_references],
            "evidence_references": list(self.evidence_references),
            "conflict_references": list(self.conflict_references),
        }


@dataclass(frozen=True, slots=True)
class FindingFacts:
    """One calculated finding and its whole traceability chain.

    ``effect_code`` and ``explanation_code`` are optional and are usually
    ``None``, because the governed rule outcome this repository builds carries
    an attention level and a rationale reference and no scientific codes.
    Reporting renders that absence as absence. It does not fill it, and it
    does not hide it.
    """

    drug_canonical_key: str
    gene_canonical_key: str
    phenotype: str
    attention_level: str
    rule_id: str
    rule_family_id: str
    rule_version: int
    rule_content_hash: str
    rationale_reference: str
    curation_revision_id: str
    curation_revision_hash: str
    evidence_references: Tuple[str, ...]
    effect_code: Optional[str] = None
    explanation_code: Optional[str] = None

    def __post_init__(self) -> None:
        where = "$.findings[%s/%s]" % (self.drug_canonical_key,
                                       self.gene_canonical_key)
        for name in ("drug_canonical_key", "gene_canonical_key", "phenotype",
                     "attention_level", "rule_id", "rule_family_id",
                     "rule_content_hash", "rationale_reference",
                     "curation_revision_id", "curation_revision_hash"):
            _require_reference(getattr(self, name), name, where)
        if self.attention_level == "NOT_ASSESSED":
            _refuse("a finding is a calculated result and is never "
                    "NOT_ASSESSED; absence belongs to coverage",
                    location=where)
        if not isinstance(self.rule_version, int) or \
                isinstance(self.rule_version, bool) or self.rule_version < 1:
            _refuse("rule_version is an integer of at least 1", location=where)
        object.__setattr__(self, "evidence_references",
                           _string_tuple(self.evidence_references,
                                         "evidence_references", where))
        if not self.evidence_references:
            _refuse("a finding names at least one evidence record "
                    "(SAFETY-INV-006)", location=where,
                    code="REPORT_EVIDENCE_MISSING")
        object.__setattr__(self, "effect_code",
                           _optional_reference(self.effect_code,
                                               "effect_code", where))
        object.__setattr__(self, "explanation_code",
                           _optional_reference(self.explanation_code,
                                               "explanation_code", where))

    @property
    def has_governed_codes(self) -> bool:
        """Whether this ruleset carried scientific codes for this finding."""
        return bool(self.effect_code or self.explanation_code)

    def to_json(self) -> Dict[str, Any]:
        return {
            "drug_canonical_key": self.drug_canonical_key,
            "gene_canonical_key": self.gene_canonical_key,
            "phenotype": self.phenotype,
            "attention_level": self.attention_level,
            "rule_id": self.rule_id,
            "rule_family_id": self.rule_family_id,
            "rule_version": self.rule_version,
            "rule_content_hash": self.rule_content_hash,
            "rationale_reference": self.rationale_reference,
            "curation_revision_id": self.curation_revision_id,
            "curation_revision_hash": self.curation_revision_hash,
            "effect_code": self.effect_code,
            "explanation_code": self.explanation_code,
            "evidence_references": list(self.evidence_references),
        }


@dataclass(frozen=True, slots=True)
class MedicationFacts:
    """Everything the assessment recorded about one requested medication."""

    drug_canonical_key: str
    requested_value: str
    attention_level: str
    coverage_status: str
    coverage_reason_codes: Tuple[str, ...] = ()
    axis_count: int = 0
    conflicted_axis_count: int = 0
    axes: Tuple[AxisFacts, ...] = ()
    findings: Tuple[FindingFacts, ...] = ()

    def __post_init__(self) -> None:
        where = "$.medications[%s]" % self.drug_canonical_key
        for name in ("drug_canonical_key", "requested_value",
                     "attention_level", "coverage_status"):
            _require_reference(getattr(self, name), name, where)
        object.__setattr__(self, "coverage_reason_codes",
                           _string_tuple(self.coverage_reason_codes,
                                         "coverage_reason_codes", where))
        if self.attention_level == "NO_ACTIVE_ATTENTION" and \
                self.coverage_status != "FULL":
            _refuse("NO_ACTIVE_ATTENTION accompanies only FULL coverage "
                    "(SAFETY-INV-001); %s does not"
                    % self.coverage_status, location=where,
                    code="REPORT_STATUS_RENDERING_UNSAFE")
        if self.attention_level == "NOT_ASSESSED" and self.findings:
            _refuse("a NOT_ASSESSED medication carries no findings",
                    location=where)
        if self.coverage_status != "FULL" and not self.coverage_reason_codes:
            _refuse("coverage %s names at least one machine-readable reason; "
                    "unexplained absence is how absence becomes reassurance"
                    % self.coverage_status, location=where,
                    code="REPORT_STATUS_RENDERING_UNSAFE")
        object.__setattr__(
            self, "axes",
            tuple(sorted(self.axes, key=lambda item: item.axis_key)))
        object.__setattr__(
            self, "findings",
            tuple(sorted(self.findings,
                         key=lambda item: (item.drug_canonical_key,
                                           item.gene_canonical_key))))

    @property
    def uncovered_axes(self) -> Tuple[AxisFacts, ...]:
        return tuple(axis for axis in self.axes if not axis.is_covered)

    @property
    def conflicted_axes(self) -> Tuple[AxisFacts, ...]:
        return tuple(axis for axis in self.axes
                     if axis.coverage_status == "SOURCE_CONFLICT")

    @property
    def conflict_references(self) -> Tuple[str, ...]:
        found: List[str] = []
        for axis in self.axes:
            for reference in axis.conflict_references:
                if reference not in found:
                    found.append(reference)
        return tuple(sorted(found))

    def to_json(self) -> Dict[str, Any]:
        return {
            "drug_canonical_key": self.drug_canonical_key,
            "requested_value": self.requested_value,
            "attention_level": self.attention_level,
            "coverage_status": self.coverage_status,
            "coverage_reason_codes": list(self.coverage_reason_codes),
            "axis_count": self.axis_count,
            "conflicted_axis_count": self.conflicted_axis_count,
            "axes": [axis.to_json() for axis in self.axes],
            "findings": [finding.to_json() for finding in self.findings],
        }


@dataclass(frozen=True, slots=True)
class CanonicalAssessmentResult:
    """The whole immutable fact set one report is built from."""

    assessment_id: str
    mode: str
    input_kind: str
    input_hash: str
    output_hash: str
    coverage_result_hash: str
    overall_attention: str
    overall_coverage: str
    overall_coverage_reason_codes: Tuple[str, ...]
    medications: Tuple[MedicationFacts, ...]
    release_provenance: Mapping[str, Any]
    pointer_audit: Mapping[str, Any]
    profile_observations: Tuple[Mapping[str, Any], ...] = ()
    warnings: Tuple[str, ...] = ()
    case_id: Optional[str] = None
    actor: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    engine_contract_version: str = ""
    computation_schema_version: str = ""
    result_schema_version: str = CANONICAL_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("assessment_id", "mode", "input_kind", "input_hash",
                     "output_hash", "coverage_result_hash",
                     "overall_attention", "overall_coverage"):
            _require_reference(getattr(self, name), name, "$." + name)
        object.__setattr__(self, "overall_coverage_reason_codes",
                           _string_tuple(self.overall_coverage_reason_codes,
                                         "overall_coverage_reason_codes", "$"))
        if not self.medications:
            _refuse("a report covers at least one requested medication",
                    location="$.medications")
        if self.overall_attention == "NO_ACTIVE_ATTENTION" and \
                self.overall_coverage != "FULL":
            _refuse("NO_ACTIVE_ATTENTION at the top requires FULL overall "
                    "coverage (SAFETY-INV-001)",
                    location="$.overall_attention",
                    code="REPORT_STATUS_RENDERING_UNSAFE")
        if not self.release_provenance:
            _refuse("a report names every version the assessment executed "
                    "against (SAFETY-INV-007)",
                    location="$.release_provenance",
                    code="REPORT_RELEASE_PROVENANCE_MISSING")
        object.__setattr__(self, "release_provenance",
                           freeze_json(dict(self.release_provenance)))
        object.__setattr__(self, "pointer_audit",
                           freeze_json(dict(self.pointer_audit)))
        object.__setattr__(
            self, "profile_observations",
            tuple(freeze_json(dict(item))
                  for item in sorted(self.profile_observations,
                                     key=lambda item: item.get("gene_id",
                                                               ""))))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(
            self, "medications",
            tuple(sorted(self.medications,
                         key=lambda item: (item.drug_canonical_key,
                                           item.requested_value))))
        if self.case_id is not None:
            _require_reference(self.case_id, "case_id", "$.case_id")

    # -- reading ---------------------------------------------------------

    @property
    def findings(self) -> Tuple[FindingFacts, ...]:
        return tuple(finding for medication in self.medications
                     for finding in medication.findings)

    @property
    def axes(self) -> Tuple[AxisFacts, ...]:
        return tuple(axis for medication in self.medications
                     for axis in medication.axes)

    @property
    def conflict_references(self) -> Tuple[str, ...]:
        found: List[str] = []
        for medication in self.medications:
            for reference in medication.conflict_references:
                if reference not in found:
                    found.append(reference)
        return tuple(sorted(found))

    @property
    def evidence_references(self) -> Tuple[str, ...]:
        found: List[str] = []
        for finding in self.findings:
            for reference in finding.evidence_references:
                if reference not in found:
                    found.append(reference)
        return tuple(sorted(found))

    def medication_for(self, drug_canonical_key: str
                       ) -> Optional[MedicationFacts]:
        for medication in self.medications:
            if medication.drug_canonical_key == drug_canonical_key:
                return medication
        return None

    def semantic_content(self) -> Dict[str, Any]:
        """The governed facts, canonically ordered.

        Excludes the case id, the actor and both timestamps: they label the
        run, not the answer, and two reports of the same facts must be
        comparable across them.
        """
        return {
            "result_schema_version": self.result_schema_version,
            "assessment_engine_contract_version": self.engine_contract_version,
            "computation_schema_version": self.computation_schema_version,
            "mode": self.mode,
            "input_kind": self.input_kind,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "coverage_result_hash": self.coverage_result_hash,
            "overall_attention": self.overall_attention,
            "overall_coverage": self.overall_coverage,
            "overall_coverage_reason_codes":
                list(self.overall_coverage_reason_codes),
            "medication_count": len(self.medications),
            "medications": [item.to_json() for item in self.medications],
            "finding_count": len(self.findings),
            "profile_observations": [dict(item)
                                     for item in self.profile_observations],
            "release_provenance": dict(self.release_provenance),
            "warnings": list(self.warnings),
        }

    def content_hash(self) -> str:
        return sha256_digest(self.semantic_content())

    def to_json(self) -> Dict[str, Any]:
        payload = self.semantic_content()
        payload["assessment_id"] = self.assessment_id
        payload["case_id"] = self.case_id
        payload["actor"] = self.actor
        payload["created_at"] = self.created_at
        payload["completed_at"] = self.completed_at
        payload["pointer_audit"] = dict(self.pointer_audit)
        payload["content_hash"] = self.content_hash()
        return payload


def _axis_from(document: Mapping[str, Any]) -> AxisFacts:
    _require_only(document, _AXIS_KEYS, "$.axes[]")
    return AxisFacts(
        drug_canonical_key=document["drug_canonical_key"],
        gene_canonical_key=document["gene_canonical_key"],
        coverage_status=document["coverage_status"],
        coverage_reason_codes=tuple(document.get("coverage_reason_codes")
                                    or ()),
        observed_phenotype=document.get("observed_phenotype"),
        observation_state=document.get("observation_state") or "",
        declaration_id=document.get("declaration_id"),
        rule_references=tuple(document.get("rule_references") or ()),
        evidence_references=tuple(document.get("evidence_references") or ()),
        conflict_references=tuple(document.get("conflict_references") or ()))


def _finding_from(document: Mapping[str, Any]) -> FindingFacts:
    _require_only(document, _FINDING_KEYS, "$.findings[]")
    return FindingFacts(
        drug_canonical_key=document["drug_canonical_key"],
        gene_canonical_key=document["gene_canonical_key"],
        phenotype=document["phenotype"],
        attention_level=document["attention_level"],
        rule_id=document["rule_id"],
        rule_family_id=document["rule_family_id"],
        rule_version=document["rule_version"],
        rule_content_hash=document["rule_content_hash"],
        rationale_reference=document["rationale_reference"],
        curation_revision_id=document["curation_revision_id"],
        curation_revision_hash=document["curation_revision_hash"],
        effect_code=document.get("effect_code"),
        explanation_code=document.get("explanation_code"),
        evidence_references=tuple(document.get("evidence_references") or ()))


def _medication_from(document: Mapping[str, Any]) -> MedicationFacts:
    _require_only(document, _MEDICATION_KEYS, "$.medications[]")
    return MedicationFacts(
        drug_canonical_key=document["drug_canonical_key"],
        requested_value=document["requested_value"],
        attention_level=document["attention_level"],
        coverage_status=document["coverage_status"],
        coverage_reason_codes=tuple(document.get("coverage_reason_codes")
                                    or ()),
        axis_count=document.get("axis_count", 0),
        conflicted_axis_count=document.get("conflicted_axis_count", 0),
        axes=tuple(_axis_from(item) for item in document.get("axes") or ()),
        findings=tuple(_finding_from(item)
                       for item in document.get("findings") or ()))


def canonical_result_from_read_model(view: Any) -> CanonicalAssessmentResult:
    """Build the report's fact set from a WP-14 lossless read model.

    The read model has already re-hashed everything it returned; this checks
    the hashes it reports rather than trusting that it ran. Two layers
    checking the same thing is the point: this one is the layer that would
    otherwise render an unverified fact.
    """
    verification = dict(getattr(view, "verification", {}) or {})
    if not verification.get("row_and_snapshot_agree"):
        _refuse("the stored row and the stored snapshot disagree, so there is "
                "no single set of facts to report",
                location="$.verification",
                code="REPORT_ROW_SNAPSHOT_DISAGREEMENT")
    if verification.get("recomputed_output_hash") != view.output_hash:
        _refuse("the stored computation recomputes to %r and the assessment "
                "records %r" % (verification.get("recomputed_output_hash"),
                                view.output_hash),
                location="$.output_hash", code="REPORT_HASH_MISMATCH")
    computation = dict(view.computation)
    coverage_hash = computation.get("coverage_result_hash")
    coverage = dict(view.coverage_result)
    if not coverage or coverage.get("content_hash") != coverage_hash:
        _refuse("the coverage result is absent or does not match the hash "
                "recorded beside it, so what could be evaluated cannot be "
                "stated", location="$.coverage_result",
                code="REPORT_COVERAGE_UNVERIFIABLE")

    axes_by_drug: Dict[str, List[AxisFacts]] = {}
    for medication in coverage.get("medications") or ():
        for axis in medication.get("axes") or ():
            facts = AxisFacts(
                drug_canonical_key=axis["drug_id"],
                gene_canonical_key=axis["gene_id"],
                coverage_status=axis["status"],
                coverage_reason_codes=tuple(axis.get("reason_codes") or ()),
                observed_phenotype=axis.get("observed_phenotype"),
                observation_state=axis.get("observation_state") or "",
                declaration_id=axis.get("declaration_id"),
                rule_references=tuple(axis.get("rule_references") or ()),
                evidence_references=tuple(axis.get("evidence_references")
                                          or ()),
                conflict_references=tuple(axis.get("conflict_references")
                                          or ()))
            axes_by_drug.setdefault(facts.drug_canonical_key, []).append(facts)

    medications = []
    for item in computation.get("medications") or ():
        key = item["drug_id"]
        findings = tuple(
            FindingFacts(
                drug_canonical_key=finding["drug_id"],
                gene_canonical_key=finding["gene_id"],
                phenotype=finding["phenotype"],
                attention_level=finding["attention_level"],
                rule_id=finding["rule_id"],
                rule_family_id=finding["rule_family_id"],
                rule_version=finding["rule_version"],
                rule_content_hash=finding["rule_content_hash"],
                rationale_reference=finding["rationale_reference"],
                curation_revision_id=finding["curation_revision_id"],
                curation_revision_hash=finding["curation_revision_hash"],
                effect_code=finding.get("effect_code"),
                explanation_code=finding.get("explanation_code"),
                evidence_references=tuple(finding.get("evidence_references")
                                          or ()))
            for finding in item.get("findings") or ())
        medications.append(MedicationFacts(
            drug_canonical_key=key,
            requested_value=item["requested_value"],
            attention_level=item["attention_level"],
            coverage_status=item["coverage_status"],
            coverage_reason_codes=tuple(item.get("coverage_reason_codes")
                                        or ()),
            axis_count=item.get("axis_count", 0),
            conflicted_axis_count=item.get("conflicted_axis_count", 0),
            axes=tuple(axes_by_drug.get(key, ())),
            findings=findings))

    observations = tuple(
        dict(item) for item in
        (view.input_snapshot.get("profile", {}) or {}).get("observations")
        or ())
    return CanonicalAssessmentResult(
        assessment_id=view.assessment_id,
        mode=view.mode,
        input_kind=view.input_kind,
        input_hash=view.input_hash,
        output_hash=view.output_hash,
        coverage_result_hash=coverage_hash,
        overall_attention=computation["overall_attention"],
        overall_coverage=computation["overall_coverage"],
        overall_coverage_reason_codes=tuple(
            computation.get("overall_coverage_reason_codes") or ()),
        medications=tuple(medications),
        release_provenance=dict(view.release_provenance),
        pointer_audit=dict(view.pointer_audit),
        profile_observations=observations,
        warnings=tuple(computation.get("warnings") or ()),
        case_id=view.case_id,
        actor=view.actor,
        created_at=view.created_at,
        completed_at=view.completed_at,
        engine_contract_version=computation.get(
            "assessment_engine_contract_version", ""),
        computation_schema_version=computation.get(
            "computation_schema_version", ""))


#: Every field the canonical document form carries. Anything else is refused.
_RESULT_KEYS: Tuple[str, ...] = (
    "result_schema_version", "assessment_engine_contract_version",
    "computation_schema_version", "assessment_id", "case_id", "actor",
    "created_at", "completed_at", "mode", "input_kind", "input_hash",
    "output_hash", "coverage_result_hash", "overall_attention",
    "overall_coverage", "overall_coverage_reason_codes", "medication_count",
    "medications", "finding_count", "profile_observations",
    "release_provenance", "pointer_audit", "warnings", "content_hash")


def canonical_result_from_document(document: Mapping[str, Any]
                                   ) -> CanonicalAssessmentResult:
    """Rebuild the fact set from its own canonical document form.

    Used when a report is regenerated or verified from a written artifact. The
    recorded ``content_hash`` is checked against a recomputation rather than
    trusted, so a document edited on disk is refused rather than rendered.
    """
    _require_only(document, _RESULT_KEYS, "$")
    version = document.get("result_schema_version")
    if version != CANONICAL_RESULT_SCHEMA_VERSION:
        _refuse("canonical result schema version %r is not %r"
                % (version, CANONICAL_RESULT_SCHEMA_VERSION),
                location="$.result_schema_version",
                code="REPORT_SCHEMA_VERSION_UNKNOWN")
    result = CanonicalAssessmentResult(
        assessment_id=document["assessment_id"],
        mode=document["mode"],
        input_kind=document["input_kind"],
        input_hash=document["input_hash"],
        output_hash=document["output_hash"],
        coverage_result_hash=document["coverage_result_hash"],
        overall_attention=document["overall_attention"],
        overall_coverage=document["overall_coverage"],
        overall_coverage_reason_codes=tuple(
            document.get("overall_coverage_reason_codes") or ()),
        medications=tuple(_medication_from(item)
                          for item in document.get("medications") or ()),
        release_provenance=dict(document.get("release_provenance") or {}),
        pointer_audit=dict(document.get("pointer_audit") or {}),
        profile_observations=tuple(
            dict(item) for item in document.get("profile_observations")
            or ()),
        warnings=tuple(document.get("warnings") or ()),
        case_id=document.get("case_id"),
        actor=document.get("actor"),
        created_at=document.get("created_at"),
        completed_at=document.get("completed_at"),
        engine_contract_version=document.get(
            "assessment_engine_contract_version", ""),
        computation_schema_version=document.get("computation_schema_version",
                                                ""))
    recorded = document.get("content_hash")
    if recorded is not None and recorded != result.content_hash():
        _refuse("the canonical result recomputes to %s and the document "
                "records %s" % (result.content_hash(), recorded),
                location="$.content_hash", code="REPORT_HASH_MISMATCH")
    return result
