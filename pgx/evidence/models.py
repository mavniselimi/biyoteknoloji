# -*- coding: utf-8 -*-
"""Evidence records, provenance, attribution and controlled vocabularies (WP-08).

Standard library plus :mod:`pgx.domain` and :mod:`pgx.evidence.errors`.

**What an evidence record is here.** One record as the source stated it, plus
everything needed to find that statement again in the raw bytes. It carries the
source's own wording, the source's own identity and version, who provided the
bytes, who the record says asserted it, which canonical entities it names, and
which publications it cites.

**What it is not.** There is no attention level, no risk, no severity, no
phenotype-to-effect conclusion, no evidence-strength judgement, no
recommendation and no executable condition. :data:`PROHIBITED_METADATA_FIELDS`
names them, and :class:`EvidenceRecordDraft` refuses construction when one
appears in normalized metadata - refuses, rather than reporting an issue,
because a risk level sitting in an evidence record is not a data-quality
problem to be counted but the store no longer meaning what it says.

**The layer rule that makes that check safe.** The source's *own* fields are
not project fields. ClinPGx variant annotations carry ``score``,
``significance`` and ``polarity``; ClinPGx guideline annotations carry boolean
``recommendation`` and ``dosingInformation`` flags. Those are facts about what
the source published, and deleting them would be censoring the source. They
live in :attr:`EvidenceRecordDraft.raw_source_payload`, under one reserved
namespace, and the prohibited-field scan never runs there. It runs over
normalized metadata, which this project authors and is therefore answerable
for. A naive recursive scan over opaque source payloads would delete real
source data and prove nothing.

**Five layers, kept apart** (WP-08 implements the first three, and the third
only outside this module):

1. raw source payload - bytes as retrieved;
2. extracted source facts - this module;
3. project interpretation candidate - :mod:`pgx.evidence.draft_curation`, an
   unreviewed migration artifact that never enters the evidence store;
4. reviewed curation - WP-09;
5. executable rule - WP-11.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from pgx.domain.hashing import ensure_utc, is_canonical_digest, sha256_digest
from pgx.domain.immutable import freeze_json
from pgx.evidence.errors import ProhibitedFieldError, SourceRecordError

__all__ = [
    "EVIDENCE_RECORD_VERSION",
    "PROHIBITED_METADATA_FIELDS",
    "RAW_PAYLOAD_NAMESPACE",
    "RECORD_TYPE_MAP_VERSION",
    "EvidenceEntityLink",
    "EvidenceEntityRole",
    "EvidenceNaturalKey",
    "EvidenceRecordDraft",
    "EvidenceRecordType",
    "ImportIssue",
    "ImportIssueCode",
    "IssueSeverity",
    "OriginStatus",
    "PublicationReference",
    "RawRecordLocator",
    "RecordTypeMapping",
    "RecordTypeMappingStatus",
    "SourceAttribution",
    "SourceRecordVersion",
    "SourceTextFragment",
    "TextLanguage",
    "VersionStatus",
    "canonical_text_hash",
    "normalize_source_record_id",
]

#: Bumped when the evidence record shape changes. Recorded on every record, so
#: a record written under an older shape is never silently compared with a
#: newer one.
EVIDENCE_RECORD_VERSION = "pgx-evidence-record/1"

#: Bumped when the object-class to record-type mapping changes.
RECORD_TYPE_MAP_VERSION = "pgx-evidence-record-types/1"

#: The single reserved key under which an untouched source payload is stored.
#: Nothing else may use it, and normalized metadata may not contain it, so a
#: source field can never present itself as something this project asserted.
RAW_PAYLOAD_NAMESPACE = "raw_source_payload"

#: Project-authored fields that must never appear in normalized evidence
#: metadata. Each is a conclusion this project would be making, not something a
#: source said. Matched case-insensitively, with ``-`` and spaces folded to
#: ``_``, at every depth of the normalized metadata - and at no depth of the
#: raw source payload.
PROHIBITED_METADATA_FIELDS: Tuple[str, ...] = (
    "attention_level",
    "candidate_preference",
    "candidate_score",
    "demo_risk_level",
    "drug_behavior_hint",
    "effect_direction",
    "evidence_strength",
    "matcher_condition",
    "normalized_effect",
    "normalized_phenotype",
    "normalized_phenotype_group",
    "plain_language",
    "plain_language_mvp",
    "risk",
    "risk_level",
    "risk_meaning",
    "treatment_selection",
    "usable_for_mvp",
)


class EvidenceRecordType(str, Enum):
    """What kind of source record this is.

    Decided from the source's own ``objCls``, never from the container it
    arrived in. The ClinPGx ``variantAnnotation`` container alone returns three
    different object classes, so a container-derived type would be wrong for
    two thirds of them.
    """

    GUIDELINE_ANNOTATION = "GUIDELINE_ANNOTATION"
    VARIANT_ANNOTATION = "VARIANT_ANNOTATION"
    DRUG_LABEL_ANNOTATION = "DRUG_LABEL_ANNOTATION"
    CLINICAL_ANNOTATION = "CLINICAL_ANNOTATION"
    PUBLICATION_REFERENCE = "PUBLICATION_REFERENCE"
    OTHER_SOURCE_RECORD = "OTHER_SOURCE_RECORD"
    UNKNOWN = "UNKNOWN"

    def __str__(self) -> str:
        return self.value


class RecordTypeMappingStatus(str, Enum):
    """How much confidence the object-class mapping carries.

    ``PENDING_REVIEW`` is not a soft ``CONFIRMED``. A record whose mapping is
    pending is quarantined from production evidence, because a record whose
    *kind* is unsettled cannot support a rule about it.
    """

    CONFIRMED = "CONFIRMED"
    PENDING_REVIEW = "PENDING_REVIEW"
    UNMAPPED = "UNMAPPED"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class RecordTypeMapping:
    """One object class, the type this project reads it as, and how sure it is.

    ``source_object_class`` and ``requested_container`` are both kept because
    they answer different questions: what the source said the record was, and
    what this project's legacy probe asked for when it received it. For the
    ClinPGx pair endpoint the container is a *request parameter*, so treating
    it as a source taxonomy would attribute the client's guesses to the source.
    """

    source_object_class: Optional[str]
    requested_container: Optional[str]
    record_type: EvidenceRecordType
    status: RecordTypeMappingStatus
    map_version: str = RECORD_TYPE_MAP_VERSION
    rationale: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.record_type, EvidenceRecordType):
            raise SourceRecordError("record_type must be an EvidenceRecordType")
        if not isinstance(self.status, RecordTypeMappingStatus):
            raise SourceRecordError(
                "status must be a RecordTypeMappingStatus")

    @property
    def is_production_eligible(self) -> bool:
        """Only a confirmed mapping of a known type may reach production."""
        return (self.status is RecordTypeMappingStatus.CONFIRMED
                and self.record_type is not EvidenceRecordType.UNKNOWN)

    def to_json(self) -> Dict[str, Any]:
        return {
            "source_object_class": self.source_object_class,
            "requested_container": self.requested_container,
            "record_type": self.record_type.value,
            "status": self.status.value,
            "map_version": self.map_version,
            "rationale": self.rationale,
            "production_eligible": self.is_production_eligible,
        }


class VersionStatus(str, Enum):
    """What is known about the source record's version.

    ``UNKNOWN_LEGACY`` exists so that a legacy import never has to invent a
    version string. A fabricated ``v1`` would be indistinguishable from a real
    one a year from now, and every later comparison would silently rest on it.
    """

    #: The source stated a version and it was read.
    KNOWN = "KNOWN"
    #: The source publishes this record type without versions at all.
    SOURCE_UNVERSIONED = "SOURCE_UNVERSIONED"
    #: A legacy import with no retained version metadata. Not a version.
    UNKNOWN_LEGACY = "UNKNOWN_LEGACY"
    #: Version metadata was expected in this shape and was absent.
    MISSING = "MISSING"
    #: Version metadata was present and unusable.
    INVALID = "INVALID"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class SourceRecordVersion:
    """A version, or an explicit statement that there is not one.

    ``KNOWN`` requires a value; every other status requires the absence of one,
    so "unknown" can never be stored as a version string that later reads like
    a real one.
    """

    status: VersionStatus
    value: Optional[str] = None
    raw_value: Optional[Any] = None
    basis: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.status, VersionStatus):
            raise SourceRecordError("status must be a VersionStatus")
        if self.status is VersionStatus.KNOWN:
            if not isinstance(self.value, str) or not self.value.strip():
                raise SourceRecordError(
                    "a KNOWN source record version requires a value")
        elif self.value is not None:
            raise SourceRecordError(
                "only a KNOWN version carries a value; %s must not, or "
                "'unknown' becomes a version string"
                % self.status.value)

    @property
    def is_production_eligible(self) -> bool:
        """A version this project can cite, or a source that has none."""
        return self.status in (VersionStatus.KNOWN,
                               VersionStatus.SOURCE_UNVERSIONED)

    @property
    def key_part(self) -> str:
        """The natural-key spelling: the value, or the status name."""
        return self.value if self.status is VersionStatus.KNOWN \
            else self.status.value

    def to_json(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "value": self.value,
            "raw_value": self.raw_value,
            "basis": self.basis,
            "production_eligible": self.is_production_eligible,
        }


class OriginStatus(str, Enum):
    """Whether the record itself says who asserted it."""

    #: An explicit source field named the asserting body.
    STATED_BY_SOURCE = "STATED_BY_SOURCE"
    #: The record carries no source field. Nothing is guessed from prose.
    NOT_STATED_BY_SOURCE = "NOT_STATED_BY_SOURCE"
    #: A value was present and matched more than one registered source.
    AMBIGUOUS = "AMBIGUOUS"
    #: A value was present and matched no registered source.
    UNREGISTERED = "UNREGISTERED"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class SourceAttribution:
    """Where the bytes came from, and who the record says asserted it.

    These are different facts and are stored separately. ClinPGx *provided* a
    DPWG guideline annotation; ClinPGx did not *assert* the guideline. Folding
    both into one ``source_registry_id`` would make every citation this project
    ever produces name the aggregator instead of the guideline body.

    ``origin_source_key`` is populated only from an explicit source field. A
    record that merely looks pharmacogenomic gets ``NOT_STATED_BY_SOURCE`` and
    an import issue - never a guessed CPIC.
    """

    provider_source_key: str
    origin_status: OriginStatus
    origin_source_key: Optional[str] = None
    raw_origin_value: Optional[str] = None
    origin_field: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.provider_source_key, str) \
                or not self.provider_source_key.strip():
            raise SourceRecordError(
                "provider_source_key is mandatory: a record whose bytes have "
                "no known provider cannot be traced at all")
        if not isinstance(self.origin_status, OriginStatus):
            raise SourceRecordError("origin_status must be an OriginStatus")
        if self.origin_status is OriginStatus.STATED_BY_SOURCE:
            if not self.origin_source_key or not self.raw_origin_value:
                raise SourceRecordError(
                    "STATED_BY_SOURCE requires both the registered origin key "
                    "and the raw value it was read from")
        elif self.origin_source_key is not None:
            raise SourceRecordError(
                "an origin source key may only accompany STATED_BY_SOURCE; "
                "%s must not carry one" % self.origin_status.value)

    @property
    def is_production_eligible(self) -> bool:
        return self.origin_status is OriginStatus.STATED_BY_SOURCE

    def to_json(self) -> Dict[str, Any]:
        return {
            "provider_source_key": self.provider_source_key,
            "origin_status": self.origin_status.value,
            "origin_source_key": self.origin_source_key,
            "raw_origin_value": self.raw_origin_value,
            "origin_field": self.origin_field,
            "production_eligible": self.is_production_eligible,
        }


@dataclass(frozen=True, slots=True)
class RawRecordLocator:
    """Exactly where in the raw bytes one source record was found.

    Carries the artifact's own digest, so the locator stays checkable after the
    fact: a reader can hash the file it has and tell whether this locator still
    describes it.

    ``pointer`` is an RFC 6901 JSON Pointer for a JSON artifact.
    ``csv_row_number`` is set instead when a CSV was *intentionally* referenced
    - the derived CSVs are comparison inputs, and referencing a row of one is a
    citation, never an import.
    """

    dataset_public_id: str
    snapshot_manifest_hash: str
    artifact_path: str
    artifact_sha256: str
    pointer: Optional[str] = None
    csv_row_number: Optional[int] = None
    artifact_id: Optional[str] = None
    requested_container: Optional[str] = None

    def __post_init__(self) -> None:
        for name in ("dataset_public_id", "snapshot_manifest_hash",
                     "artifact_path", "artifact_sha256"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise SourceRecordError(
                    "RawRecordLocator.%s must be a non-empty string" % name)
        if not is_canonical_digest(self.artifact_sha256):
            raise SourceRecordError(
                "artifact_sha256 must be a canonical sha256 digest, got %r"
                % (self.artifact_sha256,))
        _reject_unsafe_path(self.artifact_path, "artifact_path")
        if self.pointer is None and self.csv_row_number is None:
            raise SourceRecordError(
                "a locator must address a record: give a JSON pointer or a CSV "
                "row number, or the trace stops at the file")
        if self.pointer is not None and self.csv_row_number is not None:
            raise SourceRecordError(
                "a locator addresses one artifact shape: a JSON pointer or a "
                "CSV row, never both")
        if self.csv_row_number is not None:
            if isinstance(self.csv_row_number, bool) or \
                    not isinstance(self.csv_row_number, int) or \
                    self.csv_row_number < 1:
                raise SourceRecordError(
                    "csv_row_number is 1-based and counts data rows")

    @property
    def key(self) -> Tuple[str, str, str]:
        """Deterministic sort key: artifact, then address within it."""
        return (self.artifact_path,
                self.pointer or "",
                "" if self.csv_row_number is None
                else "%09d" % self.csv_row_number)

    def to_json(self) -> Dict[str, Any]:
        return {
            "dataset_public_id": self.dataset_public_id,
            "snapshot_manifest_hash": self.snapshot_manifest_hash,
            "artifact_id": self.artifact_id,
            "artifact_path": self.artifact_path,
            "artifact_sha256": self.artifact_sha256,
            "pointer": self.pointer,
            "csv_row_number": self.csv_row_number,
            "requested_container": self.requested_container,
        }


class TextLanguage(str, Enum):
    """The language of a source fragment, when the source states one.

    ``UNKNOWN`` is the default and the honest answer for ClinPGx, which labels
    no language on these fields. Guessing "probably English" would put a
    detection result where a source fact belongs.
    """

    UNKNOWN = "UNKNOWN"
    STATED_BY_SOURCE = "STATED_BY_SOURCE"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class SourceTextFragment:
    """One piece of source wording, exactly as the source wrote it.

    Fields are kept apart rather than concatenated. A summary and a
    recommendation joined into one blob cannot afterwards be attributed to the
    field each came from, and a citation that cannot say which field it quotes
    is not a citation.

    The text is never rewritten, translated, summarised or grammatically
    repaired. ``normalized_for_hash`` exists only so that two copies differing
    in incidental whitespace hash alike; :attr:`text` remains the original.
    """

    field_name: str
    text: str
    ordinal: int
    locator: RawRecordLocator
    language: TextLanguage = TextLanguage.UNKNOWN
    language_value: Optional[str] = None
    text_format: str = "text/plain"

    def __post_init__(self) -> None:
        if not isinstance(self.field_name, str) or not self.field_name.strip():
            raise SourceRecordError("field_name must be a non-empty string")
        if not isinstance(self.text, str) or not self.text:
            raise SourceRecordError(
                "a source text fragment with no text is not a fragment")
        if isinstance(self.ordinal, bool) or not isinstance(self.ordinal, int) \
                or self.ordinal < 0:
            raise SourceRecordError("ordinal must be a non-negative integer")
        if not isinstance(self.locator, RawRecordLocator):
            raise SourceRecordError("locator must be a RawRecordLocator")
        if self.language is TextLanguage.STATED_BY_SOURCE and \
                not (self.language_value or "").strip():
            raise SourceRecordError(
                "a stated language needs the value the source stated")

    @property
    def text_hash(self) -> str:
        """Digest of the whitespace-normalised text.

        Normalised for hashing only, so an incidental line break cannot make
        one quotation look like two. The exact original is what is stored.
        """
        return canonical_text_hash(self.text)

    @property
    def exact_text_hash(self) -> str:
        """Digest of the text exactly as stored, byte for byte."""
        return sha256_digest(self.text)

    def to_json(self) -> Dict[str, Any]:
        return {
            "field_name": self.field_name,
            "ordinal": self.ordinal,
            "text": self.text,
            "text_format": self.text_format,
            "language": self.language.value,
            "language_value": self.language_value,
            "text_hash": self.text_hash,
            "exact_text_hash": self.exact_text_hash,
            "locator": self.locator.to_json(),
        }


@dataclass(frozen=True, slots=True)
class PublicationReference:
    """One publication the source record cites, structurally validated only.

    No network lookup enriches a missing field, and no two publications are
    merged because their titles resemble each other. Validation is limited to
    shape - PMID digits, a conservative DOI prefix, a plausible year, an HTTPS
    URL - and every failure is recorded as an issue on the reference rather
    than by dropping it.
    """

    ordinal: int
    title: Optional[str] = None
    pmid: Optional[str] = None
    doi: Optional[str] = None
    year: Optional[int] = None
    url: Optional[str] = None
    raw_value: Any = None
    issues: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.ordinal, bool) or not isinstance(self.ordinal, int) \
                or self.ordinal < 0:
            raise SourceRecordError("ordinal must be a non-negative integer")
        object.__setattr__(self, "issues", tuple(self.issues))
        object.__setattr__(self, "raw_value", freeze_json(self.raw_value))

    @property
    def identity(self) -> Optional[str]:
        """A stable identifier when the source gave one, else ``None``.

        PMID first, then DOI. A title is never an identity: two records that
        print the same title have not been shown to cite the same article.
        """
        if self.pmid:
            return "pmid:%s" % self.pmid
        if self.doi:
            return "doi:%s" % self.doi
        return None

    def to_json(self) -> Dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "title": self.title,
            "pmid": self.pmid,
            "doi": self.doi,
            "year": self.year,
            "url": self.url,
            "identity": self.identity,
            "issues": list(self.issues),
            "raw_value": _thaw(self.raw_value),
        }


class EvidenceEntityRole(str, Enum):
    """How a canonical entity relates to the record that names it."""

    #: The source listed it in a related-entity field.
    RELATED_ENTITY = "RELATED_ENTITY"
    #: The record was retrieved under a query naming this entity.
    QUERY_CONTEXT = "QUERY_CONTEXT"
    #: The source named it inside a free-text field only.
    MENTIONED_IN_TEXT = "MENTIONED_IN_TEXT"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class EvidenceEntityLink:
    """One canonical gene or drug this record refers to.

    A record naming three genes produces three links, not three copies of the
    record. Duplicating a source record once per pair to fit scalar columns
    would make one statement look like several, and every count over it wrong.

    ``source_field`` and ``role`` keep the association's own provenance: a gene
    the source listed in ``relatedGenes`` is a different fact from one that
    appears only because the record was fetched under that gene's query.
    """

    entity_type: str
    canonical_key: str
    entity_uuid: str
    role: EvidenceEntityRole
    source_field: Optional[str] = None
    raw_value: Optional[str] = None

    def __post_init__(self) -> None:
        if self.entity_type not in ("GENE", "DRUG"):
            raise SourceRecordError(
                "entity_type must be GENE or DRUG, got %r" % (self.entity_type,))
        for name in ("canonical_key", "entity_uuid"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise SourceRecordError(
                    "EvidenceEntityLink.%s must be a non-empty string" % name)
        if not self.canonical_key.startswith(self.entity_type + ":"):
            raise SourceRecordError(
                "canonical key %r does not belong to entity type %s"
                % (self.canonical_key, self.entity_type))
        if not isinstance(self.role, EvidenceEntityRole):
            raise SourceRecordError("role must be an EvidenceEntityRole")

    @property
    def key(self) -> Tuple[str, str, str]:
        return (self.entity_type, self.canonical_key, self.role.value)

    def to_json(self) -> Dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "canonical_key": self.canonical_key,
            "entity_uuid": self.entity_uuid,
            "role": self.role.value,
            "source_field": self.source_field,
            "raw_value": self.raw_value,
        }


@dataclass(frozen=True, slots=True)
class EvidenceNaturalKey:
    """What makes one evidence record the same record across two builds.

    Dataset, provider, normalized record type, source record ID and version
    part. Deliberately *not* the payload: a source that corrects a typo has not
    produced a different record, and a natural key that changed with the bytes
    would make every correction look like a new statement.

    Changing any part produces a different key, and therefore a new identity
    rather than a silent mutation of an existing one.
    """

    dataset_public_id: str
    provider_source_key: str
    record_type: EvidenceRecordType
    source_record_id: str
    version_part: str

    def __post_init__(self) -> None:
        for name in ("dataset_public_id", "provider_source_key",
                     "source_record_id", "version_part"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise SourceRecordError(
                    "EvidenceNaturalKey.%s must be a non-empty string" % name)
        if not isinstance(self.record_type, EvidenceRecordType):
            raise SourceRecordError("record_type must be an EvidenceRecordType")

    def to_string(self) -> str:
        """The stable textual spelling used as an allocation key."""
        return "|".join((self.dataset_public_id, self.provider_source_key,
                         self.record_type.value, self.source_record_id,
                         self.version_part))

    @classmethod
    def parse(cls, text: str) -> "EvidenceNaturalKey":
        parts = text.split("|")
        if len(parts) != 5:
            raise SourceRecordError(
                "%r is not an evidence natural key; expected five "
                "'|'-separated parts" % (text,))
        try:
            record_type = EvidenceRecordType(parts[2])
        except ValueError as exc:
            raise SourceRecordError(
                "%r names an unknown record type %r" % (text, parts[2])) from exc
        return cls(parts[0], parts[1], record_type, parts[3], parts[4])

    def to_json(self) -> Dict[str, Any]:
        return {
            "dataset_public_id": self.dataset_public_id,
            "provider_source_key": self.provider_source_key,
            "record_type": self.record_type.value,
            "source_record_id": self.source_record_id,
            "version_part": self.version_part,
            "natural_key": self.to_string(),
        }


class IssueSeverity(str, Enum):
    """How much an import finding matters.

    In migration mode a ``BLOCKING`` issue does not stop the build; it is
    stored, counted, and it makes the record and the build
    production-ineligible. Quarantine records blockers visibly - it does not
    turn them into warnings.
    """

    BLOCKING = "BLOCKING"
    ADVISORY = "ADVISORY"
    INFORMATIONAL = "INFORMATIONAL"

    def __str__(self) -> str:
        return self.value


class ImportIssueCode(str, Enum):
    """Stable codes, so a refusal can be matched on rather than parsed."""

    # -- provenance and inputs -------------------------------------------
    RAW_SNAPSHOT_UNVERIFIED = "RAW_SNAPSHOT_UNVERIFIED"
    RAW_SNAPSHOT_QUARANTINED = "RAW_SNAPSHOT_QUARANTINED"
    RAW_SNAPSHOT_NOT_ACQUIRED = "RAW_SNAPSHOT_NOT_ACQUIRED"
    CANONICAL_BUILD_UNVERIFIED = "CANONICAL_BUILD_UNVERIFIED"
    DATASET_ID_MISMATCH = "DATASET_ID_MISMATCH"
    MANIFEST_HASH_MISMATCH = "MANIFEST_HASH_MISMATCH"
    SOURCE_POLICY_MISSING = "SOURCE_POLICY_MISSING"
    SOURCE_POLICY_NOT_APPROVED = "SOURCE_POLICY_NOT_APPROVED"

    # -- record identity and typing --------------------------------------
    RECORD_TYPE_PENDING_REVIEW = "RECORD_TYPE_PENDING_REVIEW"
    RECORD_TYPE_UNMAPPED = "RECORD_TYPE_UNMAPPED"
    SOURCE_RECORD_ID_MISSING = "SOURCE_RECORD_ID_MISSING"
    SOURCE_RECORD_ID_UNUSABLE = "SOURCE_RECORD_ID_UNUSABLE"
    SOURCE_VERSION_UNKNOWN_LEGACY = "SOURCE_VERSION_UNKNOWN_LEGACY"
    SOURCE_VERSION_MISSING = "SOURCE_VERSION_MISSING"
    SOURCE_VERSION_INVALID = "SOURCE_VERSION_INVALID"
    CONFLICTING_SOURCE_IDENTITY = "CONFLICTING_SOURCE_IDENTITY"

    # -- attribution ------------------------------------------------------
    ORIGIN_SOURCE_NOT_STATED = "ORIGIN_SOURCE_NOT_STATED"
    ORIGIN_SOURCE_UNREGISTERED = "ORIGIN_SOURCE_UNREGISTERED"
    ORIGIN_SOURCE_AMBIGUOUS = "ORIGIN_SOURCE_AMBIGUOUS"

    # -- entity links -----------------------------------------------------
    ENTITY_REFERENCE_UNRESOLVED = "ENTITY_REFERENCE_UNRESOLVED"
    ENTITY_REFERENCE_AMBIGUOUS = "ENTITY_REFERENCE_AMBIGUOUS"
    ENTITY_NOT_IN_CANONICAL_BUILD = "ENTITY_NOT_IN_CANONICAL_BUILD"
    NO_REQUIRED_ENTITY_LINK = "NO_REQUIRED_ENTITY_LINK"

    # -- publications -----------------------------------------------------
    PUBLICATION_FIELD_COUNT_MISMATCH = "PUBLICATION_FIELD_COUNT_MISMATCH"
    PUBLICATION_IDENTIFIER_INVALID = "PUBLICATION_IDENTIFIER_INVALID"
    PUBLICATION_MISSING = "PUBLICATION_MISSING"

    # -- text and payload -------------------------------------------------
    SOURCE_TEXT_ABSENT = "SOURCE_TEXT_ABSENT"
    PAYLOAD_NOT_AN_OBJECT = "PAYLOAD_NOT_AN_OBJECT"

    # -- build integrity --------------------------------------------------
    DUPLICATE_NATURAL_KEY = "DUPLICATE_NATURAL_KEY"
    PROVENANCE_MISSING = "PROVENANCE_MISSING"
    ALLOCATION_MISSING = "ALLOCATION_MISSING"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ImportIssue:
    """One finding about one record, or about the import as a whole."""

    code: ImportIssueCode
    severity: IssueSeverity
    subject: str
    detail: str
    natural_key: Optional[str] = None
    locator: Optional[RawRecordLocator] = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, ImportIssueCode):
            raise SourceRecordError("code must be an ImportIssueCode")
        if not isinstance(self.severity, IssueSeverity):
            raise SourceRecordError("severity must be an IssueSeverity")

    @property
    def blocking(self) -> bool:
        return self.severity is IssueSeverity.BLOCKING

    @property
    def key(self) -> Tuple[str, str, str]:
        return (self.code.value, self.natural_key or "", self.subject)

    def to_json(self) -> Dict[str, Any]:
        return {
            "code": self.code.value,
            "severity": self.severity.value,
            "subject": self.subject,
            "detail": self.detail,
            "natural_key": self.natural_key,
            "locator": self.locator.to_json() if self.locator else None,
        }


@dataclass(frozen=True)
class EvidenceRecordDraft:
    """One source record, ready to be identified and written.

    "Draft" means only that the UUID has not been attached yet - the *content*
    is final. Identity comes from :mod:`pgx.evidence.allocation`, never from
    here, for the same reason WP-07 keeps gene and drug identity out of its
    resolver: a record that minted its own UUID could not be rebuilt to the
    same bytes twice.
    """

    natural_key: EvidenceNaturalKey
    record_type_mapping: RecordTypeMapping
    attribution: SourceAttribution
    version: SourceRecordVersion
    source_record_id_raw: Any
    source_record_id_raw_type: str
    raw_source_payload: Any
    locators: Tuple[RawRecordLocator, ...]
    canonical_build_key: str
    canonical_build_content_hash: str
    entity_links: Tuple[EvidenceEntityLink, ...] = ()
    text_fragments: Tuple[SourceTextFragment, ...] = ()
    publications: Tuple[PublicationReference, ...] = ()
    normalized_metadata: Mapping[str, Any] = field(default_factory=dict)
    issues: Tuple[ImportIssue, ...] = ()
    record_uuid: Optional[str] = None
    evidence_record_version: str = EVIDENCE_RECORD_VERSION

    def __post_init__(self) -> None:
        if not self.locators:
            raise SourceRecordError(
                "an evidence record needs at least one raw locator; a record "
                "that cannot be found again in the raw bytes is not evidence")
        object.__setattr__(self, "locators", tuple(
            sorted(self.locators, key=lambda item: item.key)))
        object.__setattr__(self, "entity_links", tuple(
            sorted(self.entity_links, key=lambda item: item.key)))
        object.__setattr__(self, "text_fragments", tuple(
            sorted(self.text_fragments,
                   key=lambda item: (item.field_name, item.ordinal))))
        object.__setattr__(self, "publications", tuple(
            sorted(self.publications, key=lambda item: item.ordinal)))
        object.__setattr__(self, "issues", tuple(
            sorted(self.issues, key=lambda item: item.key)))
        object.__setattr__(self, "raw_source_payload",
                           freeze_json(self.raw_source_payload))

        metadata = dict(self.normalized_metadata or {})
        if RAW_PAYLOAD_NAMESPACE in metadata:
            raise ProhibitedFieldError(
                "normalized metadata may not contain %r: the raw payload has "
                "one reserved namespace so a source field can never present "
                "itself as something this project asserted"
                % RAW_PAYLOAD_NAMESPACE,
                field=RAW_PAYLOAD_NAMESPACE)
        offending = find_prohibited_fields(metadata)
        if offending:
            raise ProhibitedFieldError(
                "normalized evidence metadata carries project-authored "
                "field(s) %s. An evidence record states what a source said; a "
                "risk level or a plain-language conclusion here would make the "
                "store mean something it must not."
                % ", ".join(offending),
                fields=offending)
        object.__setattr__(self, "normalized_metadata",
                           MappingProxyType(dict(freeze_json(metadata))))

        for name in ("canonical_build_key", "canonical_build_content_hash"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise SourceRecordError(
                    "EvidenceRecordDraft.%s must be a non-empty string" % name)
        if not is_canonical_digest(self.canonical_build_content_hash):
            raise SourceRecordError(
                "canonical_build_content_hash must be a canonical digest")

    # -- derived facts ---------------------------------------------------

    @property
    def source_payload_hash(self) -> str:
        """Digest of the source payload alone.

        Distinct from the artifact byte hash (which covers a whole file) and
        from :meth:`content_hash` (which covers this project's rendering).
        Recomputing it from the raw artifact is what proves the record was not
        edited after extraction.
        """
        return sha256_digest(_thaw(self.raw_source_payload))

    @property
    def genes(self) -> Tuple[EvidenceEntityLink, ...]:
        return tuple(item for item in self.entity_links
                     if item.entity_type == "GENE")

    @property
    def drugs(self) -> Tuple[EvidenceEntityLink, ...]:
        return tuple(item for item in self.entity_links
                     if item.entity_type == "DRUG")

    @property
    def blocking_issues(self) -> Tuple[ImportIssue, ...]:
        return tuple(item for item in self.issues if item.blocking)

    @property
    def is_production_eligible(self) -> bool:
        """Whether this record could support a rule, if everything else did.

        Four independent conditions, each of which alone is disqualifying: the
        record's kind is settled, its version is citable, the record itself
        says who asserted it, and nothing blocking was found while reading it.
        """
        return (self.record_type_mapping.is_production_eligible
                and self.version.is_production_eligible
                and self.attribution.is_production_eligible
                and not self.blocking_issues)

    def content_identity(self) -> Dict[str, Any]:
        """Everything two builds of the same inputs must reproduce."""
        return {
            "evidence_record_version": self.evidence_record_version,
            "natural_key": self.natural_key.to_json(),
            "record_type_mapping": self.record_type_mapping.to_json(),
            "attribution": self.attribution.to_json(),
            "version": self.version.to_json(),
            "source_record_id_raw": _thaw(self.source_record_id_raw),
            "source_record_id_raw_type": self.source_record_id_raw_type,
            "source_payload_hash": self.source_payload_hash,
            "canonical_build_key": self.canonical_build_key,
            "canonical_build_content_hash": self.canonical_build_content_hash,
            "locators": [item.to_json() for item in self.locators],
            "entity_links": [item.to_json() for item in self.entity_links],
            "text_fragments": [item.to_json() for item in self.text_fragments],
            "publications": [item.to_json() for item in self.publications],
            "normalized_metadata": _thaw(self.normalized_metadata),
            "issues": [item.to_json() for item in self.issues],
        }

    def content_hash(self) -> str:
        """Digest of this project's rendering of the record.

        Excludes the allocated UUID, so two projects that allocated different
        identities still agree on what the record says.
        """
        return sha256_digest(self.content_identity())

    def to_json(self) -> Dict[str, Any]:
        payload = self.content_identity()
        payload["record_uuid"] = self.record_uuid
        payload["content_hash"] = self.content_hash()
        payload["production_eligible"] = self.is_production_eligible
        payload["blocking_issue_count"] = len(self.blocking_issues)
        # The one place the untouched source payload appears, under its
        # reserved namespace and never merged into normalized fields.
        payload[RAW_PAYLOAD_NAMESPACE] = _thaw(self.raw_source_payload)
        payload["payload_namespace_note"] = (
            "Everything under %r is the source's own record, stored unchanged. "
            "Field names there are the source's, not this project's claims."
            % RAW_PAYLOAD_NAMESPACE)
        return payload

    def with_identity(self, record_uuid: str) -> "EvidenceRecordDraft":
        """Return a copy carrying the allocated identity."""
        from dataclasses import replace
        return replace(self, record_uuid=record_uuid)


# -- helpers ------------------------------------------------------------


def normalize_source_record_id(value: Any) -> Tuple[Optional[str], str]:
    """Return ``(normalized_id, raw_type)`` for a source record identity.

    This source spells identities two ways: accession strings such as
    ``PA166104948`` and plain integers such as ``981351915``. Both are
    identities. An integer is rendered in its exact decimal form and the
    original type is kept beside it, so nothing is later mistaken for a string
    the source wrote.

    Booleans are refused because ``True`` is an ``int`` in Python and would
    become the record id ``"1"``. Floats are refused rather than coerced:
    ``9.813519e+08`` cannot be turned back into what the source meant.
    """
    if isinstance(value, bool):
        return None, "bool"
    if isinstance(value, int):
        return str(value), "int"
    if isinstance(value, str):
        text = value.strip()
        return (text or None), "str"
    if value is None:
        return None, "null"
    return None, type(value).__name__


def canonical_text_hash(text: str) -> str:
    """Digest of ``text`` with runs of whitespace collapsed.

    Used for indexing and equality only. The exact fragment is always stored
    beside it, so nothing depends on the normalised form.
    """
    return sha256_digest(" ".join(text.split()))


def find_prohibited_fields(payload: Any, path: str = "") -> Tuple[str, ...]:
    """Every prohibited project field name in a normalized payload.

    Recursive, and deliberately applied *only* to normalized metadata. Running
    it over a raw source payload would delete the source's own ``score`` and
    ``significance`` fields, which are facts about what the source published.
    """
    found: list = []
    _walk_for_prohibited(payload, path, found)
    return tuple(sorted(set(found)))


def _walk_for_prohibited(payload: Any, path: str, found: list) -> None:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            folded = str(key).strip().casefold().replace("-", "_").replace(
                " ", "_")
            where = "%s.%s" % (path, key) if path else str(key)
            if folded in PROHIBITED_METADATA_FIELDS:
                found.append(where)
            _walk_for_prohibited(value, where, found)
    elif isinstance(payload, (list, tuple)):
        for index, item in enumerate(payload):
            _walk_for_prohibited(item, "%s[%d]" % (path, index), found)


def _reject_unsafe_path(value: str, field_name: str) -> None:
    """Refuse an absolute or traversing artifact path."""
    text = value.replace("\\", "/")
    if text.startswith("/") or (len(text) > 1 and text[1] == ":"):
        raise SourceRecordError(
            "%s must be relative to the snapshot root, got %r"
            % (field_name, value))
    if any(part == ".." for part in text.split("/")):
        raise SourceRecordError(
            "%s must not traverse out of the snapshot, got %r"
            % (field_name, value))


def _thaw(value: Any) -> Any:
    """Plain-Python copy of a frozen JSON structure, for serialisation."""
    from pgx.domain.immutable import thaw_json
    try:
        return thaw_json(value)
    except Exception:  # pragma: no cover - thaw handles every frozen shape
        return value
