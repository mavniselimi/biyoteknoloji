# -*- coding: utf-8 -*-
"""Controlled vocabularies and records for scientific source governance (WP-05).

Standard library plus ``pgx.domain`` only. No SQLAlchemy, no configuration file
reading, no network: this module is the vocabulary, and it must be usable in a
unit test with nothing installed.

**The five things this module keeps apart.** ``architecture.md`` section 8.3
asks for source policy; the failure mode it is guarding against is the quiet
collapse of five different statements into one field called ``license``:

1. :class:`SourceEvidenceReference` - *what the source itself published*, held
   as a URL, a retrieval instant, a content hash and a short factual summary.
   Never the project's reading of it, and never a copy of the terms page.
2. :class:`SourceInterpretation` - *what the project team thinks that means*.
   Explicitly labelled as an interpretation, explicitly not a legal opinion,
   and attributed to whoever wrote it.
3. :class:`ReviewRecord` - *the decision a named human made*. Cannot exist
   without a reviewer, a decision instant and at least one evidence reference.
4. :class:`ReuseMatrix` - *which uses are permitted*, one answer per dimension,
   defaulting to :data:`ReusePermission.UNKNOWN` rather than to anything
   permissive.
5. ``permitted_claim_categories`` on :class:`SourcePolicyRecord` - *what the
   source may be cited for* once approved.

**Fail closed, structurally.** A :class:`SourcePolicyRecord` whose status
claims approval and which carries no supporting :class:`ReviewRecord` raises
:class:`~pgx.scientific.errors.ReviewIntegrityError` at construction. That is
deliberate: a configuration file must not be able to approve a source by
asserting that it is approved. Approval is a human act with a name attached,
and the only way to express it here is to attach one.

**Unknown is not permissive.** Every reuse dimension a record does not mention
reads as ``UNKNOWN``, and ``UNKNOWN`` blocks publication exactly as
``PROHIBITED`` does. The difference between them is what a reviewer must do
next, not what the system may do now.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from types import MappingProxyType
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Tuple, TypeVar

from pgx.domain.enums import SourceRole
from pgx.domain.hashing import ensure_utc, is_canonical_digest
from pgx.scientific.errors import (
    ConflictRegistryError,
    ReviewIntegrityError,
    SourcePolicyValidationError,
)

__all__ = [
    "AcquisitionMode",
    "ClaimCategory",
    "ConflictMateriality",
    "ConflictResolution",
    "ConflictStatus",
    "EvidenceType",
    "EvidenceVerificationStatus",
    "REUSE_DIMENSIONS",
    "ReuseDimension",
    "ReuseMatrix",
    "ReusePermission",
    "ReviewDecision",
    "ReviewRecord",
    "SourceConflict",
    "SourceEvidenceReference",
    "SourceInterpretation",
    "SourcePolicyRecord",
    "SourcePolicyStatus",
    "APPROVING_STATUSES",
    "PERMISSIVE_PERMISSIONS",
]


_VocabularyT = TypeVar("_VocabularyT", bound="_VocabularyEnum")


class _VocabularyEnum(str, Enum):
    """String-valued enum with a stable spelling and no ordering.

    Ordering is disabled for the same reason the domain disables it: none of
    these vocabularies is a magnitude, and ``PENDING_REVIEW < APPROVED`` is a
    sentence that should not compile.
    """

    def __str__(self) -> str:
        return self.value

    def __lt__(self, other: object) -> bool:  # pragma: no cover - guard
        raise TypeError(
            "%s values are not ordered; comparing them as magnitudes hides a "
            "governance decision behind an inequality" % type(self).__name__)

    __le__ = __lt__
    __gt__ = __lt__
    __ge__ = __lt__

    @classmethod
    def parse(cls: type[_VocabularyT], value: object,
              field_name: str) -> _VocabularyT:
        """Return the member named by ``value``, or raise with the legal set.

        Unknown strings are never coerced to a default. A typo in a policy file
        that silently became ``UNKNOWN`` would be a policy change made by
        accident.
        """
        if isinstance(value, cls):
            return value
        if not isinstance(value, str):
            raise SourcePolicyValidationError(
                "%s must be a string, got %r" % (field_name, type(value).__name__))
        try:
            return cls(value)
        except ValueError:
            raise SourcePolicyValidationError(
                "%s: %r is not a valid %s; permitted values are %s"
                % (field_name, value, cls.__name__,
                   ", ".join(member.value for member in cls))) from None


# ---------------------------------------------------------------------------
# Vocabularies
# ---------------------------------------------------------------------------


class SourcePolicyStatus(_VocabularyEnum):
    """Where a source stands in the project's review process.

    This is a *process* state, not a quality judgement. ``PENDING_REVIEW`` says
    nothing bad about a source; it says the project has not yet done the work
    that would let it use the source responsibly.
    """

    #: Referenced somewhere but carrying no policy record at all. The most
    #: restrictive state: the project knows nothing, so it may do nothing.
    UNREGISTERED = "UNREGISTERED"
    #: A record exists and is awaiting a human reviewer. The default.
    PENDING_REVIEW = "PENDING_REVIEW"
    #: A named reviewer has started but has not decided.
    UNDER_REVIEW = "UNDER_REVIEW"
    #: A named reviewer approved the source for the recorded claim categories.
    APPROVED = "APPROVED"
    #: Approved, but only under the restrictions the review record names.
    APPROVED_WITH_RESTRICTIONS = "APPROVED_WITH_RESTRICTIONS"
    #: A named reviewer decided the source may not be used.
    REJECTED = "REJECTED"
    #: Previously approved, now withdrawn - licence changed, evidence went
    #: stale, or the source itself changed. Treated exactly like un-approved.
    SUSPENDED = "SUSPENDED"


#: The only two statuses that permit publication. Everything else blocks.
APPROVING_STATUSES: Tuple[SourcePolicyStatus, ...] = (
    SourcePolicyStatus.APPROVED,
    SourcePolicyStatus.APPROVED_WITH_RESTRICTIONS,
)


class AcquisitionMode(_VocabularyEnum):
    """How the project is permitted to obtain records from a source.

    Recording this separately from the licence matters: a source may permit
    reuse of data a human downloaded by hand while prohibiting the automated
    crawl that would have produced the same bytes.
    """

    #: No decision has been made. Blocks automated acquisition.
    NOT_DETERMINED = "NOT_DETERMINED"
    #: A human downloads a published file and records where it came from.
    MANUAL_DOWNLOAD = "MANUAL_DOWNLOAD"
    #: An interface the source publishes and documents for programmatic use.
    OFFICIAL_API = "OFFICIAL_API"
    #: A bulk export obtained under a specific written licence or agreement.
    LICENSED_BULK_EXPORT = "LICENSED_BULK_EXPORT"
    #: Facts transcribed by a human from a publication, cited by DOI or PMID.
    PUBLICATION_TRANSCRIPTION = "PUBLICATION_TRANSCRIPTION"
    #: Produced by this project from its own records; no external source.
    INTERNAL_DERIVATION = "INTERNAL_DERIVATION"


#: Acquisition modes that a machine may perform unattended, once approved.
AUTOMATED_ACQUISITION_MODES: Tuple[AcquisitionMode, ...] = (
    AcquisitionMode.OFFICIAL_API,
    AcquisitionMode.LICENSED_BULK_EXPORT,
)


class EvidenceType(_VocabularyEnum):
    """What kind of primary artefact a licensing fact rests on.

    Only official artefacts appear here. There is deliberately no member for a
    search-result snippet, a blog post or an encyclopaedia article: those are
    not licensing authority, and giving them a slot would invite their use.
    """

    #: Nothing has been retrieved. The default, and it blocks approval.
    NOT_OBTAINED = "NOT_OBTAINED"
    #: The source's own terms-of-use or terms-of-service page.
    OFFICIAL_TERMS_PAGE = "OFFICIAL_TERMS_PAGE"
    #: A licence file or licence statement the source publishes.
    OFFICIAL_LICENSE_FILE = "OFFICIAL_LICENSE_FILE"
    #: The source's own API documentation, where it states use conditions.
    OFFICIAL_API_DOCUMENTATION = "OFFICIAL_API_DOCUMENTATION"
    #: A peer-reviewed publication by the source owners, cited by DOI or PMID.
    OFFICIAL_PUBLICATION = "OFFICIAL_PUBLICATION"
    #: Written permission addressed to this project, held on file.
    DIRECT_WRITTEN_PERMISSION = "DIRECT_WRITTEN_PERMISSION"


class EvidenceVerificationStatus(_VocabularyEnum):
    """Whether the project has actually seen the artefact it names.

    The existence of a URL is not the retrieval of a document.  ``BLOCKED``
    exists so that an unreachable network records as an unmet obligation
    rather than quietly disappearing.
    """

    #: No retrieval has been attempted.
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    #: Retrieval was attempted and failed. Never an approval.
    BLOCKED = "BLOCKED"
    #: Retrieved, hashed and summarised by this project.
    VERIFIED = "VERIFIED"
    #: Retrieved once, but the recorded hash no longer matches the source.
    STALE = "STALE"


class ClaimCategory(_VocabularyEnum):
    """What a source is permitted to be cited for once approved.

    Approval is never global. A source approved as a phenotype mapping
    authority has not thereby been approved to carry a prescribing
    recommendation, and this vocabulary is what keeps the two apart.
    """

    #: A prescribing recommendation published by a guideline body.
    PRIMARY_GUIDELINE_RECOMMENDATION = "PRIMARY_GUIDELINE_RECOMMENDATION"
    #: A curated annotation supporting, but not itself constituting, guidance.
    SUPPORTING_ANNOTATION = "SUPPORTING_ANNOTATION"
    #: An allele-to-function assignment.
    ALLELE_FUNCTION_ASSIGNMENT = "ALLELE_FUNCTION_ASSIGNMENT"
    #: A diplotype-to-phenotype mapping.
    PHENOTYPE_MAPPING = "PHENOTYPE_MAPPING"
    #: A statement carried in a regulator-approved drug label.
    DRUG_LABEL_STATEMENT = "DRUG_LABEL_STATEMENT"
    #: A bibliographic reference only; carries no interpretation.
    LITERATURE_REFERENCE = "LITERATURE_REFERENCE"
    #: Technical bookkeeping inside this project. Never scientific evidence.
    INTERNAL_BOOKKEEPING = "INTERNAL_BOOKKEEPING"


class ReusePermission(_VocabularyEnum):
    """The answer to one reuse question for one source.

    ``UNKNOWN`` and ``PROHIBITED`` have the same effect on publication and
    differ only in what a reviewer must do next. That equivalence is the whole
    fail-closed rule, expressed in two members instead of a comment.
    """

    #: The source's own published terms permit this use, on the evidence held.
    ALLOWED = "ALLOWED"
    #: Permitted only under conditions the record names. Blocks until a review
    #: records those conditions as met.
    RESTRICTED = "RESTRICTED"
    #: The source's own published terms forbid this use.
    PROHIBITED = "PROHIBITED"
    #: Nobody has established an answer. Blocks.
    UNKNOWN = "UNKNOWN"
    #: The question does not arise for this source - for example
    #: redistribution of a source this project derives itself.
    NOT_APPLICABLE = "NOT_APPLICABLE"


#: The permissions that do not, by themselves, block a use.
PERMISSIVE_PERMISSIONS: Tuple[ReusePermission, ...] = (
    ReusePermission.ALLOWED,
    ReusePermission.NOT_APPLICABLE,
)


class ReuseDimension(_VocabularyEnum):
    """One question the licensing matrix must answer for every source.

    Ten dimensions, because "can we use this?" is ten different questions and
    a single yes/no has to lie about at least nine of them.
    """

    #: Keep a copy of retrieved records on project-controlled storage.
    LOCAL_STORAGE = "LOCAL_STORAGE"
    #: Read and analyse those records inside the project.
    INTERNAL_ANALYSIS = "INTERNAL_ANALYSIS"
    #: Produce derived records - normalised, mapped or summarised.
    DERIVED_WORK_CREATION = "DERIVED_WORK_CREATION"
    #: Publish aggregated or summarised output outside the project.
    AGGREGATED_REDISTRIBUTION = "AGGREGATED_REDISTRIBUTION"
    #: Publish the source's records verbatim.
    VERBATIM_REDISTRIBUTION = "VERBATIM_REDISTRIBUTION"
    #: Any use in a commercial product or paid service.
    COMMERCIAL_USE = "COMMERCIAL_USE"
    #: Retrieve records by program rather than by hand.
    AUTOMATED_ACQUISITION = "AUTOMATED_ACQUISITION"
    #: Retrieve whole collections rather than individual records.
    BULK_DOWNLOAD = "BULK_DOWNLOAD"
    #: Pass records to a party outside this project.
    THIRD_PARTY_SHARING = "THIRD_PARTY_SHARING"
    #: Show the source's text to an end user in a report or interface.
    PUBLIC_DISPLAY = "PUBLIC_DISPLAY"


#: Canonical dimension order. Fixed so that every rendered matrix, every hash
#: and every report column reads the same on every machine.
REUSE_DIMENSIONS: Tuple[ReuseDimension, ...] = tuple(ReuseDimension)


class ReviewDecision(_VocabularyEnum):
    """What a named human concluded about a source."""

    APPROVE = "APPROVE"
    APPROVE_WITH_RESTRICTIONS = "APPROVE_WITH_RESTRICTIONS"
    REJECT = "REJECT"
    #: The reviewer looked and could not decide on the evidence held.
    REQUEST_MORE_INFORMATION = "REQUEST_MORE_INFORMATION"


#: Decisions that can back an approving status. Nothing else can.
APPROVING_DECISIONS: Tuple[ReviewDecision, ...] = (
    ReviewDecision.APPROVE,
    ReviewDecision.APPROVE_WITH_RESTRICTIONS,
)


class ConflictStatus(_VocabularyEnum):
    """Lifecycle of a disagreement between two sources."""

    #: Recorded, nobody has looked yet.
    OPEN = "OPEN"
    #: A named reviewer is working on it.
    UNDER_REVIEW = "UNDER_REVIEW"
    #: A named reviewer decided how the disagreement is handled.
    RESOLVED = "RESOLVED"
    #: A named reviewer decided the disagreement may stand, with a reason.
    ACCEPTED_VARIANCE = "ACCEPTED_VARIANCE"


#: Conflict states that no longer block publication.
SETTLED_CONFLICT_STATUSES: Tuple[ConflictStatus, ...] = (
    ConflictStatus.RESOLVED,
    ConflictStatus.ACCEPTED_VARIANCE,
)


class ConflictMateriality(_VocabularyEnum):
    """Whether a disagreement could change what the system outputs.

    ``UNDETERMINED`` blocks. Deciding that a conflict does not matter is a
    judgement someone has to make and sign, not a default.
    """

    MATERIAL = "MATERIAL"
    NON_MATERIAL = "NON_MATERIAL"
    UNDETERMINED = "UNDETERMINED"


# ---------------------------------------------------------------------------
# Small validation helpers
# ---------------------------------------------------------------------------


def _require_text(value: object, field_name: str, max_length: int = 4000) -> str:
    """Return a non-blank string, or raise.

    ``max_length`` is a policy guard, not a database limit: this repository
    stores short factual summaries of source terms, never the terms themselves.
    """
    if not isinstance(value, str):
        raise SourcePolicyValidationError(
            "%s must be a string, got %r" % (field_name, type(value).__name__))
    if not value.strip():
        raise SourcePolicyValidationError("%s must not be blank" % field_name)
    if len(value) > max_length:
        raise SourcePolicyValidationError(
            "%s is %d characters; the limit is %d. Store a short factual "
            "summary and the official URL, not the source's full text."
            % (field_name, len(value), max_length))
    return value


def _require_optional_text(
    value: object, field_name: str, max_length: int = 4000
) -> Optional[str]:
    """Return a non-blank string or ``None``; a blank string is a mistake."""
    if value is None:
        return None
    return _require_text(value, field_name, max_length)


def _require_tuple_of_text(value: object, field_name: str) -> Tuple[str, ...]:
    """Return a sorted, duplicate-free tuple of non-blank strings."""
    if isinstance(value, str) or not isinstance(value, (tuple, list)):
        raise SourcePolicyValidationError(
            "%s must be a list of strings, got %r"
            % (field_name, type(value).__name__))
    items = []
    for index, item in enumerate(value):
        items.append(_require_text(item, "%s[%d]" % (field_name, index)))
    return tuple(sorted(set(items)))


def _require_utc(value: object, field_name: str) -> _dt.datetime:
    """Return an aware UTC datetime, or raise."""
    if not isinstance(value, _dt.datetime):
        raise SourcePolicyValidationError(
            "%s must be a datetime, got %r" % (field_name, type(value).__name__))
    return ensure_utc(value, field_name)


def _require_optional_utc(value: object, field_name: str) -> Optional[_dt.datetime]:
    if value is None:
        return None
    return _require_utc(value, field_name)


def _isoformat(value: Optional[_dt.datetime]) -> Optional[str]:
    """Render an instant in the one spelling this project stores."""
    if value is None:
        return None
    return value.astimezone(_dt.timezone.utc).isoformat().replace("+00:00", "Z")


_OFFICIAL_URL_SCHEMES = ("https://",)


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceEvidenceReference:
    """A pointer to something the *source* published, and nothing else.

    What is stored: the artefact type, its official URL, when this project
    retrieved it, a content hash where one could be computed, and a short
    factual summary in the project's own words.

    What is deliberately **not** stored: the artefact's text. Copying a terms
    page into this repository would create an uncontrolled second copy of
    someone else's document whose staleness nobody would notice.

    ``verification`` is the honest part. A reference with
    :data:`EvidenceVerificationStatus.BLOCKED` records that retrieval was
    attempted and failed; it must never be read as evidence of anything except
    that the obligation is outstanding.
    """

    evidence_type: EvidenceType
    official_url: Optional[str] = None
    retrieved_at: Optional[_dt.datetime] = None
    content_hash: Optional[str] = None
    summary: Optional[str] = None
    verification: EvidenceVerificationStatus = EvidenceVerificationStatus.NOT_ATTEMPTED
    blocked_reason: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_type, EvidenceType):
            raise SourcePolicyValidationError("evidence_type must be an EvidenceType")
        if not isinstance(self.verification, EvidenceVerificationStatus):
            raise SourcePolicyValidationError(
                "verification must be an EvidenceVerificationStatus")
        url = _require_optional_text(self.official_url, "official_url", 2000)
        if url is not None and not url.startswith(_OFFICIAL_URL_SCHEMES):
            raise SourcePolicyValidationError(
                "official_url must be an https URL published by the source; "
                "got %r" % url)
        object.__setattr__(self, "official_url", url)
        object.__setattr__(
            self, "retrieved_at", _require_optional_utc(self.retrieved_at, "retrieved_at"))
        digest = _require_optional_text(self.content_hash, "content_hash", 100)
        if digest is not None and not is_canonical_digest(digest):
            raise SourcePolicyValidationError(
                "content_hash must be a canonical sha256:<64 hex> digest, got %r"
                % digest)
        object.__setattr__(self, "content_hash", digest)
        object.__setattr__(
            self, "summary", _require_optional_text(self.summary, "summary", 1000))
        object.__setattr__(
            self, "blocked_reason",
            _require_optional_text(self.blocked_reason, "blocked_reason", 500))

        if self.evidence_type is EvidenceType.NOT_OBTAINED:
            if self.verification is EvidenceVerificationStatus.VERIFIED:
                raise SourcePolicyValidationError(
                    "an evidence reference of type NOT_OBTAINED cannot be VERIFIED")
        if self.verification is EvidenceVerificationStatus.VERIFIED:
            if self.official_url is None or self.retrieved_at is None:
                raise SourcePolicyValidationError(
                    "a VERIFIED evidence reference must carry both the official "
                    "URL it was retrieved from and the retrieval instant")
        if self.verification is EvidenceVerificationStatus.BLOCKED:
            if self.blocked_reason is None:
                raise SourcePolicyValidationError(
                    "a BLOCKED evidence reference must say why retrieval failed; "
                    "an unexplained block is indistinguishable from an untried one")

    @property
    def is_official(self) -> bool:
        """True when this names an official artefact type at all."""
        return self.evidence_type is not EvidenceType.NOT_OBTAINED

    @property
    def is_verified(self) -> bool:
        """True only when this project actually retrieved the artefact."""
        return self.verification is EvidenceVerificationStatus.VERIFIED

    def to_json(self) -> Dict[str, Any]:
        """Plain-JSON form, keys in a fixed order for stable rendering."""
        return {
            "evidence_type": self.evidence_type.value,
            "official_url": self.official_url,
            "retrieved_at": _isoformat(self.retrieved_at),
            "content_hash": self.content_hash,
            "summary": self.summary,
            "verification": self.verification.value,
            "blocked_reason": self.blocked_reason,
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any], where: str) -> "SourceEvidenceReference":
        """Build from parsed JSON, rejecting unknown keys."""
        _reject_unknown_keys(payload, cls.__slots__, where)
        retrieved = payload.get("retrieved_at")
        return cls(
            evidence_type=EvidenceType.parse(
                payload.get("evidence_type"), "%s.evidence_type" % where),
            official_url=payload.get("official_url"),
            retrieved_at=_parse_instant(retrieved, "%s.retrieved_at" % where),
            content_hash=payload.get("content_hash"),
            summary=payload.get("summary"),
            verification=EvidenceVerificationStatus.parse(
                payload.get("verification", EvidenceVerificationStatus.NOT_ATTEMPTED.value),
                "%s.verification" % where),
            blocked_reason=payload.get("blocked_reason"),
        )


@dataclass(frozen=True, slots=True)
class SourceInterpretation:
    """The project team's reading of what a source's terms mean.

    Held separately from :class:`SourceEvidenceReference` on purpose. The
    source published words; this is what somebody here concluded from them, and
    conflating the two would make it impossible to re-examine a conclusion when
    the source's wording turns out to have said something else.

    ``is_legal_opinion`` is always false. This project's engineers are not its
    lawyers, and a field that could be set true would eventually be set true.
    """

    summary: str
    interpreted_by: str
    interpreted_at: _dt.datetime
    open_questions: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "summary", _require_text(self.summary, "summary", 2000))
        object.__setattr__(
            self, "interpreted_by", _require_text(self.interpreted_by, "interpreted_by", 200))
        object.__setattr__(
            self, "interpreted_at", _require_utc(self.interpreted_at, "interpreted_at"))
        object.__setattr__(
            self, "open_questions",
            _require_tuple_of_text(self.open_questions, "open_questions")
            if self.open_questions else ())

    @property
    def is_legal_opinion(self) -> bool:
        """Always false. A project interpretation is not legal advice."""
        return False

    def to_json(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "interpreted_by": self.interpreted_by,
            "interpreted_at": _isoformat(self.interpreted_at),
            "open_questions": list(self.open_questions),
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any], where: str) -> "SourceInterpretation":
        _reject_unknown_keys(payload, cls.__slots__, where)
        instant = _parse_instant(payload.get("interpreted_at"), "%s.interpreted_at" % where)
        if instant is None:
            raise SourcePolicyValidationError("%s.interpreted_at is required" % where)
        return cls(
            summary=payload.get("summary"),
            interpreted_by=payload.get("interpreted_by"),
            interpreted_at=instant,
            open_questions=tuple(payload.get("open_questions") or ()),
        )


@dataclass(frozen=True, slots=True)
class ReviewRecord:
    """A decision a named human made, on evidence, at a stated time.

    Every field here is a thing a forged approval would have to invent. An
    approving decision therefore requires all three of: a reviewer name, a
    decision instant, and at least one official evidence reference. A record
    that cannot supply them is not permitted to exist.

    ``expires_at`` exists because a licence read in 2026 is not a licence in
    2029. An expired approval reads as no approval.
    """

    decision: ReviewDecision
    reviewer_name: str
    reviewer_role: str
    decided_at: _dt.datetime
    evidence_urls: Tuple[str, ...] = ()
    restrictions: Tuple[str, ...] = ()
    notes: Optional[str] = None
    expires_at: Optional[_dt.datetime] = None

    def __post_init__(self) -> None:
        if not isinstance(self.decision, ReviewDecision):
            raise SourcePolicyValidationError("decision must be a ReviewDecision")
        object.__setattr__(
            self, "reviewer_name", _require_text(self.reviewer_name, "reviewer_name", 200))
        object.__setattr__(
            self, "reviewer_role", _require_text(self.reviewer_role, "reviewer_role", 200))
        object.__setattr__(
            self, "decided_at", _require_utc(self.decided_at, "decided_at"))
        object.__setattr__(
            self, "evidence_urls",
            _require_tuple_of_text(self.evidence_urls, "evidence_urls")
            if self.evidence_urls else ())
        object.__setattr__(
            self, "restrictions",
            _require_tuple_of_text(self.restrictions, "restrictions")
            if self.restrictions else ())
        object.__setattr__(
            self, "notes", _require_optional_text(self.notes, "notes", 2000))
        object.__setattr__(
            self, "expires_at", _require_optional_utc(self.expires_at, "expires_at"))

        if self.expires_at is not None and self.expires_at <= self.decided_at:
            raise ReviewIntegrityError(
                "a review that expires at or before it was decided has never been "
                "in force")
        if self.decision in APPROVING_DECISIONS and not self.evidence_urls:
            raise ReviewIntegrityError(
                "an approving review must cite at least one official evidence "
                "URL; approval without evidence is an assertion, not a review")
        if (self.decision is ReviewDecision.APPROVE_WITH_RESTRICTIONS
                and not self.restrictions):
            raise ReviewIntegrityError(
                "APPROVE_WITH_RESTRICTIONS must name the restrictions it imposes")

    @property
    def is_approving(self) -> bool:
        """True for the two decisions that can back an approving status."""
        return self.decision in APPROVING_DECISIONS

    def is_expired(self, now: _dt.datetime) -> bool:
        """True when ``now`` is at or past the expiry instant."""
        if self.expires_at is None:
            return False
        return ensure_utc(now, "now") >= self.expires_at

    def to_json(self) -> Dict[str, Any]:
        return {
            "decision": self.decision.value,
            "reviewer_name": self.reviewer_name,
            "reviewer_role": self.reviewer_role,
            "decided_at": _isoformat(self.decided_at),
            "evidence_urls": list(self.evidence_urls),
            "restrictions": list(self.restrictions),
            "notes": self.notes,
            "expires_at": _isoformat(self.expires_at),
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any], where: str) -> "ReviewRecord":
        _reject_unknown_keys(payload, cls.__slots__, where)
        decided = _parse_instant(payload.get("decided_at"), "%s.decided_at" % where)
        if decided is None:
            raise SourcePolicyValidationError("%s.decided_at is required" % where)
        return cls(
            decision=ReviewDecision.parse(payload.get("decision"), "%s.decision" % where),
            reviewer_name=payload.get("reviewer_name"),
            reviewer_role=payload.get("reviewer_role"),
            decided_at=decided,
            evidence_urls=tuple(payload.get("evidence_urls") or ()),
            restrictions=tuple(payload.get("restrictions") or ()),
            notes=payload.get("notes"),
            expires_at=_parse_instant(payload.get("expires_at"), "%s.expires_at" % where),
        )


@dataclass(frozen=True, slots=True)
class ReuseMatrix:
    """One permission per reuse dimension, defaulting to ``UNKNOWN``.

    Stored as a complete mapping rather than a sparse one: a dimension nobody
    filled in and a dimension somebody marked ``UNKNOWN`` mean the same thing,
    and materialising both as ``UNKNOWN`` removes the chance that a caller
    reads absence as permission.
    """

    permissions: Mapping[ReuseDimension, ReusePermission] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.permissions, Mapping):
            raise SourcePolicyValidationError("permissions must be a mapping")
        complete: Dict[ReuseDimension, ReusePermission] = {}
        for dimension in REUSE_DIMENSIONS:
            complete[dimension] = ReusePermission.UNKNOWN
        for key, value in self.permissions.items():
            dimension = (key if isinstance(key, ReuseDimension)
                         else ReuseDimension.parse(key, "reuse dimension"))
            permission = (value if isinstance(value, ReusePermission)
                          else ReusePermission.parse(
                              value, "reuse.%s" % dimension.value))
            complete[dimension] = permission
        # Stored behind a MappingProxyType for the same reason FrozenMapping is:
        # a frozen dataclass whose one field is a plain dict is not immutable,
        # and ``matrix.permissions[d] = ALLOWED`` would be a licensing decision
        # made by assignment.
        object.__setattr__(self, "permissions", MappingProxyType(complete))

    def permission(self, dimension: ReuseDimension) -> ReusePermission:
        """Return the permission for one dimension. Never raises for a member."""
        return self.permissions[dimension]

    def is_permitted(self, dimension: ReuseDimension) -> bool:
        """True only for ``ALLOWED`` and ``NOT_APPLICABLE``.

        ``RESTRICTED`` is false here on purpose: a restricted use is permitted
        only once someone has recorded that the restriction is satisfied, and
        that record lives on the review, not on the matrix.
        """
        return self.permissions[dimension] in PERMISSIVE_PERMISSIONS

    def dimensions_with(self, permission: ReusePermission) -> Tuple[ReuseDimension, ...]:
        """Every dimension carrying ``permission``, in canonical order."""
        return tuple(d for d in REUSE_DIMENSIONS if self.permissions[d] is permission)

    @property
    def unknown_dimensions(self) -> Tuple[ReuseDimension, ...]:
        """Dimensions nobody has answered. Each one blocks publication."""
        return self.dimensions_with(ReusePermission.UNKNOWN)

    @property
    def prohibited_dimensions(self) -> Tuple[ReuseDimension, ...]:
        return self.dimensions_with(ReusePermission.PROHIBITED)

    @property
    def is_fully_answered(self) -> bool:
        return not self.unknown_dimensions

    def to_json(self) -> Dict[str, str]:
        """Complete matrix in canonical dimension order."""
        return {d.value: self.permissions[d].value for d in REUSE_DIMENSIONS}

    @classmethod
    def unknown(cls) -> "ReuseMatrix":
        """The default matrix: every question unanswered."""
        return cls({})

    @classmethod
    def from_json(cls, payload: Optional[Mapping[str, Any]], where: str) -> "ReuseMatrix":
        if payload is None:
            return cls.unknown()
        if not isinstance(payload, Mapping):
            raise SourcePolicyValidationError("%s must be an object" % where)
        known = {d.value for d in REUSE_DIMENSIONS}
        unknown_keys = sorted(set(payload) - known)
        if unknown_keys:
            raise SourcePolicyValidationError(
                "%s names unknown reuse dimensions: %s"
                % (where, ", ".join(unknown_keys)))
        return cls({ReuseDimension.parse(key, "%s key" % where):
                    ReusePermission.parse(value, "%s.%s" % (where, key))
                    for key, value in payload.items()})


@dataclass(frozen=True, slots=True)
class SourcePolicyRecord:
    """Everything the project has decided, and not decided, about one source.

    The invariant worth stating plainly: **a record cannot approve itself**.
    ``status`` may only name an approving state when ``review`` carries an
    approving :class:`ReviewRecord`, and a ``ReviewRecord`` cannot be built
    without a named reviewer, an instant and cited evidence. So the path from a
    configuration file to "this source is approved" runs through a human, by
    construction rather than by convention.

    ``permitted_claim_categories`` is likewise gated: an unapproved record may
    not claim any category at all, because a category list is a statement about
    what the source has been cleared for.
    """

    source_key: str
    display_name: str
    role: SourceRole
    status: SourcePolicyStatus = SourcePolicyStatus.PENDING_REVIEW
    acquisition_mode: AcquisitionMode = AcquisitionMode.NOT_DETERMINED
    version_policy: Optional[str] = None
    citation_policy: Optional[str] = None
    license_identifier: Optional[str] = None
    provider: Optional[str] = None
    jurisdiction: Optional[str] = None
    reuse: ReuseMatrix = field(default_factory=ReuseMatrix.unknown)
    permitted_claim_categories: Tuple[ClaimCategory, ...] = ()
    evidence: Tuple[SourceEvidenceReference, ...] = ()
    interpretation: Optional[SourceInterpretation] = None
    review: Optional[ReviewRecord] = None
    legacy_aliases: Tuple[str, ...] = ()
    blocking_reasons: Tuple[str, ...] = ()
    notes: Optional[str] = None
    active: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "source_key", _require_text(self.source_key, "source_key", 120))
        object.__setattr__(
            self, "display_name", _require_text(self.display_name, "display_name", 300))
        if not isinstance(self.role, SourceRole):
            raise SourcePolicyValidationError("role must be a SourceRole")
        if not isinstance(self.status, SourcePolicyStatus):
            raise SourcePolicyValidationError("status must be a SourcePolicyStatus")
        if not isinstance(self.acquisition_mode, AcquisitionMode):
            raise SourcePolicyValidationError(
                "acquisition_mode must be an AcquisitionMode")
        if not isinstance(self.reuse, ReuseMatrix):
            raise SourcePolicyValidationError("reuse must be a ReuseMatrix")
        if not isinstance(self.active, bool):
            raise SourcePolicyValidationError("active must be a bool")

        for name in ("version_policy", "citation_policy", "license_identifier",
                     "provider", "jurisdiction", "notes"):
            object.__setattr__(
                self, name, _require_optional_text(getattr(self, name), name, 2000))

        categories = tuple(self.permitted_claim_categories or ())
        for category in categories:
            if not isinstance(category, ClaimCategory):
                raise SourcePolicyValidationError(
                    "permitted_claim_categories must contain ClaimCategory members")
        object.__setattr__(
            self, "permitted_claim_categories",
            tuple(sorted(set(categories), key=lambda item: item.value)))

        evidence = tuple(self.evidence or ())
        for item in evidence:
            if not isinstance(item, SourceEvidenceReference):
                raise SourcePolicyValidationError(
                    "evidence must contain SourceEvidenceReference records")
        object.__setattr__(self, "evidence", evidence)

        if self.interpretation is not None and not isinstance(
                self.interpretation, SourceInterpretation):
            raise SourcePolicyValidationError(
                "interpretation must be a SourceInterpretation")
        if self.review is not None and not isinstance(self.review, ReviewRecord):
            raise SourcePolicyValidationError("review must be a ReviewRecord")

        object.__setattr__(
            self, "blocking_reasons",
            _require_tuple_of_text(self.blocking_reasons, "blocking_reasons")
            if self.blocking_reasons else ())
        # Exact strings the frozen legacy files use for this source. Recorded
        # deliberately, one spelling at a time, so that matching legacy data to
        # a policy is a decision in a reviewed file rather than a string-
        # distance function's opinion.
        object.__setattr__(
            self, "legacy_aliases",
            _require_tuple_of_text(self.legacy_aliases, "legacy_aliases")
            if self.legacy_aliases else ())

        # -- the anti-forgery invariants ---------------------------------
        if self.status in APPROVING_STATUSES:
            if self.review is None or not self.review.is_approving:
                raise ReviewIntegrityError(
                    "source %r claims status %s but carries no approving review "
                    "record. A configuration file may not approve a source; a "
                    "named reviewer must." % (self.source_key, self.status.value))
            if not self.has_official_evidence:
                raise ReviewIntegrityError(
                    "source %r claims status %s but cites no official evidence. "
                    "Approval must rest on primary source material."
                    % (self.source_key, self.status.value))
            if (self.status is SourcePolicyStatus.APPROVED_WITH_RESTRICTIONS
                    and self.review.decision is not
                    ReviewDecision.APPROVE_WITH_RESTRICTIONS):
                raise ReviewIntegrityError(
                    "source %r claims APPROVED_WITH_RESTRICTIONS but its review "
                    "decision is %s" % (self.source_key, self.review.decision.value))
        elif self.permitted_claim_categories:
            raise ReviewIntegrityError(
                "source %r is %s but already names permitted claim categories. "
                "What a source may be cited for is decided at review, not "
                "before it." % (self.source_key, self.status.value))

        if self.role is SourceRole.INTERNAL_SYSTEM:
            outside = tuple(c.value for c in self.permitted_claim_categories
                            if c is not ClaimCategory.INTERNAL_BOOKKEEPING)
            if outside:
                raise ReviewIntegrityError(
                    "source %r is INTERNAL_SYSTEM but claims %s. Technical "
                    "bookkeeping can never be scientific evidence "
                    "(SourceRegistryEntry enforces the same rule)."
                    % (self.source_key, ", ".join(outside)))

    # -- derived state ---------------------------------------------------

    @property
    def has_official_evidence(self) -> bool:
        """True when at least one reference names a real official artefact.

        A ``NOT_OBTAINED`` reference does not count, and neither does a
        ``BLOCKED`` one: recording that retrieval failed is honest, but it is
        not evidence of what the terms say.
        """
        return any(item.is_official and item.is_verified for item in self.evidence)

    @property
    def is_approved(self) -> bool:
        """True only for an approving status backed by an approving review."""
        return (self.status in APPROVING_STATUSES
                and self.review is not None
                and self.review.is_approving)

    def effective_status(self, now: _dt.datetime) -> SourcePolicyStatus:
        """The status in force at ``now``, with expiry applied.

        An approval whose review has expired reads as
        :data:`SourcePolicyStatus.PENDING_REVIEW`, not as approved-but-stale:
        the work needed to use the source again is exactly the review work.
        """
        if self.status in APPROVING_STATUSES and self.review is not None:
            if self.review.is_expired(now):
                return SourcePolicyStatus.PENDING_REVIEW
        return self.status

    def may_support_claim(self, category: ClaimCategory, now: _dt.datetime) -> bool:
        """True when this source is cleared, right now, for ``category``."""
        if not self.active:
            return False
        if self.effective_status(now) not in APPROVING_STATUSES:
            return False
        return category in self.permitted_claim_categories

    def to_json(self) -> Dict[str, Any]:
        """Plain-JSON form. Key order is fixed so rendering is deterministic."""
        return {
            "source_key": self.source_key,
            "display_name": self.display_name,
            "role": self.role.value,
            "status": self.status.value,
            "acquisition_mode": self.acquisition_mode.value,
            "provider": self.provider,
            "jurisdiction": self.jurisdiction,
            "version_policy": self.version_policy,
            "citation_policy": self.citation_policy,
            "license_identifier": self.license_identifier,
            "reuse": self.reuse.to_json(),
            "permitted_claim_categories": [c.value for c in self.permitted_claim_categories],
            "evidence": [item.to_json() for item in self.evidence],
            "interpretation": (self.interpretation.to_json()
                               if self.interpretation is not None else None),
            "review": self.review.to_json() if self.review is not None else None,
            "legacy_aliases": list(self.legacy_aliases),
            "blocking_reasons": list(self.blocking_reasons),
            "notes": self.notes,
            "active": self.active,
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any], where: str) -> "SourcePolicyRecord":
        """Build one record from parsed JSON, rejecting unknown keys."""
        if not isinstance(payload, Mapping):
            raise SourcePolicyValidationError("%s must be an object" % where)
        _reject_unknown_keys(payload, cls.__slots__, where)
        role_value = payload.get("role")
        if not isinstance(role_value, str):
            raise SourcePolicyValidationError("%s.role must be a string" % where)
        try:
            role = SourceRole(role_value)
        except ValueError:
            raise SourcePolicyValidationError(
                "%s.role: %r is not a valid SourceRole; permitted values are %s"
                % (where, role_value,
                   ", ".join(member.value for member in SourceRole))) from None

        categories = payload.get("permitted_claim_categories") or ()
        if isinstance(categories, str) or not isinstance(categories, (list, tuple)):
            raise SourcePolicyValidationError(
                "%s.permitted_claim_categories must be a list" % where)

        evidence_payload = payload.get("evidence") or ()
        if isinstance(evidence_payload, str) or not isinstance(
                evidence_payload, (list, tuple)):
            raise SourcePolicyValidationError("%s.evidence must be a list" % where)

        interpretation_payload = payload.get("interpretation")
        review_payload = payload.get("review")
        return cls(
            source_key=payload.get("source_key"),
            display_name=payload.get("display_name"),
            role=role,
            status=SourcePolicyStatus.parse(
                payload.get("status", SourcePolicyStatus.PENDING_REVIEW.value),
                "%s.status" % where),
            acquisition_mode=AcquisitionMode.parse(
                payload.get("acquisition_mode", AcquisitionMode.NOT_DETERMINED.value),
                "%s.acquisition_mode" % where),
            version_policy=payload.get("version_policy"),
            citation_policy=payload.get("citation_policy"),
            license_identifier=payload.get("license_identifier"),
            provider=payload.get("provider"),
            jurisdiction=payload.get("jurisdiction"),
            reuse=ReuseMatrix.from_json(payload.get("reuse"), "%s.reuse" % where),
            permitted_claim_categories=tuple(
                ClaimCategory.parse(item, "%s.permitted_claim_categories[%d]" % (where, i))
                for i, item in enumerate(categories)),
            evidence=tuple(
                SourceEvidenceReference.from_json(item, "%s.evidence[%d]" % (where, i))
                for i, item in enumerate(evidence_payload)),
            interpretation=(
                SourceInterpretation.from_json(
                    interpretation_payload, "%s.interpretation" % where)
                if interpretation_payload else None),
            review=(ReviewRecord.from_json(review_payload, "%s.review" % where)
                    if review_payload else None),
            legacy_aliases=tuple(payload.get("legacy_aliases") or ()),
            blocking_reasons=tuple(payload.get("blocking_reasons") or ()),
            notes=payload.get("notes"),
            active=_require_bool(payload.get("active", True), "%s.active" % where),
        )


@dataclass(frozen=True, slots=True)
class ConflictResolution:
    """How a named human settled a disagreement between sources.

    ``preferred_source_key`` is optional and deliberately so: "CPIC wins" is a
    decision somebody must make for a specific disagreement, with a reason.
    There is no global precedence order in this package, because a global order
    would silently answer questions nobody asked.
    """

    decision_summary: str
    rationale: str
    decided_by: str
    decided_at: _dt.datetime
    preferred_source_key: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "decision_summary",
            _require_text(self.decision_summary, "decision_summary", 2000))
        object.__setattr__(
            self, "rationale", _require_text(self.rationale, "rationale", 4000))
        object.__setattr__(
            self, "decided_by", _require_text(self.decided_by, "decided_by", 200))
        object.__setattr__(
            self, "decided_at", _require_utc(self.decided_at, "decided_at"))
        object.__setattr__(
            self, "preferred_source_key",
            _require_optional_text(self.preferred_source_key, "preferred_source_key", 120))

    def to_json(self) -> Dict[str, Any]:
        return {
            "decision_summary": self.decision_summary,
            "rationale": self.rationale,
            "decided_by": self.decided_by,
            "decided_at": _isoformat(self.decided_at),
            "preferred_source_key": self.preferred_source_key,
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any], where: str) -> "ConflictResolution":
        _reject_unknown_keys(payload, cls.__slots__, where)
        decided = _parse_instant(payload.get("decided_at"), "%s.decided_at" % where)
        if decided is None:
            raise SourcePolicyValidationError("%s.decided_at is required" % where)
        return cls(
            decision_summary=payload.get("decision_summary"),
            rationale=payload.get("rationale"),
            decided_by=payload.get("decided_by"),
            decided_at=decided,
            preferred_source_key=payload.get("preferred_source_key"),
        )


@dataclass(frozen=True, slots=True)
class SourceConflict:
    """Two or more sources disagreeing about the same subject.

    Recording a conflict is not resolving it, and this type keeps the two
    apart. A conflict is settled only when it carries a
    :class:`ConflictResolution` with a named decider - so "nobody looked" can
    never present itself as "no problem found".
    """

    conflict_key: str
    subject: str
    source_keys: Tuple[str, ...]
    description: str
    materiality: ConflictMateriality = ConflictMateriality.UNDETERMINED
    status: ConflictStatus = ConflictStatus.OPEN
    detected_at: Optional[_dt.datetime] = None
    resolution: Optional[ConflictResolution] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "conflict_key", _require_text(self.conflict_key, "conflict_key", 200))
        object.__setattr__(self, "subject", _require_text(self.subject, "subject", 500))
        keys = _require_tuple_of_text(self.source_keys, "source_keys")
        if len(keys) < 2:
            raise ConflictRegistryError(
                "conflict %r names %d source(s); a conflict needs at least two "
                "distinct sources to disagree" % (self.conflict_key, len(keys)))
        object.__setattr__(self, "source_keys", keys)
        object.__setattr__(
            self, "description", _require_text(self.description, "description", 4000))
        if not isinstance(self.materiality, ConflictMateriality):
            raise ConflictRegistryError("materiality must be a ConflictMateriality")
        if not isinstance(self.status, ConflictStatus):
            raise ConflictRegistryError("status must be a ConflictStatus")
        object.__setattr__(
            self, "detected_at", _require_optional_utc(self.detected_at, "detected_at"))
        if self.resolution is not None and not isinstance(
                self.resolution, ConflictResolution):
            raise ConflictRegistryError("resolution must be a ConflictResolution")

        if self.status in SETTLED_CONFLICT_STATUSES and self.resolution is None:
            raise ConflictRegistryError(
                "conflict %r is %s but carries no resolution record. A conflict "
                "is settled by a named human, not by a status field."
                % (self.conflict_key, self.status.value))
        if self.status not in SETTLED_CONFLICT_STATUSES and self.resolution is not None:
            raise ConflictRegistryError(
                "conflict %r carries a resolution but its status is %s"
                % (self.conflict_key, self.status.value))
        if (self.resolution is not None
                and self.resolution.preferred_source_key is not None
                and self.resolution.preferred_source_key not in self.source_keys):
            raise ConflictRegistryError(
                "conflict %r prefers source %r, which is not one of the sources "
                "in conflict" % (self.conflict_key,
                                 self.resolution.preferred_source_key))

    @property
    def is_settled(self) -> bool:
        """True when a named human has decided what happens."""
        return self.status in SETTLED_CONFLICT_STATUSES

    @property
    def blocks_publication(self) -> bool:
        """True while an unsettled conflict could change what is published.

        ``UNDETERMINED`` blocks alongside ``MATERIAL``. Deciding that a
        disagreement does not matter is itself a review decision.
        """
        if self.is_settled:
            return False
        return self.materiality in (ConflictMateriality.MATERIAL,
                                    ConflictMateriality.UNDETERMINED)

    def to_json(self) -> Dict[str, Any]:
        return {
            "conflict_key": self.conflict_key,
            "subject": self.subject,
            "source_keys": list(self.source_keys),
            "description": self.description,
            "materiality": self.materiality.value,
            "status": self.status.value,
            "detected_at": _isoformat(self.detected_at),
            "resolution": (self.resolution.to_json()
                           if self.resolution is not None else None),
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any], where: str) -> "SourceConflict":
        if not isinstance(payload, Mapping):
            raise ConflictRegistryError("%s must be an object" % where)
        _reject_unknown_keys(payload, cls.__slots__, where)
        resolution_payload = payload.get("resolution")
        return cls(
            conflict_key=payload.get("conflict_key"),
            subject=payload.get("subject"),
            source_keys=tuple(payload.get("source_keys") or ()),
            description=payload.get("description"),
            materiality=ConflictMateriality.parse(
                payload.get("materiality", ConflictMateriality.UNDETERMINED.value),
                "%s.materiality" % where),
            status=ConflictStatus.parse(
                payload.get("status", ConflictStatus.OPEN.value), "%s.status" % where),
            detected_at=_parse_instant(payload.get("detected_at"), "%s.detected_at" % where),
            resolution=(ConflictResolution.from_json(
                resolution_payload, "%s.resolution" % where)
                if resolution_payload else None),
        )


# ---------------------------------------------------------------------------
# Shared parsing helpers
# ---------------------------------------------------------------------------


def _require_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise SourcePolicyValidationError(
            "%s must be a boolean, got %r" % (field_name, type(value).__name__))
    return value


def _reject_unknown_keys(
    payload: Mapping[str, Any], allowed: Any, where: str
) -> None:
    """Refuse keys the record does not define.

    A misspelt ``licence_identifier`` that was silently ignored would leave a
    record looking deliberately blank when somebody had in fact filled it in.
    """
    if not isinstance(payload, Mapping):
        raise SourcePolicyValidationError("%s must be an object" % where)
    unknown = sorted(set(payload) - set(allowed))
    if unknown:
        raise SourcePolicyValidationError(
            "%s carries unknown key(s): %s" % (where, ", ".join(unknown)))


def _parse_instant(value: object, field_name: str) -> Optional[_dt.datetime]:
    """Parse an ISO-8601 UTC instant. Naive and non-UTC spellings are refused.

    Timestamps in this package are audit facts. One recorded without an offset
    names no instant, and one recorded in a local zone names a different
    instant on a different machine.
    """
    if value is None:
        return None
    if isinstance(value, _dt.datetime):
        return _require_utc(value, field_name)
    if not isinstance(value, str):
        raise SourcePolicyValidationError(
            "%s must be an ISO-8601 UTC string, got %r"
            % (field_name, type(value).__name__))
    text = value.strip()
    if not text:
        raise SourcePolicyValidationError("%s must not be blank" % field_name)
    normalised = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = _dt.datetime.fromisoformat(normalised)
    except ValueError:
        raise SourcePolicyValidationError(
            "%s is not a valid ISO-8601 instant: %r" % (field_name, value)) from None
    if parsed.tzinfo is None:
        raise SourcePolicyValidationError(
            "%s has no timezone offset; a naive timestamp names no instant and "
            "cannot be audited: %r" % (field_name, value))
    return ensure_utc(parsed, field_name)

