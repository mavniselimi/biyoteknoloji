# -*- coding: utf-8 -*-
"""The validation case, and the two halves it is deliberately split into.

A validation case is **two objects**, not one object with a visibility flag:

:class:`ValidationCaseMetadata`
    Identity, role, provenance, fingerprints, classification, compatibility.
    Publishable. This is what a manifest holds and what a listing returns.

:class:`RestrictedPayload`
    The observations, the medications and - for a holdout - whatever a case
    is *for*. Never publishable, never committed beside the rules it tests.

The split is structural because a flag is not. A single class with
``expected_result: Optional[...]`` and ``public: bool`` publishes the expected
result the first time somebody serialises it without reading the flag, and
that mistake is invisible in review. Here the public object has no field to
put an answer in, so the mistake cannot be made: ``metadata.to_json()`` is
safe by construction rather than by discipline.

**No expected result exists anywhere in WP-18.** Not in the metadata, not in
the payload, not in the schemas. A payload carries the *inputs* a case
presents; what the correct output is, is a scientific judgement recorded by
WP-22's protocol under a named expert. Providing a field for it here would
invite filling it, and an AI-authored expected answer is the specific thing
this repository may not produce.

**Prohibited fields are refused at any depth.** The list is long and blunt on
purpose: this is the boundary between a research prototype and a system that
has touched a person's record, and it is enforced by structure rather than by
review.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from pgx.domain.hashing import ensure_utc, sha256_digest
from pgx.domain.immutable import freeze_json
from pgx.validation.compatibility import ReleaseCompatibility
from pgx.validation.errors import (ProvenanceError, RestrictedContentError,
                                   ValidationCaseError, VisibilityError)
from pgx.validation.fingerprint import (content_fingerprint,
                                        derivation_family_fingerprint,
                                        normalise_text)
from pgx.validation.vocabulary import (AUTHOR_CONTEXTS, DataClassification,
                                       HOLDOUT_ROLES, ValidationCaseRole,
                                       VisibilityLevel)

__all__ = [
    "CASE_SCHEMA_VERSION",
    "PROHIBITED_CASE_FIELDS",
    "PROHIBITED_PAYLOAD_FIELDS",
    "Provenance",
    "RestrictedPayload",
    "ValidationCaseId",
    "ValidationCaseMetadata",
    "assert_no_prohibited_fields",
    "default_visibility_for",
]

CASE_SCHEMA_VERSION = "pgx-wp18-validation-case/1"

#: Fields no validation case may carry, at any nesting depth, in metadata or
#: in a payload.
#:
#: Three groups, and they are refused for three different reasons.
#:
#: *Real-patient data.* A VCF, a lab report or an EHR extract is data about a
#: person. Accepting one here would make this a system that processes patient
#: data, which is P2-03/P2-04 and is not authorised by WP-18.
#:
#: *Genotype-level input.* Diplotypes, star alleles and activity scores are
#: refused because the engine consumes phenotypes and translating between them
#: is a scientific act this product does not perform (SAFETY-INV-004 is the
#: nearest relative of that decision).
#:
#: *Expected answers.* A case that carries its own answer is a scored case,
#: and a scored case in a public manifest is a leaked holdout.
PROHIBITED_CASE_FIELDS: Tuple[str, ...] = (
    # Real-patient and identifying data
    "patient", "patient_name", "patient_id", "person", "person_name",
    "subject_name", "mrn", "medical_record_number", "nhs_number",
    "national_id", "tckn", "ssn", "date_of_birth", "dob", "birth_date",
    "address", "postcode", "zip_code", "phone", "email", "ip_address",
    "ehr", "ehr_record", "encounter", "admission", "chart", "chart_note",
    "lab_report", "laboratory_report", "lab_result", "pathology_report",
    "clinical_note", "clinical_text", "free_text", "narrative",
    "diagnosis", "indication", "comorbidity", "dose", "dosage", "posology",
    # Genotype-level and raw sequencing input
    "genotype", "diplotype", "haplotype", "star_allele", "alleles",
    "allele", "activity_score", "variant", "variants", "rsid", "zygosity",
    "vcf", "vcf_path", "vcf_content", "fastq", "bam", "cram", "sam",
    "sequence", "raw_sequence", "sequencing_run",
    # Expected answers and scores
    "expected_result", "expected_results", "expected_attention",
    "expected_coverage", "expected_findings", "expected_answer",
    "gold_standard", "ground_truth", "reference_answer", "correct_answer",
    "answer_key", "score", "grade", "concordance", "accuracy", "pass_rate",
    "validation_result", "benchmark_result", "rank", "ranking",
    # Uploaded arbitrary content
    "upload", "uploaded_file", "attachment", "file_content", "blob",
)

#: A payload holds inputs. It may hold observations and medications - which is
#: why those are absent from the list above - but it may still not hold an
#: answer or a person. Identical list; named separately so a future decision
#: to diverge is a visible edit rather than an accident.
PROHIBITED_PAYLOAD_FIELDS: Tuple[str, ...] = PROHIBITED_CASE_FIELDS

_CASE_ID = re.compile(r"^PGX-VAL-[A-Z0-9][A-Z0-9\-]{2,46}[A-Z0-9]$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._@\-]{1,63}$")


def assert_no_prohibited_fields(payload: Any, prohibited: Sequence[str],
                                path: str = "$", depth: int = 0) -> None:
    """Walk to any depth and refuse the first prohibited key found.

    Depth matters more than breadth here. A top-level check is satisfied by
    one extra layer of nesting, and the person adding that layer is not
    usually being devious - they are following a shape that felt natural. The
    refusal names the *location*, never the value, so an error raised over a
    genotype does not carry the genotype into a log.
    """
    if depth > 24:
        raise ValidationCaseError("case content nests deeper than 24 levels "
                                  "at %s" % path)
    blocked = {name.lower() for name in prohibited}
    if isinstance(payload, Mapping):
        for key in payload:
            if not isinstance(key, str):
                raise ValidationCaseError("case keys must be strings at %s"
                                          % path)
            here = "%s.%s" % (path, key)
            if key.strip().lower() in blocked:
                raise ValidationCaseError(
                    "%s is a field this product does not accept; refused at "
                    "%s. WP-18 holds synthetic and literature-derived cases "
                    "only - real-patient ingestion is P2-03/P2-04."
                    % (key, here))
            assert_no_prohibited_fields(payload[key], prohibited, here,
                                        depth + 1)
    elif isinstance(payload, (list, tuple)):
        for index, item in enumerate(payload):
            assert_no_prohibited_fields(item, prohibited,
                                        "%s[%d]" % (path, index), depth + 1)


def default_visibility_for(role: ValidationCaseRole) -> VisibilityLevel:
    """The only visibility a role may start with. Fail-closed by role.

    A holdout is ``RESTRICTED`` and there is no argument that makes it
    anything else at construction. Widening it later is WP-22's protocol
    decision, taken by a person, and is not expressible in this package.
    """
    if not isinstance(role, ValidationCaseRole):
        raise VisibilityError("role must be a ValidationCaseRole, got %r"
                              % type(role).__name__)
    return (VisibilityLevel.AUTHOR_VISIBLE
            if role is ValidationCaseRole.DEVELOPMENT
            else VisibilityLevel.RESTRICTED)


@dataclass(frozen=True, slots=True)
class ValidationCaseId:
    """``PGX-VAL-...``. Immutable, type-distinct, and never reused.

    A plain string would be equal to any other string with the same
    characters, including a development case identifier that happened to
    match. Making it a type means a function that takes a case id cannot be
    handed a drug key by mistake, and it means the identifier prints as
    itself in an error message.
    """

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise ValidationCaseError("ValidationCaseId requires a str, got "
                                      "%r" % type(self.value).__name__)
        if not _CASE_ID.match(self.value):
            raise ValidationCaseError(
                "ValidationCaseId must match PGX-VAL-<token>, got %r"
                % self.value)

    def __str__(self) -> str:
        return self.value

    def to_json(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where a case came from, and how it was made.

    Required for every case and *verifiable* for a holdout. "Verifiable" here
    means the source identity is recorded and, where the source is a file this
    repository holds, its digest is recorded too - so a later reader can check
    that the thing cited is the thing that was read.

    ``derived_from_development`` is stated by the author rather than guessed.
    A case built by editing a demo profile is not independent evidence however
    much it has been changed, and the person who built it is the only one who
    knows. Recording it as a claim means the audit can refuse it; inferring it
    would mean the audit could be fooled by a rename.
    """

    source_identity: str
    derivation_method: str
    derived_from_development: bool
    source_digest: Optional[str] = None
    citation: Optional[str] = None
    author: Optional[str] = None

    def __post_init__(self) -> None:
        source = normalise_text(str(self.source_identity or ""))
        method = normalise_text(str(self.derivation_method or ""))
        if len(source) < 3:
            raise ProvenanceError(
                "a case must record where it came from; a case of unknown "
                "origin cannot be shown to be independent")
        if len(method) < 3:
            raise ProvenanceError("a case must record how it was derived")
        if not isinstance(self.derived_from_development, bool):
            raise ProvenanceError("derived_from_development must be a bool; "
                                  "it is a claim, not an inference")
        if self.source_digest is not None and not re.match(
                r"^sha256:[0-9a-f]{64}$", str(self.source_digest)):
            raise ProvenanceError("source_digest must be a canonical "
                                  "sha256:<hex> value")
        object.__setattr__(self, "source_identity", source)
        object.__setattr__(self, "derivation_method", method)

    @property
    def family_fingerprint(self) -> str:
        return derivation_family_fingerprint(self.source_identity,
                                             self.derivation_method)

    def to_json(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "source_identity": self.source_identity,
            "derivation_method": self.derivation_method,
            "derived_from_development": self.derived_from_development,
            "derivation_family_fingerprint": self.family_fingerprint,
        }
        for name in ("source_digest", "citation", "author"):
            value = getattr(self, name)
            if value is not None:
                payload[name] = value
        return payload


