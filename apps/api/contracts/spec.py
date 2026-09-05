# -*- coding: utf-8 -*-
"""Every API request and response shape, declared as data (WP-16).

This module is the boundary contract. It is standard library only, imports no
web framework, and holds no scientific logic: it says what a document may
contain, and nothing about what any of it means.

**Why a declaration rather than only Pydantic classes.** The same shapes are
needed in three places - the runtime validator, the OpenAPI document, and the
tests that check both - and an environment without Pydantic still has to be
able to check all three. Declaring once and deriving three times is the only
arrangement in which they cannot disagree.

**Three rules run through every model here.**

*Nothing unnamed gets in.* Every model forbids extra properties. A field this
contract does not name cannot be rendered, cannot be validated and must not be
silently dropped, because a dropped ``dose`` is invisible and a rejected one is
not.

*Nothing is unbounded.* Every string has a maximum length, every collection a
maximum size. An API whose only limit is the body-size cap has one limit, not
a contract.

*Governed values are enums, not strings.* An attention level, a coverage
status, a reason code, an operation mode and a permitted input kind each come
from ``pgx.domain``. A free string here would be a second vocabulary, and the
first one it would drift from is the one the safety invariants are written
against.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.domain.claims import OperationMode, PermittedInputKind
from pgx.domain.enums import (AttentionLevel, CoverageReasonCode,
                              CoverageStatus, Phenotype)

__all__ = [
    "CONTRACT_VERSION",
    "FieldSpec",
    "LIMITS",
    "MODELS",
    "ModelSpec",
    "PROHIBITED_REQUEST_FIELDS",
    "REQUEST_MODELS",
    "RESPONSE_MODELS",
    "model",
]

#: Bumped when a request or response shape changes in a way a client notices.
CONTRACT_VERSION = "pgx-api-contract/1"


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

#: Every bound the boundary enforces, in one place so the documentation, the
#: tests and the validator quote the same numbers.
#:
#: These are deliberately small. P0 assesses a handful of medications against a
#: handful of genes for one synthetic or protocol-defined case; a request that
#: needs a thousand of either is not a case this product was designed for, and
#: accepting it would mean the first thing to discover that is the database.
LIMITS: Mapping[str, int] = {
    "max_body_bytes": 64 * 1024,
    "max_string_length": 256,
    "max_identifier_length": 64,
    "max_reference_length": 128,
    "max_medications": 32,
    "max_observations": 64,
    "max_page_size": 100,
    "default_page_size": 25,
    # A cursor carries the release, dataset and coverage-manifest identity
    # it was produced against plus the key it stopped at, so that it can be
    # refused against any other release. Base64url of that document runs to
    # about 425 characters at the longest identifiers this contract allows;
    # 512 leaves headroom without admitting an unbounded query parameter.
    "max_cursor_length": 512,
    "max_message_length": 512,
    "max_detail_entries": 20,
    "max_collection_items": 200,
}

#: Characters no API string may contain, at any depth. C0 and C1 control
#: characters, plus the line and paragraph separators.
#:
#: Rejected rather than stripped. Stripping would make two different values
#: identical, and a value carrying an escape sequence is a value somebody
#: constructed on purpose.
CONTROL_CHARACTER_RANGES: Tuple[Tuple[int, int], ...] = (
    (0x00, 0x08), (0x0A, 0x1F), (0x7F, 0x9F), (0x2028, 0x2029))

#: Field names refused wherever they appear in a request body, at any depth,
#: with why. The value is never echoed back.
#:
#: Three groups, and they are refused for three different reasons.
#:
#: *Raw science this product does not interpret* - a genotype, a diplotype, a
#: star allele, an activity score, a variant file. Turning one of those into a
#: phenotype is a scientific act nobody here is authorised to perform.
#:
#: *Identifiable or clinical text* - a name, a date of birth, a record number,
#: notes, a narrative, a diagnosis, an indication, a dose. P0 stores no direct
#: patient identifier and calculates no dose.
#:
#: *Answers the caller is not entitled to supply* - an actor, a role, an
#: attention level, a coverage status, a finding, an evidence or rule
#: reference, any hash, any release provenance. Each of those is something the
#: system determines; accepting one from a client would let the client decide
#: what the system concluded, or who it thinks they are.
PROHIBITED_REQUEST_FIELDS: Mapping[str, str] = {
    # -- raw science ----------------------------------------------------
    "genotype": "a genotype is not a phenotype; inferring one from the other "
                "is a scientific act this system does not perform",
    "diplotype": "a diplotype requires a reviewed allele-function translation "
                 "this system does not perform",
    "star_allele": "a star allele requires the same reviewed translation a "
                   "diplotype does",
    "star_alleles": "a star allele requires the same reviewed translation a "
                    "diplotype does",
    "alleles": "allele data requires a reviewed translation to a phenotype",
    "allele": "allele data requires a reviewed translation to a phenotype",
    "activity_score": "an activity score is derived from a genotype "
                      "translation this system does not do",
    "vcf": "variant files are outside the P0 permitted input kinds",
    "vcf_path": "a path to a variant file is a variant file",
    "vcf_url": "a link to a variant file is a variant file",
    # -- identifiable or clinical text ----------------------------------
    "ehr": "electronic health record data is outside P0",
    "ehr_id": "a record identifier points into an electronic health record",
    "patient_id": "a patient identifier is identifiable data with no "
                  "calculation role here",
    "patient_name": "identifiable data has no calculation role",
    "date_of_birth": "a date of birth is identifiable data",
    "dob": "a date of birth is identifiable data",
    "mrn": "a medical record number is identifiable data",
    "clinical_notes": "clinical notes must not influence a calculation",
    "notes": "free notes must not influence a calculation",
    "narrative": "free narrative must not influence a calculation",
    "patient_narrative": "free clinical narrative must not influence a "
                         "calculation",
    "diagnosis": "this system does not diagnose",
    "indication": "an indication is a clinical judgement, not an input",
    "dose": "this system calculates no dose and accepts none",
    "dosage": "this system calculates no dosage and accepts none",
    # -- answers the caller may not supply -------------------------------
    "actor": "the actor is taken from the authenticated principal, never from "
             "the request",
    "role": "the role is taken from the authenticated principal, never from "
            "the request",
    "principal": "identity is established by the server, not asserted by the "
                 "caller",
    "attention": "attention is calculated, never supplied",
    "attention_level": "attention is calculated, never supplied",
    "overall_attention": "attention is calculated, never supplied",
    "coverage": "coverage is calculated, never supplied",
    "coverage_status": "coverage is calculated, never supplied",
    "overall_coverage": "coverage is calculated, never supplied",
    "coverage_reason_codes": "coverage reasons are calculated, never supplied",
    "findings": "a finding is calculated from a governed rule, never supplied",
    "evidence_references": "evidence is resolved from the pinned build, never "
                           "supplied",
    "rule_id": "a rule is selected by the governed ruleset, never supplied",
    "rule_version": "a rule version comes from the pinned ruleset",
    "input_hash": "hashes are computed from what was actually asked",
    "output_hash": "hashes are computed from what was actually calculated",
    "report_hash": "hashes are computed from what was actually rendered",
    "coverage_result_hash": "hashes are computed, never supplied",
    "content_hash": "hashes are computed, never supplied",
    "release_provenance": "the pinned versions are recorded by the service "
                          "that pinned them",
    "release_manifest_hash": "the pinned versions are recorded by the service",
    "ruleset_content_hash": "the pinned versions are recorded by the service",
    "dataset_public_id": "the pinned versions are recorded by the service",
    "software_version": "the pinned versions are recorded by the service",
    "active_pointer_generation": "pointer state is observed, never asserted",
}


# ---------------------------------------------------------------------------
# The declaration types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One field of one model.

    ``kind`` is a small closed vocabulary rather than a Python type, because
    two of the kinds - ``uuid`` and ``digest`` - are strings with a format this
    boundary refuses to accept without, and a bare ``str`` annotation would
    lose exactly that.
    """

    name: str
    kind: str
    required: bool = True
    nullable: bool = False
    description: str = ""
    max_length: Optional[int] = None
    min_length: Optional[int] = None
    pattern: Optional[str] = None
    enum_values: Tuple[str, ...] = ()
    minimum: Optional[int] = None
    maximum: Optional[int] = None
    min_items: Optional[int] = None
    max_items: Optional[int] = None
    item_kind: Optional[str] = None
    item_model: Optional[str] = None
    item_max_length: Optional[int] = None
    item_pattern: Optional[str] = None
    item_enum_values: Tuple[str, ...] = ()
    model: Optional[str] = None
    unique_items: bool = False

    KINDS: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError("unknown field kind %r for %s"
                             % (self.kind, self.name))
        if self.kind == "array" and not (self.item_kind or self.item_model):
            raise ValueError("array field %s names no item type" % self.name)
        if self.kind == "object" and not self.model:
            raise ValueError("object field %s names no model" % self.name)
        if self.kind == "enum" and not self.enum_values:
            raise ValueError("enum field %s lists no values" % self.name)
        if self.item_kind == "enum" and not self.item_enum_values:
            # An array of governed codes whose vocabulary is not declared is
            # worse than an array of plain strings: the validator has nothing
            # to check items against, and a generated client is told the
            # values are constrained without being told to what. Refused at
            # declaration time so the omission cannot reach either.
            raise ValueError(
                "array field %s has enum items and lists no item values"
                % self.name)


