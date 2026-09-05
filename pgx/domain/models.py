# -*- coding: utf-8 -*-
"""Immutable domain models (WP-02, extended by WP-03).

Standard library only. These are the *type and invariant contract* for the
scientific pipeline, not an engine: nothing here matches a phenotype, scores a
risk, or renders a report. Those belong to WP-12 through WP-15.

The pipeline direction is one-way and is enforced by construction:

    EvidenceRecord -> CuratedInterpretation -> ComputableRule -> AssessmentFinding

Each stage requires the previous stage's identity. There is deliberately no
method anywhere that turns an :class:`EvidenceRecord` into an
:class:`AssessmentFinding`: source text may never become a calculated result
without passing through curation and rule approval.

WP-03 adds the *version registry*: :class:`SoftwareVersion`,
:class:`RulesetVersion` membership, a typed :class:`ReleaseBundle`, the
:class:`ActiveRelease` pointer and the append-only :class:`AuditEvent`. These
are still values with invariants - the activation and rollback *operations*
live in :mod:`pgx.application.release_service`, because a state transition that
must be transactional and audited is a service, never a method on a frozen
dataclass.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, Mapping, Optional, Tuple

from pgx.domain.claims import (DEFAULT_CLAIM_BOUNDARY, ClaimBoundary,
                               OperationMode, PermittedInputKind)
from pgx.domain.enums import (
    AttentionLevel,
    AuditAction,
    CoverageReasonCode,
    CoverageStatus,
    CurationStatus,
    DatasetStatus,
    Phenotype,
    ReleaseStatus,
    RuleStatus,
    RulesetStatus,
    SourceRole,
)
from pgx.domain.errors import (
    DomainInvariantError,
    LifecycleError,
    ModeNotPermittedError,
    TraceabilityError,
)
from pgx.domain.hashing import ensure_utc, is_canonical_digest
from pgx.domain.immutable import EMPTY_MAPPING, freeze_json, freeze_metadata
from pgx.domain.identifiers import (
    AssessmentId,
    AuditEventId,
    ComputableRuleId,
    CuratedInterpretationId,
    DatasetPublicId,
    DatasetVersionId,
    DrugId,
    EvidenceRecordId,
    GeneId,
    ReleaseBundleId,
    ReleasePublicId,
    RulesetPublicId,
    RulesetVersionId,
    SoftwareVersionId,
    SourceRegistryEntryId,
    require_id,
)

__all__ = [
    "ActiveRelease",
    "Assessment",
    "AssessmentFinding",
    "AuditEvent",
    "ComputableRule",
    "CoverageAssessment",
    "CuratedInterpretation",
    "DatasetVersion",
    "Drug",
    "EvidenceRecord",
    "Gene",
    "ReleaseBundle",
    "RulesetVersion",
    "SoftwareVersion",
    "SourceRegistryEntry",
]

#: Shared, genuinely immutable empty mapping. A module-level ``{}`` would be
#: mutable shared state: one caller mutating it would change every default.
_EMPTY_METADATA: Mapping[str, Any] = EMPTY_MAPPING


def _require_text(value: object, field_name: str) -> str:
    """Return a non-blank string or raise."""
    if not isinstance(value, str) or not value.strip():
        raise DomainInvariantError("%s must be a non-empty string" % field_name)
    return value


def _require_digest(value: object, field_name: str) -> str:
    """Return a canonical ``sha256:<hex>`` digest or raise."""
    if not is_canonical_digest(value):
        raise DomainInvariantError(
            "%s must be a canonical 'sha256:<64 hex>' digest, got %r" % (field_name, value))
    return str(value)


def _frozen_metadata(value: Optional[Mapping[str, Any]], field_name: str) -> Mapping[str, Any]:
    """Return a deeply immutable snapshot of a JSON metadata mapping.

    Recursive: nested mappings become FrozenMapping and nested sequences become
    tuples, so ``model.metadata["a"]["b"] = x`` fails. The caller's original
    object is copied, so mutating it afterwards cannot reach inside the model.
    """
    return freeze_metadata(value, field_name)


def _require_permitted_mode(
    value: object, boundary: ClaimBoundary = DEFAULT_CLAIM_BOUNDARY
) -> OperationMode:
    """Return ``value`` if it is an OperationMode the boundary enables.

    WP-00 owns the mode vocabulary and decides which modes are live. A plain
    string is refused outright, and a real but disabled mode (``PILOT`` in P0)
    raises rather than being quietly accepted.
    """
    if not isinstance(value, OperationMode):
        raise DomainInvariantError(
            "mode must be a pgx.domain.claims.OperationMode, got %r. A free "
            "string cannot be checked against the claim boundary."
            % (type(value).__name__,))
    if not boundary.is_mode_enabled(value):
        raise ModeNotPermittedError(
            "operation mode %s is not enabled in %s, so an assessment may not be "
            "created in it. %s"
            % (value.value, boundary.phase.value,
               "PILOT requires a formally expanded intended purpose and a P2 gate."
               if value is OperationMode.PILOT else ""))
    return value


def _require_tuple(value: object, field_name: str) -> Tuple[Any, ...]:
    """Reject mutable collections so a model cannot be changed after creation."""
    if isinstance(value, (list, set)):
        raise DomainInvariantError(
            "%s must be an immutable tuple, not %r" % (field_name, type(value).__name__))
    if not isinstance(value, tuple):
        raise DomainInvariantError(
            "%s must be a tuple, got %r" % (field_name, type(value).__name__))
    return value


# ---------------------------------------------------------------------------
# Registry and versioning
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceRegistryEntry:
    """A registered source of scientific or technical records.

    Licence and citation policy are recorded, never inferred. WP-05 owns the
    scientific source strategy; WP-02 only fixes the shape.
    """

    id: SourceRegistryEntryId
    source_key: str
    display_name: str
    role: SourceRole
    version_policy: str
    license_policy: str
    citation_policy: str
    release_eligible: bool
    active: bool
    created_at: _dt.datetime
    legacy_id: Optional[str] = None

    def __post_init__(self) -> None:
        require_id(self.id, SourceRegistryEntryId, "SourceRegistryEntry.id")
        _require_text(self.source_key, "source_key")
        _require_text(self.display_name, "display_name")
        if not isinstance(self.role, SourceRole):
            raise DomainInvariantError("role must be a SourceRole")
        _require_text(self.version_policy, "version_policy")
        _require_text(self.license_policy, "license_policy")
        _require_text(self.citation_policy, "citation_policy")
        if not isinstance(self.release_eligible, bool):
            raise DomainInvariantError("release_eligible must be a bool")
        if not isinstance(self.active, bool):
            raise DomainInvariantError("active must be a bool")
        object.__setattr__(self, "created_at", ensure_utc(self.created_at, "created_at"))
        if self.role is SourceRole.INTERNAL_SYSTEM and self.release_eligible:
            raise DomainInvariantError(
                "an INTERNAL_SYSTEM source is technical bookkeeping and can never "
                "be release-eligible scientific evidence")


@dataclass(frozen=True, slots=True)
class DatasetVersion:
    """An immutable dataset build.

    Approval metadata is required once the dataset is ``PUBLISHED``: an
    unapproved dataset must not present itself as publishable.
    """

    id: DatasetVersionId
    public_id: DatasetPublicId
    status: DatasetStatus
    manifest_hash: str
    created_at: _dt.datetime
    dq_report_path: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[_dt.datetime] = None
    legacy_id: Optional[str] = None

    def __post_init__(self) -> None:
        require_id(self.id, DatasetVersionId, "DatasetVersion.id")
        if not isinstance(self.public_id, DatasetPublicId):
            raise DomainInvariantError("public_id must be a DatasetPublicId")
        if not isinstance(self.status, DatasetStatus):
            raise DomainInvariantError("status must be a DatasetStatus")
        _require_digest(self.manifest_hash, "manifest_hash")
        object.__setattr__(self, "created_at", ensure_utc(self.created_at, "created_at"))
        if self.approved_at is not None:
            object.__setattr__(
                self, "approved_at", ensure_utc(self.approved_at, "approved_at"))
        if self.status is DatasetStatus.PUBLISHED:
            if not (self.approved_by and self.approved_by.strip()) or self.approved_at is None:
                raise LifecycleError(
                    "a PUBLISHED dataset version requires approved_by and approved_at")


@dataclass(frozen=True, slots=True)
class Gene:
    """A canonical gene with its normalised symbol and aliases."""

    id: GeneId
    normalized_symbol: str
    preferred_name: str
    created_at: _dt.datetime
    aliases: Tuple[str, ...] = ()
    external_ids: Mapping[str, Any] = field(default=_EMPTY_METADATA)
    legacy_id: Optional[str] = None

    def __post_init__(self) -> None:
        require_id(self.id, GeneId, "Gene.id")
        _require_text(self.normalized_symbol, "normalized_symbol")
        if self.normalized_symbol != self.normalized_symbol.strip().upper():
            raise DomainInvariantError(
                "normalized_symbol must already be normalised (trimmed, upper-case)")
        _require_text(self.preferred_name, "preferred_name")
        _require_tuple(self.aliases, "aliases")
        object.__setattr__(self, "external_ids",
                           _frozen_metadata(self.external_ids, "external_ids"))
        object.__setattr__(self, "created_at", ensure_utc(self.created_at, "created_at"))


@dataclass(frozen=True, slots=True)
class Drug:
    """A canonical drug with its normalised name and aliases."""

    id: DrugId
    normalized_name: str
    preferred_name: str
    created_at: _dt.datetime
    aliases: Tuple[str, ...] = ()
    external_ids: Mapping[str, Any] = field(default=_EMPTY_METADATA)
    legacy_id: Optional[str] = None

    def __post_init__(self) -> None:
        require_id(self.id, DrugId, "Drug.id")
        _require_text(self.normalized_name, "normalized_name")
        if self.normalized_name != self.normalized_name.strip().lower():
            raise DomainInvariantError(
                "normalized_name must already be normalised (trimmed, lower-case)")
        _require_text(self.preferred_name, "preferred_name")
        _require_tuple(self.aliases, "aliases")
        object.__setattr__(self, "external_ids",
                           _frozen_metadata(self.external_ids, "external_ids"))
        object.__setattr__(self, "created_at", ensure_utc(self.created_at, "created_at"))


# ---------------------------------------------------------------------------
# Evidence -> Interpretation -> Rule
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """A single record as the source stated it.

    This is the *bottom* of the pipeline and carries source truth only. It has
    deliberately **no** attention, risk, severity, dose, or treatment field, and
    **no** method that produces a finding or an assessment. Source summaries may
    contain dosing language; preserving that text is allowed, promoting it to a
    result is not (``LEGACY-BUG-012``).
    """

    id: EvidenceRecordId
    source_registry_id: SourceRegistryEntryId
    dataset_version_id: DatasetVersionId
    source_record_id: str
    source_record_version: str
    raw_hash: str
    created_at: _dt.datetime
    gene_id: Optional[GeneId] = None
    drug_id: Optional[DrugId] = None
    source_text: Optional[str] = None
    evidence_metadata: Mapping[str, Any] = field(default=_EMPTY_METADATA)
    publication_metadata: Mapping[str, Any] = field(default=_EMPTY_METADATA)
    legacy_id: Optional[str] = None

    def __post_init__(self) -> None:
        require_id(self.id, EvidenceRecordId, "EvidenceRecord.id")
        require_id(self.source_registry_id, SourceRegistryEntryId,
                   "EvidenceRecord.source_registry_id")
        require_id(self.dataset_version_id, DatasetVersionId,
                   "EvidenceRecord.dataset_version_id")
        _require_text(self.source_record_id, "source_record_id")
        _require_text(self.source_record_version, "source_record_version")
        _require_digest(self.raw_hash, "raw_hash")
        if self.gene_id is not None:
            require_id(self.gene_id, GeneId, "EvidenceRecord.gene_id")
        if self.drug_id is not None:
            require_id(self.drug_id, DrugId, "EvidenceRecord.drug_id")
        object.__setattr__(self, "evidence_metadata",
                           _frozen_metadata(self.evidence_metadata, "evidence_metadata"))
        object.__setattr__(self, "publication_metadata",
                           _frozen_metadata(self.publication_metadata, "publication_metadata"))
        object.__setattr__(self, "created_at", ensure_utc(self.created_at, "created_at"))


@dataclass(frozen=True, slots=True)
class CuratedInterpretation:
    """A human curation decision over one or more evidence records.

    Requires at least one :class:`EvidenceRecordId`: an interpretation with no
    evidence has nothing to interpret. Reaching ``CURATED`` additionally
    requires a rationale, a named reviewer, and a review instant, so approval
    can never be implied.
    """

    id: CuratedInterpretationId
    evidence_record_ids: Tuple[EvidenceRecordId, ...]
    status: CurationStatus
    normalized_effect: str
    significance: str
    created_by: str
    created_at: _dt.datetime
    normalized_phenotype: Optional[Phenotype] = None
    rationale: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[_dt.datetime] = None
    legacy_id: Optional[str] = None

    def __post_init__(self) -> None:
        require_id(self.id, CuratedInterpretationId, "CuratedInterpretation.id")
        _require_tuple(self.evidence_record_ids, "evidence_record_ids")
        if not self.evidence_record_ids:
            raise TraceabilityError(
                "a CuratedInterpretation requires at least one evidence record; "
                "an interpretation without evidence is untraceable")
        for index, evidence_id in enumerate(self.evidence_record_ids):
            require_id(evidence_id, EvidenceRecordId,
                       "CuratedInterpretation.evidence_record_ids[%d]" % index)
        if len(set(self.evidence_record_ids)) != len(self.evidence_record_ids):
            raise DomainInvariantError("evidence_record_ids must not repeat")
        if not isinstance(self.status, CurationStatus):
            raise DomainInvariantError("status must be a CurationStatus")
        _require_text(self.normalized_effect, "normalized_effect")
        _require_text(self.significance, "significance")
        _require_text(self.created_by, "created_by")
        if self.normalized_phenotype is not None and not isinstance(
                self.normalized_phenotype, Phenotype):
            raise DomainInvariantError("normalized_phenotype must be a Phenotype")
        object.__setattr__(self, "created_at", ensure_utc(self.created_at, "created_at"))
        if self.reviewed_at is not None:
            object.__setattr__(
                self, "reviewed_at", ensure_utc(self.reviewed_at, "reviewed_at"))
        if self.status is CurationStatus.CURATED:
            missing = []
            if not (self.rationale and self.rationale.strip()):
                missing.append("rationale")
            if not (self.reviewed_by and self.reviewed_by.strip()):
                missing.append("reviewed_by")
            if self.reviewed_at is None:
                missing.append("reviewed_at")
            if missing:
                raise LifecycleError(
                    "a CURATED interpretation requires %s; curation must record "
                    "who decided and why" % ", ".join(missing))

    @property
    def is_usable_for_rule_construction(self) -> bool:
        """Only a CURATED interpretation may back a rule."""
        return self.status is CurationStatus.CURATED


@dataclass(frozen=True, slots=True)
class ComputableRule:
    """A machine-evaluable rule derived from exactly one curated interpretation.

    ``condition`` is a typed, canonical mapping, never executable code: a rule
    must be reviewable by a scientist and reproducible by the engine, and an
    ``eval``-style rule is neither.

    Reaching ``VALIDATED`` requires approval metadata and at least one evidence
    reference (``SAFETY-INV-003``, ``SAFETY-INV-006``). WP-02 stores rules; the
    engine that executes them is WP-14.
    """

    id: ComputableRuleId
    interpretation_id: CuratedInterpretationId
    evidence_record_ids: Tuple[EvidenceRecordId, ...]
    condition: Mapping[str, Any]
    attention_level: AttentionLevel
    status: RuleStatus
    rule_version: int
    created_by: str
    created_at: _dt.datetime
    approved_by: Optional[str] = None
    approved_at: Optional[_dt.datetime] = None
    legacy_id: Optional[str] = None

    def __post_init__(self) -> None:
        require_id(self.id, ComputableRuleId, "ComputableRule.id")
        require_id(self.interpretation_id, CuratedInterpretationId,
                   "ComputableRule.interpretation_id")
        _require_tuple(self.evidence_record_ids, "evidence_record_ids")
        for index, evidence_id in enumerate(self.evidence_record_ids):
            require_id(evidence_id, EvidenceRecordId,
                       "ComputableRule.evidence_record_ids[%d]" % index)
        if len(set(self.evidence_record_ids)) != len(self.evidence_record_ids):
            raise DomainInvariantError("evidence_record_ids must not repeat")
        if not isinstance(self.condition, Mapping):
            raise DomainInvariantError(
                "condition must be a typed mapping, not %r" % type(self.condition).__name__)
        if isinstance(self.condition, str) or callable(self.condition):
            raise DomainInvariantError(
                "condition must not be code; rules are declarative data")
        # Deeply frozen: a rule condition is the input to a reproducible
        # calculation, so no part of it may change after construction.
        object.__setattr__(self, "condition", freeze_json(self.condition, "$.condition"))
        if not isinstance(self.attention_level, AttentionLevel):
            raise DomainInvariantError("attention_level must be an AttentionLevel")
        if not isinstance(self.status, RuleStatus):
            raise DomainInvariantError("status must be a RuleStatus")
        if not isinstance(self.rule_version, int) or isinstance(self.rule_version, bool) \
                or self.rule_version < 1:
            raise DomainInvariantError("rule_version must be an int >= 1")
        _require_text(self.created_by, "created_by")
        object.__setattr__(self, "created_at", ensure_utc(self.created_at, "created_at"))
        if self.approved_at is not None:
            object.__setattr__(
                self, "approved_at", ensure_utc(self.approved_at, "approved_at"))
        if self.status is RuleStatus.VALIDATED:
            missing = []
            if not (self.approved_by and self.approved_by.strip()):
                missing.append("approved_by")
            if self.approved_at is None:
                missing.append("approved_at")
            if missing:
                raise LifecycleError(
                    "a VALIDATED rule requires %s; approval may never be implied"
                    % ", ".join(missing))
            if not self.evidence_record_ids:
                raise TraceabilityError(
                    "a VALIDATED rule requires at least one evidence reference "
                    "(SAFETY-INV-006)")

    @property
    def is_executable(self) -> bool:
        """Only VALIDATED rules may ever be executed (``SAFETY-INV-003``).

        DRAFT, CURATED and DEPRECATED rules are inert. This property states the
        contract; the engine enforcing it is WP-14.
        """
        return self.status is RuleStatus.VALIDATED


@dataclass(frozen=True, slots=True)
class RulesetVersion:
    """An immutable, versioned collection of rules with pinned membership.

    Membership is the point of this record. A ruleset that names its rules only
    indirectly - "whatever is VALIDATED today" - cannot pin a release, because
    the set it denotes changes underneath the release that cited it. So
    ``rule_ids`` is an explicit, ordered, duplicate-free tuple, fixed at
    construction and unchangeable afterwards (the dataclass is frozen and the
    tuple is immutable).

    Ordering is deterministic: members are sorted by their UUID string, so two
    processes that select the same rules produce the same manifest and the same
    hash regardless of the order the rules came back from a query.

    ``FROZEN`` is the terminal, release-eligible state. WP-03 does not invent a
    freeze *operation* here - a lifecycle transition that must be audited is a
    service - but it does enforce what a frozen record has to look like: a
    non-empty membership, an approver, and an approval instant.
    """

    id: RulesetVersionId
    public_id: RulesetPublicId
    status: RulesetStatus
    manifest_hash: str
    created_at: _dt.datetime
    rule_ids: Tuple[ComputableRuleId, ...] = ()
    approved_by: Optional[str] = None
    approved_at: Optional[_dt.datetime] = None
    legacy_id: Optional[str] = None

    def __post_init__(self) -> None:
        require_id(self.id, RulesetVersionId, "RulesetVersion.id")
        if not isinstance(self.public_id, RulesetPublicId):
            raise DomainInvariantError("public_id must be a RulesetPublicId")
        if not isinstance(self.status, RulesetStatus):
            raise DomainInvariantError("status must be a RulesetStatus")
        _require_digest(self.manifest_hash, "manifest_hash")
        object.__setattr__(self, "created_at", ensure_utc(self.created_at, "created_at"))
        if self.approved_at is not None:
            object.__setattr__(
                self, "approved_at", ensure_utc(self.approved_at, "approved_at"))

        _require_tuple(self.rule_ids, "rule_ids")
        seen = set()
        for index, rule_id in enumerate(self.rule_ids):
            require_id(rule_id, ComputableRuleId, "RulesetVersion.rule_ids[%d]" % index)
            if rule_id in seen:
                raise DomainInvariantError(
                    "rule %s appears twice in ruleset membership; a rule counted "
                    "twice would be weighted twice by anything that reads the set"
                    % rule_id)
            seen.add(rule_id)
        # Deterministic order, so the manifest hash does not depend on query order.
        object.__setattr__(
            self, "rule_ids",
            tuple(sorted(self.rule_ids, key=lambda item: str(item.value))))

        if self.status in (RulesetStatus.VALIDATED, RulesetStatus.FROZEN):
            if not (self.approved_by and self.approved_by.strip()) or self.approved_at is None:
                raise LifecycleError(
                    "a %s ruleset requires approved_by and approved_at" % self.status.value)
        if self.status is RulesetStatus.FROZEN and not self.rule_ids:
            raise LifecycleError(
                "a FROZEN ruleset must pin at least one rule. An empty frozen "
                "ruleset would let a release claim rule coverage it does not have.")

    @property
    def member_count(self) -> int:
        """How many rules this ruleset pins."""
        return len(self.rule_ids)

    def contains(self, rule_id: ComputableRuleId) -> bool:
        """True when ``rule_id`` is pinned by this ruleset."""
        return rule_id in self.rule_ids


@dataclass(frozen=True, slots=True)
class SoftwareVersion:
    """One registered build of this software (WP-03).

    A release pins the code it ran under by identity, not by a declared version
    string: two builds can both call themselves ``0.3.0`` and differ in source
    tree. ``source_commit`` and ``source_tree_hash`` are what actually
    distinguish them, and ``manifest_hash`` is the canonical digest of the
    identity payload as it appears in a release manifest.

    Registration records a build; it does not assert that the build was
    reviewed, tested or approved.
    """

    id: SoftwareVersionId
    version: str
    source_commit: str
    source_tree_hash: str
    manifest_hash: str
    built_at: _dt.datetime
    created_at: _dt.datetime
    build_metadata: Mapping[str, Any] = field(default=_EMPTY_METADATA)

    def __post_init__(self) -> None:
        require_id(self.id, SoftwareVersionId, "SoftwareVersion.id")
        _require_text(self.version, "version")
        _require_text(self.source_commit, "source_commit")
        _require_digest(self.source_tree_hash, "source_tree_hash")
        _require_digest(self.manifest_hash, "manifest_hash")
        object.__setattr__(self, "built_at", ensure_utc(self.built_at, "built_at"))
        object.__setattr__(self, "created_at", ensure_utc(self.created_at, "created_at"))
        object.__setattr__(self, "build_metadata",
                           _frozen_metadata(self.build_metadata, "build_metadata"))


@dataclass(frozen=True, slots=True)
class ReleaseBundle:
    """The pinned (software, dataset, ruleset) triple an assessment ran against.

    All three are pinned **by identity**. WP-02 held the software as a plain
    string, which meant a release could not distinguish two builds that declared
    the same version, and nothing joined the release to a registered build
    record. ``software_version_id`` replaces it.

    ``manifest`` is the deeply immutable payload whose canonical digest is
    ``manifest_hash``; :mod:`pgx.domain.release_manifest` builds and verifies
    it. Storing both means a stored release can be re-checked later without
    trusting the row: recompute the digest of the payload and compare.

    Status transitions (``DRAFT -> ACTIVE -> ROLLED_BACK | RETIRED``) are
    service operations that write audit events - see
    :mod:`pgx.application.release_service`. A bundle never activates itself.
    """

    id: ReleaseBundleId
    public_id: ReleasePublicId
    software_version_id: SoftwareVersionId
    dataset_version_id: DatasetVersionId
    ruleset_version_id: RulesetVersionId
    manifest: Mapping[str, Any]
    manifest_hash: str
    status: ReleaseStatus
    created_at: _dt.datetime
    activated_at: Optional[_dt.datetime] = None
    activated_by: Optional[str] = None
    legacy_id: Optional[str] = None
    notes: Optional[str] = None

    def __post_init__(self) -> None:
        require_id(self.id, ReleaseBundleId, "ReleaseBundle.id")
        if not isinstance(self.public_id, ReleasePublicId):
            raise DomainInvariantError("public_id must be a ReleasePublicId")
        require_id(self.software_version_id, SoftwareVersionId,
                   "ReleaseBundle.software_version_id")
        require_id(self.dataset_version_id, DatasetVersionId,
                   "ReleaseBundle.dataset_version_id")
        require_id(self.ruleset_version_id, RulesetVersionId,
                   "ReleaseBundle.ruleset_version_id")
        if not isinstance(self.status, ReleaseStatus):
            raise DomainInvariantError("status must be a ReleaseStatus")
        _require_digest(self.manifest_hash, "manifest_hash")
        if not isinstance(self.manifest, Mapping):
            raise DomainInvariantError(
                "manifest must be a mapping, got %r" % type(self.manifest).__name__)
        # Deeply frozen: the manifest is the input to a reproducible digest, so
        # nothing may edit it after the digest was taken.
        object.__setattr__(self, "manifest", freeze_json(self.manifest, "$.manifest"))
        object.__setattr__(self, "created_at", ensure_utc(self.created_at, "created_at"))
        if self.activated_at is not None:
            object.__setattr__(
                self, "activated_at", ensure_utc(self.activated_at, "activated_at"))
        if self.status is ReleaseStatus.DRAFT and (
                self.activated_at is not None or self.activated_by is not None):
            raise LifecycleError(
                "a DRAFT release carries no activation metadata; it has never "
                "been activated")
        if self.status in (ReleaseStatus.ACTIVE, ReleaseStatus.ROLLED_BACK):
            if self.activated_at is None or not (
                    self.activated_by and self.activated_by.strip()):
                raise LifecycleError(
                    "a %s release must record who activated it and when; a release "
                    "that reached ACTIVE without that metadata cannot be audited"
                    % self.status.value)

    @property
    def was_ever_activated(self) -> bool:
        """True when this bundle carries activation metadata.

        Rollback uses the audit history rather than this flag - history is the
        record of what happened - but a bundle that was never activated cannot
        have been, and this states that locally.
        """
        return self.activated_at is not None


@dataclass(frozen=True, slots=True)
class ActiveRelease:
    """The single pointer naming the release currently in force (WP-03).

    Exactly one of these exists. It is a *pointer*, not a copy: it holds the
    release identity and the bookkeeping needed to change it safely, and
    nothing about the release's content.

    ``generation`` is a monotonically increasing counter, incremented on every
    successful pointer change. It is the optimistic-concurrency token: two
    activations that both read generation *n* cannot both commit, because the
    second finds the pointer no longer at *n*. The database row is also locked
    with ``SELECT ... FOR UPDATE`` during activation; the counter is what makes
    a lost update *detectable* rather than merely unlikely.

    ``release_id`` is ``None`` before the first activation. That is a real
    state, not an error: a system with no active release must say so rather
    than pointing at something arbitrary.
    """

    #: Fixed primary key of the one row. A singleton enforced in the database.
    SINGLETON_ID: ClassVar[int] = 1

    release_id: Optional[ReleaseBundleId]
    generation: int
    updated_at: _dt.datetime
    updated_by: str
    singleton_id: int = 1

    def __post_init__(self) -> None:
        if self.release_id is not None:
            require_id(self.release_id, ReleaseBundleId, "ActiveRelease.release_id")
        if not isinstance(self.generation, int) or isinstance(self.generation, bool):
            raise DomainInvariantError(
                "generation must be an int, got %r" % type(self.generation).__name__)
        if self.generation < 0:
            raise DomainInvariantError(
                "generation must not be negative, got %d" % self.generation)
        if self.singleton_id != ActiveRelease.SINGLETON_ID:
            raise DomainInvariantError(
                "the active release pointer is a singleton; singleton_id must be "
                "%d, got %r" % (ActiveRelease.SINGLETON_ID, self.singleton_id))
        if self.release_id is None and self.generation != 0:
            raise DomainInvariantError(
                "generation %d with no active release: a pointer that has moved "
                "must name the release it moved to" % self.generation)
        _require_text(self.updated_by, "updated_by")
        object.__setattr__(self, "updated_at", ensure_utc(self.updated_at, "updated_at"))

    @property
    def is_set(self) -> bool:
        """True when a release is currently active."""
        return self.release_id is not None

    def moved_to(
        self,
        release_id: ReleaseBundleId,
        updated_at: _dt.datetime,
        updated_by: str,
    ) -> "ActiveRelease":
        """Return the next pointer state. Returns a new value; mutates nothing."""
        require_id(release_id, ReleaseBundleId, "moved_to.release_id")
        return ActiveRelease(
            release_id=release_id,
            generation=self.generation + 1,
            updated_at=updated_at,
            updated_by=updated_by,
        )


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """One append-only record of something that happened (WP-03).

    Append-only is the whole contract. The repository port offers no update and
    no delete, and the migration installs a trigger that refuses both at the
    database level, because an audit trail that can be edited answers no
    question worth asking.

    ``previous_release_id`` and ``new_release_id`` are what make an activation
    or rollback reconstructible: "which release was in force before this event,
    and which after". Either may be ``None`` - the first activation has no
    predecessor - so the pair is not required, but an event that claims to
    change the pointer and names neither side is refused.
    """

    id: AuditEventId
    action: AuditAction
    actor: str
    object_type: str
    object_id: str
    occurred_at: _dt.datetime
    reason: Optional[str] = None
    previous_release_id: Optional[ReleaseBundleId] = None
    new_release_id: Optional[ReleaseBundleId] = None
    metadata: Mapping[str, Any] = field(default=_EMPTY_METADATA)

    #: Actions that must name at least one side of a pointer change.
    _POINTER_ACTIONS: ClassVar[Tuple[AuditAction, ...]] = (
        AuditAction.RELEASE_ACTIVATED, AuditAction.RELEASE_ROLLED_BACK)

    def __post_init__(self) -> None:
        require_id(self.id, AuditEventId, "AuditEvent.id")
        if not isinstance(self.action, AuditAction):
            raise DomainInvariantError(
                "action must be an AuditAction, got %r. A free string cannot be "
                "queried and drifts silently." % type(self.action).__name__)
        _require_text(self.actor, "actor")
        _require_text(self.object_type, "object_type")
        _require_text(self.object_id, "object_id")
        object.__setattr__(self, "occurred_at", ensure_utc(self.occurred_at, "occurred_at"))
        if self.previous_release_id is not None:
            require_id(self.previous_release_id, ReleaseBundleId,
                       "AuditEvent.previous_release_id")
        if self.new_release_id is not None:
            require_id(self.new_release_id, ReleaseBundleId, "AuditEvent.new_release_id")
        if self.action in AuditEvent._POINTER_ACTIONS and self.new_release_id is None:
            raise DomainInvariantError(
                "a %s event must name the release the pointer moved to"
                % self.action.value)
        if self.reason is not None:
            _require_text(self.reason, "reason")
        object.__setattr__(self, "metadata", _frozen_metadata(self.metadata, "metadata"))


# ---------------------------------------------------------------------------
# Assessment side
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CoverageAssessment:
    """What could be evaluated, and why not, for one medication.

    Coverage is a first-class output, never derived from attention and never
    displayed as a substitute for it (``architecture.md`` section 9.2).

    The contract that makes false reassurance impossible: only ``FULL`` coverage
    may accompany ``NO_ACTIVE_ATTENTION``. Every other absence path terminates
    in ``NOT_ASSESSED`` (``SAFETY-INV-001``, ``LEGACY-BUG-002``).

    **On the identity.** ``drug_id`` is the canonical identity the pinned
    dataset already holds for this drug, obtained by lookup. Nothing here
    mints one: two runs of the same question against the same release must
    record the same drug, and a freshly generated UUID per run would make an
    assessment unjoinable to the entity it is about.

    It is optional for exactly one case. A medication the pinned canonical
    dataset does not contain *has* no canonical identity, and inventing one
    would fabricate the subject of the entry. That case is explicit rather
    than implicit: the identity may be absent only when the reason codes say
    ``DRUG_NOT_IN_CANONICAL_DATASET``, and ``drug_canonical_key`` still
    records exactly what was requested, so the entry names its medication
    either way.
    """

    drug_id: Optional[DrugId]
    status: CoverageStatus
    reason_codes: Tuple[CoverageReasonCode, ...] = ()
    drug_canonical_key: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.drug_canonical_key, str):
            raise DomainInvariantError(
                "drug_canonical_key is the canonical key this entry is about, "
                "as a string")
        if not isinstance(self.status, CoverageStatus):
            raise DomainInvariantError("status must be a CoverageStatus")
        _require_tuple(self.reason_codes, "reason_codes")
        for index, code in enumerate(self.reason_codes):
            if not isinstance(code, CoverageReasonCode):
                raise DomainInvariantError(
                    "reason_codes[%d] must be a CoverageReasonCode" % index)
        if self.drug_id is None:
            if CoverageReasonCode.DRUG_NOT_IN_CANONICAL_DATASET not in \
                    self.reason_codes:
                raise DomainInvariantError(
                    "a coverage entry names the canonical drug it is about. "
                    "The only entry that may not is one for a medication the "
                    "pinned canonical dataset does not contain, and that "
                    "entry says so with DRUG_NOT_IN_CANONICAL_DATASET rather "
                    "than leaving the identity quietly absent")
            _require_text(self.drug_canonical_key, "drug_canonical_key")
        else:
            require_id(self.drug_id, DrugId, "CoverageAssessment.drug_id")
        if self.status is not CoverageStatus.FULL and not self.reason_codes:
            raise DomainInvariantError(
                "coverage %s requires at least one machine-readable reason code; "
                "unexplained partial coverage is not reportable" % self.status.value)
        if self.status is CoverageStatus.FULL and self.reason_codes:
            raise DomainInvariantError(
                "FULL coverage must carry no reason codes")

    def permits_no_active_attention(self) -> bool:
        """Only FULL coverage may report NO_ACTIVE_ATTENTION."""
        return self.status is CoverageStatus.FULL


@dataclass(frozen=True, slots=True)
class AssessmentFinding:
    """One calculated attention finding, with its full traceability chain.

    Requires both the rule that produced it and at least one evidence record
    behind that rule (``SAFETY-INV-006``). It cannot be built from source text:
    there is no constructor, classmethod, or helper anywhere that accepts an
    :class:`EvidenceRecord` and returns a finding.

    It carries no dose, no treatment selection, and no candidate-safety field;
    those claims are prohibited outright (``SAFETY-INV-005``, intended-purpose
    section 7).

    **On the scientific codes (WP-14 reconciliation).** WP-02 modelled
    ``effect_code`` and ``explanation_code`` as required, anticipating that a
    governed rule would carry them. The governed rule outcome WP-11 actually
    built carries exactly two things - an attention level and a
    ``rationale_reference`` pointing at the approved curated interpretation
    whose reasoning justifies it - and nothing in this repository produces a
    scientific effect or explanation code under review.

    So both are now optional and default to ``None``, and
    ``rationale_reference`` is required. A finding computed by WP-14 states
    that no governed effect code exists rather than carrying a plausible one:
    an invented ``DECREASED_ACTIVATION`` would be a scientific claim wearing
    the appearance of a reviewed one, and a downstream reader cannot tell the
    two apart. If a future protocol puts these codes into hash-covered,
    versioned rule content, they can be populated from there; until then their
    absence is the honest value, and WP-15 must render it as absence.

    A supplied code must still be a non-empty string, so a caller cannot pass
    ``""`` and have it read as "present but blank".
    """

    gene_id: GeneId
    drug_id: DrugId
    phenotype: Phenotype
    attention_level: AttentionLevel
    rule_id: ComputableRuleId
    rule_version: int
    evidence_record_ids: Tuple[EvidenceRecordId, ...]
    rationale_reference: str = ""
    effect_code: Optional[str] = None
    explanation_code: Optional[str] = None

    def __post_init__(self) -> None:
        require_id(self.gene_id, GeneId, "AssessmentFinding.gene_id")
        require_id(self.drug_id, DrugId, "AssessmentFinding.drug_id")
        if not isinstance(self.phenotype, Phenotype):
            raise DomainInvariantError("phenotype must be a Phenotype")
        if not isinstance(self.attention_level, AttentionLevel):
            raise DomainInvariantError("attention_level must be an AttentionLevel")
        if self.attention_level is AttentionLevel.NOT_ASSESSED:
            raise DomainInvariantError(
                "a finding is a calculated result and cannot be NOT_ASSESSED; "
                "absence is expressed through CoverageAssessment instead")
        _require_text(self.rationale_reference, "rationale_reference")
        for name in ("effect_code", "explanation_code"):
            value = getattr(self, name)
            if value is None:
                continue
            if not isinstance(value, str) or not value.strip():
                raise DomainInvariantError(
                    "%s is optional, but a supplied one must be a non-empty "
                    "string. An empty code reads as present-but-blank, which "
                    "is the one thing absence must not be confused with."
                    % name)
        require_id(self.rule_id, ComputableRuleId, "AssessmentFinding.rule_id")
        if not isinstance(self.rule_version, int) or isinstance(self.rule_version, bool) \
                or self.rule_version < 1:
            raise DomainInvariantError("rule_version must be an int >= 1")
        _require_tuple(self.evidence_record_ids, "evidence_record_ids")
        if not self.evidence_record_ids:
            raise TraceabilityError(
                "every calculated finding must cite at least one evidence record "
                "(SAFETY-INV-006)")
        for index, evidence_id in enumerate(self.evidence_record_ids):
            require_id(evidence_id, EvidenceRecordId,
                       "AssessmentFinding.evidence_record_ids[%d]" % index)


@dataclass(frozen=True, slots=True)
class PinnedReleaseProvenance:
    """Every version an assessment was calculated against, pinned by identity
    *and* content hash (``SAFETY-INV-007``).

    One value object rather than eighteen fields on :class:`Assessment`,
    because these are answers to a single question - *what exactly did this
    run execute against* - and they are complete or they are useless. An
    assessment carrying half of them cannot be reproduced, and a half-pinned
    result that persisted would look as authoritative as a whole one.

    ``active_pointer_generation`` is the generation of the WP-03 active-release
    pointer at the moment the release was pinned. It is recorded so that a
    stored assessment can be read against the pointer history: an assessment
    pinned at generation 4 was calculated against whatever was active then,
    regardless of what is active now. The service reads the pointer exactly
    once, and this is the value it read.
    """

    release_public_id: str
    release_manifest_hash: str
    active_pointer_generation: int
    software_version_id: SoftwareVersionId
    software_version: str
    software_source_tree_hash: str
    dataset_version_id: DatasetVersionId
    dataset_public_id: str
    canonical_build_content_hash: str
    ruleset_version_id: RulesetVersionId
    ruleset_public_id: str
    ruleset_content_hash: str
    evidence_build_key: str
    evidence_build_content_hash: str
    coverage_manifest_hash: str
    protocol_version: str
    protocol_content_hash: str
    source_policy_version: str
    source_policy_content_hash: str

    def __post_init__(self) -> None:
        require_id(self.software_version_id, SoftwareVersionId,
                   "PinnedReleaseProvenance.software_version_id")
        require_id(self.dataset_version_id, DatasetVersionId,
                   "PinnedReleaseProvenance.dataset_version_id")
        require_id(self.ruleset_version_id, RulesetVersionId,
                   "PinnedReleaseProvenance.ruleset_version_id")
        for name in ("release_public_id", "software_version",
                     "dataset_public_id", "ruleset_public_id",
                     "evidence_build_key", "protocol_version",
                     "source_policy_version"):
            _require_text(getattr(self, name), name)
        for name in ("release_manifest_hash", "software_source_tree_hash",
                     "canonical_build_content_hash", "ruleset_content_hash",
                     "evidence_build_content_hash", "coverage_manifest_hash",
                     "protocol_content_hash", "source_policy_content_hash"):
            _require_digest(getattr(self, name), name)
        if not isinstance(self.active_pointer_generation, int) or \
                isinstance(self.active_pointer_generation, bool) or \
                self.active_pointer_generation < 0:
            raise DomainInvariantError(
                "active_pointer_generation is the WP-03 pointer generation "
                "observed at pin time and counts from 0")

    def to_json(self) -> Dict[str, Any]:
        return {
            "release_public_id": self.release_public_id,
            "release_manifest_hash": self.release_manifest_hash,
            "active_pointer_generation": self.active_pointer_generation,
            "software_version_id": self.software_version_id.to_json(),
            "software_version": self.software_version,
            "software_source_tree_hash": self.software_source_tree_hash,
            "dataset_version_id": self.dataset_version_id.to_json(),
            "dataset_public_id": self.dataset_public_id,
            "canonical_build_content_hash": self.canonical_build_content_hash,
            "ruleset_version_id": self.ruleset_version_id.to_json(),
            "ruleset_public_id": self.ruleset_public_id,
            "ruleset_content_hash": self.ruleset_content_hash,
            "evidence_build_key": self.evidence_build_key,
            "evidence_build_content_hash": self.evidence_build_content_hash,
            "coverage_manifest_hash": self.coverage_manifest_hash,
            "protocol_version": self.protocol_version,
            "protocol_content_hash": self.protocol_content_hash,
            "source_policy_version": self.source_policy_version,
            "source_policy_content_hash": self.source_policy_content_hash,
        }


@dataclass(frozen=True, slots=True)
class Assessment:
    """One deterministic assessment run.

    A release bundle is mandatory: an assessment that cannot name the software,
    dataset, and ruleset it ran against is not reproducible and must not exist
    (``SAFETY-INV-007``).

    ``mode`` is the WP-00 :class:`~pgx.domain.claims.OperationMode`, not a free
    string. It is validated against the active claim boundary, so an assessment
    can never be created in a mode the product has not enabled - in P0 that
    means ``PILOT`` is refused (``architecture.md`` section 2.3).

    This is the calculated fact record. It is not a report and not an API
    response model; rendering belongs to WP-15 and serialisation to WP-16.
    """

    id: AssessmentId
    release_bundle_id: ReleaseBundleId
    mode: OperationMode
    input_hash: str
    created_at: _dt.datetime
    findings: Tuple[AssessmentFinding, ...] = ()
    coverage: Tuple[CoverageAssessment, ...] = ()
    output_hash: Optional[str] = None
    case_id: Optional[str] = None
    #: WP-14. Every version this run executed against. Optional on the type so
    #: WP-02's provisional shape still constructs, and **required to persist**:
    #: :meth:`require_complete_release_metadata` is what the repository calls,
    #: and the database enforces the same thing again with NOT NULL columns.
    release_provenance: Optional["PinnedReleaseProvenance"] = None
    input_kind: Optional[PermittedInputKind] = None
    overall_coverage: Optional[CoverageStatus] = None
    calculated_overall_attention: Optional[AttentionLevel] = None
    actor: Optional[str] = None
    completed_at: Optional[_dt.datetime] = None

    def __post_init__(self) -> None:
        require_id(self.id, AssessmentId, "Assessment.id")
        require_id(self.release_bundle_id, ReleaseBundleId, "Assessment.release_bundle_id")
        _require_permitted_mode(self.mode)
        _require_digest(self.input_hash, "input_hash")
        if self.output_hash is not None:
            _require_digest(self.output_hash, "output_hash")
        object.__setattr__(self, "created_at", ensure_utc(self.created_at, "created_at"))
        _require_tuple(self.findings, "findings")
        for index, finding in enumerate(self.findings):
            if not isinstance(finding, AssessmentFinding):
                raise DomainInvariantError(
                    "findings[%d] must be an AssessmentFinding; an assessment cannot "
                    "be assembled from raw evidence" % index)
        _require_tuple(self.coverage, "coverage")
        for index, coverage in enumerate(self.coverage):
            if not isinstance(coverage, CoverageAssessment):
                raise DomainInvariantError(
                    "coverage[%d] must be a CoverageAssessment" % index)
        if self.release_provenance is not None and \
                not isinstance(self.release_provenance, PinnedReleaseProvenance):
            raise DomainInvariantError(
                "release_provenance must be a PinnedReleaseProvenance")
        if self.input_kind is not None and \
                not isinstance(self.input_kind, PermittedInputKind):
            raise DomainInvariantError(
                "input_kind must be a PermittedInputKind, not a free string")
        if self.overall_coverage is not None and \
                not isinstance(self.overall_coverage, CoverageStatus):
            raise DomainInvariantError("overall_coverage must be a CoverageStatus")
        if self.calculated_overall_attention is not None and \
                not isinstance(self.calculated_overall_attention, AttentionLevel):
            raise DomainInvariantError(
                "calculated_overall_attention must be an AttentionLevel")
        if self.completed_at is not None:
            object.__setattr__(self, "completed_at",
                               ensure_utc(self.completed_at, "completed_at"))
        # SAFETY-INV-001, in the shape the stored record takes: a reassuring
        # overall level may accompany only FULL overall coverage.
        if self.calculated_overall_attention is AttentionLevel.NO_ACTIVE_ATTENTION \
                and self.overall_coverage is not CoverageStatus.FULL:
            raise DomainInvariantError(
                "NO_ACTIVE_ATTENTION requires FULL overall coverage; every "
                "other absence path terminates in NOT_ASSESSED "
                "(SAFETY-INV-001)")

    def require_complete_release_metadata(self) -> "PinnedReleaseProvenance":
        """Return the pinned provenance, or refuse.

        SAFETY-INV-007: an assessment that cannot name the software, dataset
        and ruleset it ran against is not reproducible, cannot be audited and
        cannot be retracted, so it must not be stored. Called by the
        repository rather than by ``__post_init__`` so that a *calculation*
        can still be represented before it is pinned - but nothing reaches
        persistence without it.
        """
        if self.release_provenance is None:
            raise DomainInvariantError(
                "an assessment may be persisted only with complete release "
                "metadata: release, software, dataset, ruleset, evidence "
                "build, coverage manifest, protocol and source policy, each "
                "by identity and hash (SAFETY-INV-007)")
        if self.output_hash is None:
            raise DomainInvariantError(
                "an assessment may be persisted only with an output hash; "
                "an unhashed result cannot be shown to be reproducible "
                "(SAFETY-INV-007)")
        return self.release_provenance

    @property
    def overall_attention(self) -> AttentionLevel:
        """Highest calculated attention, or ``NOT_ASSESSED`` when none exists.

        Deliberately not a maximum over a numeric scale: ``NOT_ASSESSED`` is
        never ranked against ``LOW``. With no calculated finding the answer is
        "we did not look", not "low".
        """
        ranking = (AttentionLevel.HIGH, AttentionLevel.MEDIUM, AttentionLevel.LOW,
                   AttentionLevel.NO_ACTIVE_ATTENTION)
        present = {finding.attention_level for finding in self.findings}
        for level in ranking:
            if level in present:
                return level
        return AttentionLevel.NOT_ASSESSED