@dataclass(frozen=True, slots=True)
class RestrictedPayload:
    """What a case presents to the engine. Never published.

    Holds inputs only. There is no field for an expected result, and
    :data:`PROHIBITED_PAYLOAD_FIELDS` refuses one under every name it could
    plausibly be given - so "the payload also records what should happen" is
    not a change somebody can make by adding a key.
    """

    content: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.content, Mapping) or not self.content:
            raise ValidationCaseError("a payload needs non-empty content")
        assert_no_prohibited_fields(self.content, PROHIBITED_PAYLOAD_FIELDS)
        object.__setattr__(self, "content", freeze_json(dict(self.content),
                                                        "$"))

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.content)

    @property
    def payload_hash(self) -> str:
        """Digest of the payload as stored. Distinct from the fingerprint.

        The fingerprint answers "is this the same case"; the payload hash
        answers "is this the same bytes". A reformatted payload keeps its
        fingerprint and changes its hash, and both questions get asked.
        """
        return sha256_digest({"schema_version": CASE_SCHEMA_VERSION,
                              "content": dict(self.content)})


@dataclass(frozen=True, slots=True)
class ValidationCaseMetadata:
    """The publishable half. Carries no answer and no payload content.

    Every field here is safe to print, commit and diff. That is the invariant
    the class exists to hold, and :meth:`to_json` is asserted against the
    prohibited list by test rather than trusted.
    """

    case_id: ValidationCaseId
    role: ValidationCaseRole
    classification: DataClassification
    provenance: Provenance
    content_fingerprint: str
    no_pii_assertion: str
    created_at: _dt.datetime
    compatibility: ReleaseCompatibility
    visibility: VisibilityLevel = None  # type: ignore[assignment]
    payload_hash: Optional[str] = None
    payload_reference: Optional[str] = None
    title: Optional[str] = None
    notes: Optional[str] = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.case_id, ValidationCaseId):
            raise ValidationCaseError("case_id must be a ValidationCaseId")
        if not isinstance(self.role, ValidationCaseRole):
            raise ValidationCaseError("role must be a ValidationCaseRole; a "
                                      "string could name a role that does "
                                      "not exist")
        if not isinstance(self.classification, DataClassification):
            raise ValidationCaseError("classification must be a "
                                      "DataClassification")
        if not isinstance(self.provenance, Provenance):
            raise ValidationCaseError("provenance must be a Provenance")
        if not isinstance(self.compatibility, ReleaseCompatibility):
            raise ValidationCaseError("compatibility must be a "
                                      "ReleaseCompatibility")
        if not re.match(r"^sha256:[0-9a-f]{64}$",
                        str(self.content_fingerprint)):
            raise ValidationCaseError("content_fingerprint must be a "
                                      "canonical sha256:<hex> value")
        if len(normalise_text(str(self.no_pii_assertion or ""))) < 16:
            raise ValidationCaseError(
                "every case states, in its own words, that it carries no data "
                "about a person; an empty assertion is not one")

        if self.visibility is None:
            object.__setattr__(self, "visibility",
                               default_visibility_for(self.role))
        if not isinstance(self.visibility, VisibilityLevel):
            raise VisibilityError("visibility must be a VisibilityLevel")
        if self.role in HOLDOUT_ROLES and \
                self.visibility is VisibilityLevel.AUTHOR_VISIBLE:
            raise VisibilityError(
                "a %s case may not be AUTHOR_VISIBLE; that is the one "
                "combination the partition exists to prevent"
                % self.role.value)

        if self.role in HOLDOUT_ROLES:
            if self.provenance.derived_from_development:
                raise ProvenanceError(
                    "a holdout case may not declare a development or demo "
                    "fixture as its source: it would be measuring the rules "
                    "against the material that shaped them")
            if self.provenance.source_digest is None and \
                    self.provenance.citation is None:
                raise ProvenanceError(
                    "a holdout case needs verifiable provenance - a source "
                    "digest or a citation - or its independence cannot be "
                    "shown")

        if self.payload_hash is not None and not re.match(
                r"^sha256:[0-9a-f]{64}$", str(self.payload_hash)):
            raise ValidationCaseError("payload_hash must be a canonical "
                                      "sha256:<hex> value")
        object.__setattr__(self, "created_at",
                           ensure_utc(self.created_at, "created_at"))

        for name, value in (("title", self.title), ("notes", self.notes)):
            if value is not None:
                object.__setattr__(self, name, normalise_text(str(value)))

        extra = dict(self.extra or {})
        assert_no_prohibited_fields(extra, PROHIBITED_CASE_FIELDS, "$.extra")
        object.__setattr__(self, "extra", freeze_json(extra, "$"))

    @property
    def is_holdout(self) -> bool:
        return self.role in HOLDOUT_ROLES

    @property
    def is_validation_evidence(self) -> bool:
        """Whether this case may enter a validation denominator.

        Development cases may not, and that is not a policy this method
        applies - it is what the role *means*. WP-21 reads this rather than
        re-deciding it.
        """
        return self.role in HOLDOUT_ROLES

    def visible_to(self, context_kind) -> bool:
        """Whether this context may read the payload. Metadata is separate."""
        if self.visibility is VisibilityLevel.AUTHOR_VISIBLE:
            return True
        if self.visibility is VisibilityLevel.PUBLIC_METADATA:
            return False
        return context_kind not in AUTHOR_CONTEXTS and \
            self.role is not ValidationCaseRole.EXPERT_HOLDOUT

    def to_json(self) -> Dict[str, Any]:
        """The publishable rendering. Contains no payload and no answer."""
        payload: Dict[str, Any] = {
            "schema_version": CASE_SCHEMA_VERSION,
            "case_id": self.case_id.to_json(),
            "role": self.role.value,
            "classification": self.classification.value,
            "visibility": self.visibility.value,
            "is_holdout": self.is_holdout,
            "is_validation_evidence": self.is_validation_evidence,
            "content_fingerprint": self.content_fingerprint,
            "no_pii_assertion": self.no_pii_assertion,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "provenance": self.provenance.to_json(),
            "compatibility": self.compatibility.to_json(),
        }
        for name in ("payload_hash", "payload_reference", "title", "notes"):
            value = getattr(self, name)
            if value is not None:
                payload[name] = value
        if self.extra:
            payload["extra"] = dict(self.extra)
        return payload

    def metadata_hash(self) -> str:
        return sha256_digest(self.to_json())