_KINDS: Tuple[str, ...] = ("string", "integer", "boolean", "enum", "uuid",
                           "digest", "object", "array")


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """One request or response document shape."""

    name: str
    description: str
    fields: Tuple[FieldSpec, ...]
    direction: str = "response"

    def __post_init__(self) -> None:
        if self.direction not in ("request", "response"):
            raise ValueError("direction is request or response")
        seen = set()
        for item in self.fields:
            if item.name in seen:
                raise ValueError("%s declares %s twice"
                                 % (self.name, item.name))
            seen.add(item.name)

    @property
    def field_names(self) -> Tuple[str, ...]:
        return tuple(item.name for item in self.fields)

    def field(self, name: str) -> FieldSpec:
        for item in self.fields:
            if item.name == name:
                return item
        raise KeyError("%s has no field %s" % (self.name, name))


def _enum(values) -> Tuple[str, ...]:
    return tuple(item.value for item in values)


_UUID_PATTERN = (r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
                 r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
_GENE_KEY_PATTERN = r"^GENE:[A-Z0-9][A-Z0-9\-.@_]{0,48}$"
_DRUG_KEY_PATTERN = r"^DRUG:[a-z0-9][a-z0-9\-.+_]{0,48}$"
_PUBLIC_ID_PATTERN = r"^PGX-[A-Z]+-[0-9]{8}-[0-9]{3}$"
_REQUEST_ID_PATTERN = _UUID_PATTERN
_SAFE_LABEL_PATTERN = r"^[^\x00-\x1f\x7f-\x9f]{1,256}$"


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

_PHENOTYPE_OBSERVATION_REQUEST = ModelSpec(
    name="PhenotypeObservationRequest",
    direction="request",
    description=(
        "One supplied gene-to-phenotype observation. The value is a phenotype "
        "token; it is normalised by the governed WP-12 normaliser, which "
        "records what it could not interpret rather than guessing."),
    fields=(
        FieldSpec("gene", "string", pattern=_GENE_KEY_PATTERN,
                  max_length=LIMITS["max_identifier_length"], min_length=6,
                  description="Canonical gene key, for example GENE:EXAMPLE1."),
        FieldSpec("value", "string", max_length=64, min_length=1,
                  description=(
                      "The supplied phenotype token. A token this contract "
                      "version does not recognise is recorded as an "
                      "uninterpretable observation, never guessed at.")),
    ))

_PHENOTYPE_PROFILE_REQUEST = ModelSpec(
    name="PhenotypeProfileRequest",
    direction="request",
    description=(
        "A phenotype profile as supplied. Carries observations only: no "
        "genotype, no variant file, no identifiable field."),
    fields=(
        FieldSpec("input_contract_version", "string",
                  max_length=LIMITS["max_identifier_length"],
                  description="The phenotype input contract this profile "
                              "claims to follow."),
        FieldSpec("profile_id", "string", required=False, nullable=True,
                  max_length=LIMITS["max_identifier_length"],
                  pattern=_SAFE_LABEL_PATTERN,
                  description="Optional label for the profile. Not part of "
                              "any hash."),
        FieldSpec("observations", "array", item_model=
                  "PhenotypeObservationRequest", min_items=1,
                  max_items=LIMITS["max_observations"],
                  description="One entry per gene. Every supplied gene "
                              "produces an observation, including one that "
                              "could not be interpreted."),
    ))

_ASSESSMENT_CREATE_REQUEST = ModelSpec(
    name="AssessmentCreateRequest",
    direction="request",
    description=(
        "One assessment question. Everything the service needs and nothing "
        "it determines for itself: no actor, no role, no hash, no release "
        "provenance and no calculated value."),
    fields=(
        FieldSpec("mode", "enum", enum_values=_enum(OperationMode),
                  description="Operation mode. Checked against the claim "
                              "boundary before anything is read."),
        FieldSpec("input_kind", "enum", enum_values=_enum(PermittedInputKind),
                  description="What kind of input this is. Checked against "
                              "the claim boundary."),
        FieldSpec("case_id", "string", required=False, nullable=True,
                  max_length=LIMITS["max_identifier_length"],
                  pattern=_SAFE_LABEL_PATTERN,
                  description="Optional label for the run. Deliberately "
                              "outside the semantic input hash."),
        FieldSpec("requested_release_public_id", "string", required=False,
                  nullable=True, pattern=_PUBLIC_ID_PATTERN, max_length=32,
                  description="Optional release to pin. It must be the "
                              "active one; naming a different release is "
                              "refused rather than honoured."),
        FieldSpec("profile", "object", model="PhenotypeProfileRequest",
                  description="The supplied phenotype profile."),
        FieldSpec("medications", "array", item_kind="string",
                  item_pattern=_DRUG_KEY_PATTERN,
                  item_max_length=LIMITS["max_identifier_length"],
                  min_items=1, max_items=LIMITS["max_medications"],
                  unique_items=True,
                  description=(
                      "Canonical drug keys. Free text is not resolved here: "
                      "turning a brand name into a canonical drug is WP-07's "
                      "work, and a medication the pinned dataset does not "
                      "contain is reported as unsupported rather than "
                      "dropped.")),
    ))

#: Vocabularies mirrored from WP-22 so the boundary rejects an out-of-list
#: value before it reaches the domain. Imported rather than retyped would be
#: better, but this module is deliberately import-light and the tests assert
#: the two lists agree.
_REVIEW_DECISIONS = ("AGREE", "PARTIAL", "DISAGREE")
_REVIEW_RATIONALE_CODES = (
    "GUIDELINE_DIRECT", "GUIDELINE_EXTRAPOLATED", "PHENOTYPE_DETERMINATIVE",
    "INSUFFICIENT_INPUT", "NO_APPLICABLE_RULE", "SOURCE_CONFLICT",
    "EVIDENCE_INSUFFICIENT", "OUT_OF_SCOPE")
_REVIEW_DIMENSIONS = ("CLARITY", "TRACEABILITY", "CLINICAL_USEFULNESS",
                      "SAFETY_FRAMING")
_REVIEW_CORRECTION_KINDS = (
    "TYPOGRAPHIC", "RATIONALE_AMENDED", "EXPECTATION_AMENDED",
    "DECISION_ANNOTATED", "RATING_ANNOTATED", "WITHDRAWN_BY_REVIEWER")

_EXPERT_EXPECTED_REQUEST = ModelSpec(
    name="ExpertReviewExpectedRequest",
    direction="request",
    description=(
        "What the reviewer expects the system to output, recorded before "
        "anything is revealed. Every field the server owns - actor, role, "
        "timestamps, status and every hash - is absent by construction: this "
        "shape has nowhere to put one, and a body carrying one is refused "
        "rather than having it stripped."),
    fields=(
        FieldSpec("expected_attention_level", "string",
                  max_length=LIMITS["max_identifier_length"],
                  pattern=_SAFE_LABEL_PATTERN,
                  description="The attention level the reviewer expects."),
        FieldSpec("expected_coverage_status", "string",
                  max_length=LIMITS["max_identifier_length"],
                  pattern=_SAFE_LABEL_PATTERN,
                  description="The coverage status the reviewer expects."),
        FieldSpec("expected_coverage_reason", "string", required=False,
                  nullable=True, max_length=LIMITS["max_identifier_length"],
                  pattern=_SAFE_LABEL_PATTERN,
                  description="Optional expected coverage reason code."),
        FieldSpec("expected_rule_id", "string", required=False, nullable=True,
                  max_length=LIMITS["max_identifier_length"],
                  pattern=_SAFE_LABEL_PATTERN,
                  description="Optional expected firing rule identifier."),
        FieldSpec("requires_traceable_evidence", "boolean", required=False,
                  description=(
                      "Whether the reviewer expects the finding to carry "
                      "resolvable evidence. Defaults to true.")),
        FieldSpec("rationale_codes", "array", required=False,
                  item_kind="enum",
                  item_enum_values=_REVIEW_RATIONALE_CODES,
                  max_items=LIMITS["max_detail_entries"], unique_items=True,
                  description=(
                      "Why the reviewer expects this. A controlled list "
                      "rather than prose, because free text in a blinded "
                      "expectation is where a dose instruction would "
                      "eventually appear.")),
        FieldSpec("reviewer_note", "string", required=False, nullable=True,
                  max_length=LIMITS["max_message_length"],
                  description=(
                      "A bounded note about the reasoning. Never a treatment "
                      "recommendation, dose or clinical directive; a body "
                      "containing one is refused.")),
    ))

_EXPERT_REVEAL_REQUEST = ModelSpec(
    name="ExpertReviewRevealRequest",
    direction="request",
    description=(
        "Reveal takes no reviewer input. The body exists so the operation has "
        "a declared shape, and it is empty because everything reveal needs - "
        "which expectation to pin, which release to read - comes from the "
        "stored assignment rather than from the caller."),
    fields=(
        FieldSpec("acknowledged", "boolean", required=False,
                  description=(
                      "Optional confirmation that the reviewer understands "
                      "the reveal is irreversible. Recorded nowhere; the "
                      "irreversibility does not depend on it.")),
    ))

_EXPERT_RATING_REQUEST = ModelSpec(
    name="ExpertReviewRatingRequest",
    direction="request",
    description="One optional Likert rating on one declared dimension.",
    fields=(
        FieldSpec("dimension", "enum", enum_values=_REVIEW_DIMENSIONS,
                  description="A dimension declared before any review "
                              "existed."),
        FieldSpec("value", "integer", minimum=1, maximum=5,
                  description="1 to 5 inclusive."),
    ))

_EXPERT_COMPLETE_REQUEST = ModelSpec(
    name="ExpertReviewCompleteRequest",
    direction="request",
    description=(
        "The post-reveal comparison. Exactly one decision from three, plus "
        "optional structured ratings. This is not the expected response and "
        "cannot be used as one."),
    fields=(
        FieldSpec("decision", "enum", enum_values=_REVIEW_DECISIONS,
                  description=(
                      "AGREE, PARTIAL or DISAGREE. PARTIAL is a third "
                      "answer, not a midpoint; these are never ordered or "
                      "averaged.")),
        FieldSpec("ratings", "array", required=False,
                  item_model="ExpertReviewRatingRequest",
                  max_items=len(_REVIEW_DIMENSIONS),
                  description="Optional ratings, at most one per dimension."),
        FieldSpec("reviewer_note", "string", required=False, nullable=True,
                  max_length=LIMITS["max_message_length"],
                  description="Bounded note explaining the decision."),
    ))

_EXPERT_REPLACEMENT_REQUEST = ModelSpec(
    name="ExpertReviewReplacementRequest",
    direction="request",
    description=(
        "The governed fields a correction may replace. Exactly the expected "
        "response's structured fields and nothing else - a correction cannot "
        "introduce a field the original record could not have held."),
    fields=(
        FieldSpec("expected_attention_level", "string", required=False,
                  nullable=True, max_length=LIMITS["max_identifier_length"],
                  pattern=_SAFE_LABEL_PATTERN),
        FieldSpec("expected_coverage_status", "string", required=False,
                  nullable=True, max_length=LIMITS["max_identifier_length"],
                  pattern=_SAFE_LABEL_PATTERN),
        FieldSpec("expected_coverage_reason", "string", required=False,
                  nullable=True, max_length=LIMITS["max_identifier_length"],
                  pattern=_SAFE_LABEL_PATTERN),
        FieldSpec("expected_rule_id", "string", required=False, nullable=True,
                  max_length=LIMITS["max_identifier_length"],
                  pattern=_SAFE_LABEL_PATTERN),
        FieldSpec("requires_traceable_evidence", "boolean", required=False,
                  nullable=True),
        FieldSpec("rationale_codes", "array", required=False,
                  item_kind="enum",
                  item_enum_values=_REVIEW_RATIONALE_CODES,
                  max_items=LIMITS["max_detail_entries"], unique_items=True),
        FieldSpec("reviewer_note", "string", required=False, nullable=True,
                  max_length=LIMITS["max_message_length"]),
    ))

_EXPERT_CORRECTION_REQUEST = ModelSpec(
    name="ExpertReviewCorrectionRequest",
    direction="request",
    description=(
        "An appended amendment. The record it refers to is never touched, "
        "and a correction appended after a reveal is annotation only."),
    fields=(
        FieldSpec("target_hash", "digest",
                  description="The hash of the record being corrected."),
        FieldSpec("kind", "enum", enum_values=_REVIEW_CORRECTION_KINDS,
                  description="What kind of amendment this is."),
        FieldSpec("reason_code", "string",
                  max_length=LIMITS["max_identifier_length"],
                  pattern=_SAFE_LABEL_PATTERN,
                  description="Why the amendment was made."),
        FieldSpec("replacement", "object", required=False, nullable=True,
                  model="ExpertReviewReplacementRequest",
                  description=(
                      "The replacement value, where the kind carries one. A "
                      "declared shape rather than an open object: an open "
                      "one would be the hole through which a treatment "
                      "recommendation eventually arrives.")),
    ))


# ---------------------------------------------------------------------------
# Shared response models
# ---------------------------------------------------------------------------

_ERROR_BODY = ModelSpec(
    name="ErrorBody",
    description="The one error shape this API returns.",
    fields=(
        FieldSpec("code", "string", max_length=LIMITS["max_identifier_length"],
                  description="Stable machine-readable code."),
        FieldSpec("message", "string",
                  max_length=LIMITS["max_message_length"],
                  description=(
                      "Controlled message from a fixed catalogue. Never the "
                      "text of an unexpected exception.")),
        FieldSpec("details", "object", model="ErrorDetails",
                  description="Bounded machine-readable metadata."),
        FieldSpec("request_id", "uuid",
                  description="The same identifier the response header "
                              "carries."),
    ))

_ERROR_DETAILS = ModelSpec(
    name="ErrorDetails",
    description=(
        "Bounded safe metadata about a failure. Carries locations and codes; "
        "never a rejected value, a phenotype, a medication list, a path, a "
        "query or a stack frame."),
    fields=(
        FieldSpec("issues", "array", required=False,
                  item_model="ErrorIssue",
                  max_items=LIMITS["max_detail_entries"],
                  description="One entry per contract violation."),
        FieldSpec("components", "array", required=False, item_kind="string",
                  item_max_length=LIMITS["max_identifier_length"],
                  max_items=LIMITS["max_detail_entries"],
                  description="Named components that were not ready."),
        FieldSpec("required_role", "enum", required=False, nullable=True,
                  enum_values=("DEMO_USER", "EXPERT_REVIEWER", "ADMIN"),
                  description="The role a forbidden request would have "
                              "needed."),
        FieldSpec("work_package", "string", required=False, nullable=True,
                  max_length=LIMITS["max_identifier_length"],
                  description="The work package that will implement a "
                              "not-implemented route."),
        FieldSpec("limit", "integer", required=False, nullable=True,
                  minimum=0, maximum=1000000,
                  description="The bound a request exceeded."),
    ))

_ERROR_ISSUE = ModelSpec(
    name="ErrorIssue",
    description=(
        "One contract violation. ``location`` is a normalised JSON pointer "
        "and ``code`` is stable; neither the supplied value nor any text "
        "derived from it appears."),
    fields=(
        FieldSpec("location", "string",
                  max_length=LIMITS["max_reference_length"],
                  description="Normalised JSON pointer, for example "
                              "$.profile.observations[0].value."),
        FieldSpec("code", "string", max_length=LIMITS["max_identifier_length"],
                  description="Stable violation code."),
    ))

_ERROR_ENVELOPE = ModelSpec(
    name="ErrorEnvelope",
    description="Every failure response, for every status, has this shape.",
    fields=(
        FieldSpec("error", "object", model="ErrorBody",
                  description="The failure."),
    ))

_RELEASE_PROVENANCE = ModelSpec(
    name="ReleaseProvenanceResponse",
    description=(
        "Every version the assessment executed against, by identity and "
        "content hash (SAFETY-INV-007). Complete, or the assessment was not "
        "persistable."),
    fields=(
        FieldSpec("release_public_id", "string", max_length=32),
        FieldSpec("release_manifest_hash", "digest"),
        FieldSpec("software_version", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("software_source_tree_hash", "digest"),
        FieldSpec("dataset_public_id", "string", max_length=32),
        FieldSpec("canonical_build_content_hash", "digest"),
        FieldSpec("ruleset_public_id", "string", max_length=32),
        FieldSpec("ruleset_content_hash", "digest"),
        FieldSpec("evidence_build_key", "string",
                  max_length=LIMITS["max_reference_length"]),
        FieldSpec("evidence_build_content_hash", "digest"),
        FieldSpec("coverage_manifest_hash", "digest"),
        FieldSpec("protocol_version", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("protocol_content_hash", "digest"),
        FieldSpec("source_policy_version", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("source_policy_content_hash", "digest"),
    ))

_STATUS_BLOCK = ModelSpec(
    name="StatusBlock",
    description=(
        "Attention and coverage together, always. One object rather than two "
        "sibling fields, so no serialisation of this contract can carry one "
        "without the other (SAFETY-INV-001). NOT_ASSESSED is emitted "
        "verbatim; it is never mapped to LOW, to safe, or to an absence of "
        "warning."),
    fields=(
        FieldSpec("attention", "enum", enum_values=_enum(AttentionLevel),
                  description="Calculated attention level."),
        FieldSpec("coverage", "enum", enum_values=_enum(CoverageStatus),
                  description="Calculated coverage status."),
        FieldSpec("coverage_reason_codes", "array", item_kind="enum",
                  item_enum_values=_enum(CoverageReasonCode),
                  max_items=LIMITS["max_collection_items"],
                  description=(
                      "Machine-readable reasons. Empty only when coverage is "
                      "FULL; unexplained absence is how absence becomes "
                      "reassurance.")),
    ))


# ---------------------------------------------------------------------------
# Assessment response models
# ---------------------------------------------------------------------------

_FINDING_RESULT = ModelSpec(
    name="FindingResponse",
    description=(
        "One calculated finding with its whole traceability chain. "
        "``effect_code`` and ``explanation_code`` are null wherever the "
        "governed ruleset carries none, and no text is authored to stand in "
        "for them."),
    fields=(
        FieldSpec("gene", "string", pattern=_GENE_KEY_PATTERN,
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("drug", "string", pattern=_DRUG_KEY_PATTERN,
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("phenotype", "enum", enum_values=_enum(Phenotype)),
        FieldSpec("attention", "enum",
                  enum_values=("NO_ACTIVE_ATTENTION", "LOW", "MEDIUM",
                               "HIGH")),
        FieldSpec("rule_id", "uuid"),
        FieldSpec("rule_family_id", "string",
                  max_length=LIMITS["max_reference_length"]),
        FieldSpec("rule_version", "integer", minimum=1, maximum=1000000),
        FieldSpec("rule_content_hash", "digest"),
        FieldSpec("rationale_reference", "string",
                  max_length=LIMITS["max_reference_length"]),
        FieldSpec("curation_revision_id", "string",
                  max_length=LIMITS["max_reference_length"]),
        FieldSpec("curation_revision_hash", "digest"),
        FieldSpec("effect_code", "string", nullable=True,
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("explanation_code", "string", nullable=True,
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("evidence_references", "array", item_kind="uuid",
                  min_items=1, max_items=LIMITS["max_collection_items"]),
    ))

_AXIS_RESULT = ModelSpec(
    name="AxisResponse",
    description=(
        "One drug-gene axis as coverage reported it. Present whether or not "
        "it could be evaluated: an axis dropped for being uncovered would "
        "make a partial assessment look complete."),
    fields=(
        FieldSpec("gene", "string", pattern=_GENE_KEY_PATTERN,
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("drug", "string", pattern=_DRUG_KEY_PATTERN,
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("coverage", "enum", enum_values=_enum(CoverageStatus)),
        FieldSpec("coverage_reason_codes", "array", item_kind="enum",
                  item_enum_values=_enum(CoverageReasonCode),
                  max_items=LIMITS["max_collection_items"]),
        FieldSpec("observed_phenotype", "enum", nullable=True,
                  enum_values=_enum(Phenotype)),
        FieldSpec("observation_state", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("declaration_id", "string", nullable=True,
                  max_length=LIMITS["max_reference_length"]),
        FieldSpec("evidence_references", "array", item_kind="uuid",
                  max_items=LIMITS["max_collection_items"]),
        FieldSpec("conflict_references", "array", item_kind="string",
                  item_max_length=LIMITS["max_reference_length"],
                  max_items=LIMITS["max_collection_items"],
                  description="Unresolved source conflicts, preserved and "
                              "never adjudicated (SAFETY-INV-008)."),
    ))

_MEDICATION_RESULT = ModelSpec(
    name="MedicationResponse",
    description="Everything the assessment recorded about one medication.",
    fields=(
        FieldSpec("drug", "string", pattern=_DRUG_KEY_PATTERN,
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("requested_value", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("status", "object", model="StatusBlock"),
        FieldSpec("axis_count", "integer", minimum=0, maximum=1000000),
        FieldSpec("conflicted_axis_count", "integer", minimum=0,
                  maximum=1000000),
        FieldSpec("axes", "array", item_model="AxisResponse",
                  max_items=LIMITS["max_collection_items"]),
        FieldSpec("findings", "array", item_model="FindingResponse",
                  max_items=LIMITS["max_collection_items"]),
    ))

_OBSERVATION_RESULT = ModelSpec(
    name="ObservationResponse",
    description=(
        "One normalised phenotype observation as stored. Carries the verdict "
        "and never the raw supplied value."),
    fields=(
        FieldSpec("gene", "string", pattern=_GENE_KEY_PATTERN,
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("status", "enum",
                  enum_values=("NORMALIZED", "MISSING", "INDETERMINATE",
                               "UNSUPPORTED")),
        FieldSpec("phenotype", "enum", nullable=True,
                  enum_values=_enum(Phenotype)),
        FieldSpec("reason_code", "string", nullable=True,
                  max_length=LIMITS["max_identifier_length"]),
    ))

_ASSESSMENT_RESPONSE = ModelSpec(
    name="AssessmentResponse",
    description=(
        "One immutable assessment, exactly as it was calculated and stored. "
        "Nothing here is recomputed at serialisation time, and the canonical "
        "warning is imported from the claim boundary rather than written "
        "here."),
    fields=(
        FieldSpec("contract_version", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("assessment_id", "uuid"),
        FieldSpec("mode", "enum", enum_values=_enum(OperationMode)),
        FieldSpec("input_kind", "enum",
                  enum_values=_enum(PermittedInputKind)),
        FieldSpec("case_id", "string", nullable=True,
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("created_at", "string", nullable=True, max_length=40,
                  description="UTC instant the run was recorded. Excluded "
                              "from every hash."),
        FieldSpec("input_hash", "digest"),
        FieldSpec("output_hash", "digest"),
        FieldSpec("coverage_result_hash", "digest"),
        FieldSpec("status", "object", model="StatusBlock"),
        FieldSpec("medications", "array", item_model="MedicationResponse",
                  min_items=1, max_items=LIMITS["max_medications"]),
        FieldSpec("observations", "array", item_model="ObservationResponse",
                  max_items=LIMITS["max_observations"]),
        FieldSpec("release", "object", model="ReleaseProvenanceResponse"),
        FieldSpec("warnings", "array", item_kind="string",
                  item_max_length=LIMITS["max_message_length"],
                  max_items=LIMITS["max_detail_entries"]),
        FieldSpec("clinical_warning", "string", max_length=2048,
                  description=(
                      "The canonical clinical warning, imported verbatim "
                      "from pgx.domain.claims. Never written here and never "
                      "paraphrased.")),
        FieldSpec("persisted", "boolean",
                  description="True only when a transaction committed."),
    ))


# ---------------------------------------------------------------------------
# Catalogue, evidence and version response models
# ---------------------------------------------------------------------------

_PAGE_INFO = ModelSpec(
    name="PageInfo",
    description=(
        "Deterministic cursor pagination. The cursor is bound to the release "
        "and dataset it was created for; one made for another release is "
        "refused rather than silently applied to a different catalogue."),
    fields=(
        FieldSpec("page_size", "integer", minimum=1,
                  maximum=LIMITS["max_page_size"]),
        FieldSpec("returned", "integer", minimum=0,
                  maximum=LIMITS["max_page_size"]),
        FieldSpec("total", "integer", minimum=0, maximum=1000000),
        FieldSpec("next_cursor", "string", nullable=True,
                  max_length=LIMITS["max_cursor_length"]),
    ))

_DRUG_SUMMARY = ModelSpec(
    name="DrugSummary",
    description=(
        "One canonical drug and what the governed coverage manifest declares "
        "about it. Carries no safety statement, no suitability, no score and "
        "no ordering by attention."),
    fields=(
        FieldSpec("drug", "string", pattern=_DRUG_KEY_PATTERN,
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("display_name", "string",
                  max_length=LIMITS["max_string_length"]),
        FieldSpec("aliases", "array", item_kind="string",
                  item_max_length=LIMITS["max_string_length"],
                  max_items=LIMITS["max_detail_entries"]),
        FieldSpec("declared", "boolean",
                  description="Whether the coverage manifest declares a "
                              "scope for this drug."),
        FieldSpec("declaration_id", "string", nullable=True,
                  max_length=LIMITS["max_reference_length"]),
        FieldSpec("expected_gene_keys", "array", item_kind="string",
                  item_pattern=_GENE_KEY_PATTERN,
                  item_max_length=LIMITS["max_identifier_length"],
                  max_items=LIMITS["max_collection_items"],
                  description="Genes a complete assessment of this drug "
                              "would have to consider."),
        FieldSpec("supported_axis_count", "integer", minimum=0,
                  maximum=1000000),
        FieldSpec("verified_axis_count", "integer", minimum=0,
                  maximum=1000000,
                  description="Axes whose declared rule and evidence were "
                              "checked against the frozen artifact."),
    ))

_DRUG_COLLECTION = ModelSpec(
    name="DrugCollectionResponse",
    description="A bounded, deterministically ordered page of canonical drugs.",
    fields=(
        FieldSpec("contract_version", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("release", "object", model="CatalogueContext"),
        FieldSpec("page", "object", model="PageInfo"),
        FieldSpec("items", "array", item_model="DrugSummary",
                  max_items=LIMITS["max_page_size"]),
    ))

_GENE_SUMMARY = ModelSpec(
    name="GeneSummary",
    description=(
        "One canonical gene and the phenotypes the governed manifest "
        "declares axes for. Listing a gene is not a claim that it is fully "
        "covered; the declared axes are what says how much of it is."),
    fields=(
        FieldSpec("gene", "string", pattern=_GENE_KEY_PATTERN,
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("display_name", "string",
                  max_length=LIMITS["max_string_length"]),
        FieldSpec("supported_phenotypes", "array", item_kind="enum",
                  item_enum_values=_enum(Phenotype),
                  max_items=LIMITS["max_detail_entries"],
                  description="Phenotypes a governed rule is declared for."),
        FieldSpec("expected_for_drugs", "array", item_kind="string",
                  item_pattern=_DRUG_KEY_PATTERN,
                  item_max_length=LIMITS["max_identifier_length"],
                  max_items=LIMITS["max_collection_items"],
                  description="Drugs whose declared scope includes this "
                              "gene."),
        FieldSpec("supported_axis_count", "integer", minimum=0,
                  maximum=1000000),
        FieldSpec("fully_declared", "boolean",
                  description=(
                      "True only when every drug expecting this gene also "
                      "declares at least one supported axis for it. False is "
                      "the honest answer whenever the manifest is silent.")),
    ))

_GENE_COLLECTION = ModelSpec(
    name="GeneCollectionResponse",
    description="Governed canonical genes and their declared phenotype scope.",
    fields=(
        FieldSpec("contract_version", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("release", "object", model="CatalogueContext"),
        FieldSpec("page", "object", model="PageInfo"),
        FieldSpec("items", "array", item_model="GeneSummary",
                  max_items=LIMITS["max_page_size"]),
        FieldSpec("phenotype_vocabulary", "array", item_kind="enum",
                  item_enum_values=_enum(Phenotype),
                  max_items=LIMITS["max_detail_entries"],
                  description="The governed phenotype vocabulary in force."),
    ))

_CATALOGUE_CONTEXT = ModelSpec(
    name="CatalogueContext",
    description=(
        "The release, dataset and manifest a catalogue page was read from. "
        "A cursor is only valid inside one of these."),
    fields=(
        FieldSpec("release_public_id", "string", max_length=32),
        FieldSpec("dataset_public_id", "string", max_length=32),
        FieldSpec("ruleset_public_id", "string", max_length=32),
        FieldSpec("coverage_manifest_hash", "digest"),
    ))

_EVIDENCE_LINK = ModelSpec(
    name="EvidenceEntityLink",
    description="One canonical entity this evidence record is linked to.",
    fields=(
        FieldSpec("entity_type", "enum", enum_values=("GENE", "DRUG")),
        FieldSpec("canonical_key", "string", nullable=True,
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("source_label", "string", nullable=True,
                  max_length=LIMITS["max_string_length"]),
    ))

_EVIDENCE_RECORD_TYPE_MAPPING = ModelSpec(
    name="EvidenceRecordTypeMapping",
    description=(
        "How the source's own record type became a canonical one. "
        "Identifiers and a status; the curation rationale behind the mapping "
        "is prose and is not published here."),
    fields=(
        FieldSpec("record_type", "string", nullable=True,
                  max_length=LIMITS["max_identifier_length"],
                  description="The canonical record type."),
        FieldSpec("status", "string", nullable=True,
                  max_length=LIMITS["max_identifier_length"],
                  description="CONFIRMED, PENDING_REVIEW or another governed "
                              "mapping status."),
        FieldSpec("map_version", "string", nullable=True,
                  max_length=LIMITS["max_identifier_length"],
                  description="The version of the mapping rules that produced "
                              "this."),
        FieldSpec("production_eligible", "boolean",
                  description="Whether this mapping permits the record to "
                              "support production evidence."),
    ))

_EVIDENCE_PUBLICATION = ModelSpec(
    name="EvidencePublicationReference",
    description="A publication identifier the source cited.",
    fields=(
        FieldSpec("identifier_type", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("identifier", "string",
                  max_length=LIMITS["max_reference_length"]),
    ))

_EVIDENCE_LOCATOR = ModelSpec(
    name="EvidenceLocator",
    description=(
        "Where this record came from inside the sealed snapshot, by artifact "
        "identity and digest. No filesystem path leaves the server."),
    fields=(
        FieldSpec("snapshot_id", "string", nullable=True,
                  max_length=LIMITS["max_reference_length"]),
        FieldSpec("artifact_id", "string", nullable=True,
                  max_length=LIMITS["max_reference_length"]),
        FieldSpec("artifact_digest", "string", nullable=True,
                  max_length=LIMITS["max_reference_length"]),
        FieldSpec("json_pointer", "string", nullable=True,
                  max_length=LIMITS["max_reference_length"]),
    ))

_EVIDENCE_RESPONSE = ModelSpec(
    name="EvidenceDetailResponse",
    description=(
        "One evidence record's identity and provenance chain. Deliberately "
        "carries no source prose, no summary this system authored, and no "
        "clinical advice: it says where a fact came from, not what to do "
        "about it."),
    fields=(
        FieldSpec("contract_version", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("record_uuid", "uuid"),
        FieldSpec("natural_key", "string",
                  max_length=LIMITS["max_reference_length"]),
        FieldSpec("record_type", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("provider_source_key", "string", nullable=True,
                  max_length=LIMITS["max_reference_length"]),
        FieldSpec("origin_source_key", "string", nullable=True,
                  max_length=LIMITS["max_reference_length"]),
        FieldSpec("origin_status", "string", nullable=True,
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("version_status", "string", nullable=True,
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("version_value", "string", nullable=True,
                  max_length=LIMITS["max_reference_length"]),
        FieldSpec("source_payload_hash", "string", nullable=True,
                  max_length=LIMITS["max_reference_length"]),
        FieldSpec("content_hash", "string", nullable=True,
                  max_length=LIMITS["max_reference_length"]),
        FieldSpec("production_eligible", "boolean"),
        FieldSpec("evidence_build_key", "string",
                  max_length=LIMITS["max_reference_length"]),
        FieldSpec("evidence_build_content_hash", "string", nullable=True,
                  max_length=LIMITS["max_reference_length"]),
        FieldSpec("genes", "array", item_model="EvidenceEntityLink",
                  max_items=LIMITS["max_collection_items"]),
        FieldSpec("drugs", "array", item_model="EvidenceEntityLink",
                  max_items=LIMITS["max_collection_items"]),
        FieldSpec("publications", "array",
                  item_model="EvidencePublicationReference",
                  max_items=LIMITS["max_collection_items"]),
        FieldSpec("locators", "array", item_model="EvidenceLocator",
                  max_items=LIMITS["max_collection_items"]),
        FieldSpec("record_type_mapping", "object", nullable=True,
                  model="EvidenceRecordTypeMapping",
                  description="The raw-to-canonical record-type step of the "
                              "provenance trace."),
        FieldSpec("text_fragment_count", "integer", minimum=0,
                  maximum=1000000,
                  description=(
                      "How many source text fragments the record carries. "
                      "The fragments themselves are source prose and are not "
                      "served.")),
    ))

_SYSTEM_VERSION = ModelSpec(
    name="SystemVersionResponse",
    description=(
        "The active release pointer and the exact version set it names, read "
        "once. Fields are never combined from two releases."),
    fields=(
        FieldSpec("contract_version", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("api_version", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("release_public_id", "string", max_length=32),
        FieldSpec("release_manifest_hash", "digest"),
        FieldSpec("active_pointer_generation", "integer", minimum=0,
                  maximum=1000000),
        FieldSpec("software_version", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("software_source_tree_hash", "digest"),
        FieldSpec("dataset_public_id", "string", max_length=32),
        FieldSpec("canonical_build_content_hash", "digest"),
        FieldSpec("ruleset_public_id", "string", max_length=32),
        FieldSpec("ruleset_content_hash", "digest"),
        FieldSpec("evidence_build_key", "string",
                  max_length=LIMITS["max_reference_length"]),
        FieldSpec("evidence_build_content_hash", "digest"),
        FieldSpec("coverage_manifest_hash", "digest"),
        FieldSpec("protocol_version", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("source_policy_version", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("claim_boundary_phase", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("claim_boundary_approved", "boolean"),
    ))


# ---------------------------------------------------------------------------
# Health response models
# ---------------------------------------------------------------------------

_LIVENESS = ModelSpec(
    name="LivenessResponse",
    description=(
        "Process liveness only. Makes no claim it did not verify: there is "
        "no version, no release and no dependency here, because checking any "
        "of them would make liveness fail for a reason liveness is not "
        "about."),
    fields=(
        FieldSpec("status", "enum", enum_values=("LIVE",)),
    ))

_COMPONENT_STATUS = ModelSpec(
    name="ComponentStatus",
    description=(
        "One readiness component. ``detail`` is a controlled phrase from a "
        "fixed catalogue - never an exception message, a DSN, a path or a "
        "stack frame."),
    fields=(
        FieldSpec("component", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("ready", "boolean"),
        FieldSpec("blocking", "boolean",
                  description="Whether this component blocks readiness."),
        FieldSpec("detail", "string",
                  max_length=LIMITS["max_message_length"]),
    ))

_READINESS = ModelSpec(
    name="ReadinessResponse",
    description=(
        "Bounded per-component readiness. External ClinPGx and language-model "
        "availability are absent by construction: neither is a P0 dependency, "
        "and letting either affect this would make an outage elsewhere look "
        "like an outage here."),
    fields=(
        FieldSpec("status", "enum", enum_values=("READY", "NOT_READY")),
        FieldSpec("components", "array", item_model="ComponentStatus",
                  max_items=LIMITS["max_detail_entries"]),
        FieldSpec("blocking_failures", "array", item_kind="string",
                  item_max_length=LIMITS["max_identifier_length"],
                  max_items=LIMITS["max_detail_entries"]),
    ))


REQUEST_MODELS: Tuple[ModelSpec, ...] = (
    _ASSESSMENT_CREATE_REQUEST,
    _PHENOTYPE_PROFILE_REQUEST,
    _PHENOTYPE_OBSERVATION_REQUEST,
    # WP-22 replaced the single stub shape with the four real ones. The stub
    # is gone rather than kept beside them: a declared shape nobody sends is
    # a surface somebody eventually implements against.
    _EXPERT_EXPECTED_REQUEST,
    _EXPERT_REVEAL_REQUEST,
    _EXPERT_RATING_REQUEST,
    _EXPERT_COMPLETE_REQUEST,
    _EXPERT_REPLACEMENT_REQUEST,
    _EXPERT_CORRECTION_REQUEST,
)

_EXPERT_REVIEW_STATE = ModelSpec(
    name="ExpertReviewStateResponse",
    description=(
        "The reviewer's own view of their assignment while blinded. There is "
        "no result field in this shape - not an optional one, not a nullable "
        "one. A hidden value is still disclosure, so the pre-reveal response "
        "has nowhere to put one."),
    fields=(
        FieldSpec("review_id", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("assignment_id", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("case_id", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("state", "string",
                  max_length=LIMITS["max_identifier_length"],
                  description="ASSIGNED, EXPECTATION_RECORDED, "
                              "RESULT_REVEALED, COMPLETED or INVALIDATED."),
        FieldSpec("blinded", "boolean",
                  description="True until a reveal record exists."),
        FieldSpec("release_public_id", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("protocol_version", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("expectation_recorded", "boolean"),
        FieldSpec("expectation_revision", "integer", required=False,
                  nullable=True, minimum=1),
        FieldSpec("expectation_revision_hash", "string", required=False,
                  nullable=True, max_length=LIMITS["max_identifier_length"]),
        FieldSpec("correction_count", "integer", minimum=0),
    ))

_EXPERT_REVIEW_RESULT = ModelSpec(
    name="ExpertReviewResultBlock",
    description=(
        "The deterministic system result. Present only in a reveal response "
        "and in a post-reveal state response."),
    fields=(
        FieldSpec("attention_level", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("coverage_status", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("coverage_reason", "string", required=False, nullable=True,
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("firing_rule_id", "string", required=False, nullable=True,
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("finding_count", "integer", minimum=0),
        FieldSpec("traceable_finding_count", "integer", minimum=0),
        FieldSpec("output_hash", "digest"),
    ))

_EXPERT_EXPECTED_RESPONSE = ModelSpec(
    name="ExpertReviewExpectedResponse",
    description=(
        "The receipt for a locked expectation. Carries the revision hash a "
        "later reveal will pin, and the server-generated timestamp - so a "
        "reviewer can verify what was recorded without being able to have "
        "chosen it."),
    fields=(
        FieldSpec("review_id", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("revision_id", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("revision", "integer", minimum=1),
        FieldSpec("recorded_at", "string",
                  max_length=LIMITS["max_identifier_length"],
                  description="Server-generated UTC timestamp."),
        FieldSpec("content_hash", "digest"),
        FieldSpec("revision_hash", "digest"),
        FieldSpec("state", "string",
                  max_length=LIMITS["max_identifier_length"]),
    ))

_EXPERT_REVEAL_RESPONSE = ModelSpec(
    name="ExpertReviewRevealResponse",
    description=(
        "The one-way door, and what it pinned. The expectation revision hash "
        "here is the reference every downstream metric consumes; a later "
        "correction cannot move it."),
    fields=(
        FieldSpec("review_id", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("reveal_id", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("expectation_revision_id", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("expectation_revision_hash", "digest"),
        FieldSpec("revealed_at", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("reveal_hash", "digest"),
        FieldSpec("state", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("result", "object", model="ExpertReviewResultBlock"),
    ))

_EXPERT_COMPLETE_RESPONSE = ModelSpec(
    name="ExpertReviewCompleteResponse",
    description="The immutable completion record.",
    fields=(
        FieldSpec("review_id", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("completion_id", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("decision", "enum", enum_values=_REVIEW_DECISIONS),
        FieldSpec("rated_dimensions", "array", item_kind="string",
                  item_max_length=LIMITS["max_identifier_length"],
                  max_items=len(_REVIEW_DIMENSIONS),
                  description=(
                      "Which dimensions were rated. The values themselves "
                      "belong to the reviewer's record, not to a receipt.")),
        FieldSpec("completed_at", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("completion_hash", "digest"),
        FieldSpec("state", "string",
                  max_length=LIMITS["max_identifier_length"]),
    ))

_EXPERT_CORRECTION_RESPONSE = ModelSpec(
    name="ExpertReviewCorrectionResponse",
    description="The appended amendment's receipt.",
    fields=(
        FieldSpec("review_id", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("correction_id", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("kind", "enum", enum_values=_REVIEW_CORRECTION_KINDS),
        FieldSpec("after_reveal", "boolean",
                  description=(
                      "True when this correction is annotation only and "
                      "cannot change the reference a metric consumes.")),
        FieldSpec("recorded_at", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("correction_hash", "digest"),
    ))

_EXPERT_ASSIGNMENT_SUMMARY = ModelSpec(
    name="ExpertReviewAssignmentSummary",
    description="One of the calling reviewer's own assignments.",
    fields=(
        FieldSpec("review_id", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("case_id", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("state", "string",
                  max_length=LIMITS["max_identifier_length"]),
        FieldSpec("blinded", "boolean"),
        FieldSpec("release_public_id", "string",
                  max_length=LIMITS["max_identifier_length"]),
    ))

_EXPERT_ASSIGNMENT_LIST = ModelSpec(
    name="ExpertReviewAssignmentListResponse",
    description=(
        "The calling reviewer's assignments and nobody else's. A reviewer who "
        "could list another's would learn which cases exist and who holds "
        "them."),
    fields=(
        FieldSpec("assignments", "array",
                  item_model="ExpertReviewAssignmentSummary",
                  max_items=LIMITS["max_detail_entries"]),
        FieldSpec("count", "integer", minimum=0),
    ))


RESPONSE_MODELS: Tuple[ModelSpec, ...] = (
    _EXPERT_REVIEW_RESULT,
    _EXPERT_REVIEW_STATE,
    _EXPERT_EXPECTED_RESPONSE,
    _EXPERT_REVEAL_RESPONSE,
    _EXPERT_COMPLETE_RESPONSE,
    _EXPERT_CORRECTION_RESPONSE,
    _EXPERT_ASSIGNMENT_SUMMARY,
    _EXPERT_ASSIGNMENT_LIST,
    _ASSESSMENT_RESPONSE,
    _MEDICATION_RESULT,
    _AXIS_RESULT,
    _FINDING_RESULT,
    _OBSERVATION_RESULT,
    _STATUS_BLOCK,
    _RELEASE_PROVENANCE,
    _DRUG_COLLECTION,
    _DRUG_SUMMARY,
    _GENE_COLLECTION,
    _GENE_SUMMARY,
    _CATALOGUE_CONTEXT,
    _PAGE_INFO,
    _EVIDENCE_RESPONSE,
    _EVIDENCE_LINK,
    _EVIDENCE_RECORD_TYPE_MAPPING,
    _EVIDENCE_PUBLICATION,
    _EVIDENCE_LOCATOR,
    _SYSTEM_VERSION,
    _LIVENESS,
    _READINESS,
    _COMPONENT_STATUS,
    _ERROR_ENVELOPE,
    _ERROR_BODY,
    _ERROR_DETAILS,
    _ERROR_ISSUE,
)

MODELS: Mapping[str, ModelSpec] = {
    item.name: item for item in REQUEST_MODELS + RESPONSE_MODELS}


def model(name: str) -> ModelSpec:
    """One declared model, or a stated failure.

    Raises ``KeyError`` rather than returning ``None``: a caller asking for a
    model that does not exist has a bug, and handing back ``None`` would turn
    it into a missing response field three frames away.
    """
    return MODELS[name]
