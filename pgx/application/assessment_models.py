# -*- coding: utf-8 -*-
"""The assessment input contract and the pinned release context (WP-14).

Two immutable values, and the difference between them is the whole shape of
the work package: :class:`AssessmentInput` is *what was asked*, and
:class:`PinnedAssessmentRelease` is *what it was asked of*. Both are frozen
before calculation begins, and neither can be influenced by the caller after.

**The input hash covers the question, not the asking.** It excludes the
assessment id, the actor, the request time, the process, the source path, any
UI metadata, and the order the caller happened to list things in. Two people
asking the same question about the same phenotypes get the same hash, which is
what makes "same input, same release, different answer" a detectable event
rather than a matter of opinion.

**``case_id`` is deliberately outside the semantic hash.** A case identifier
labels a run; it is not part of what was asked. Two runs of the same
phenotypes and medications under different case ids are the same question, and
if the identifier entered the hash they would look like different ones - which
would destroy exactly the comparison the hash exists to support. The case id is
still recorded, persisted and returned; it simply is not part of the question.
A test asserts this decision rather than leaving it to be rediscovered.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from pgx.domain.claims import (DEFAULT_CLAIM_BOUNDARY, ClaimBoundary,
                               OperationMode, PermittedInputKind)
from pgx.domain.hashing import sha256_digest
from pgx.domain.identifiers import DrugId, GeneId
from pgx.domain.immutable import freeze_json
from pgx.engine.risk_errors import (AssessmentArtifactError,
                                    AssessmentInputError)

__all__ = [
    "ASSESSMENT_INPUT_SCHEMA_VERSION",
    "AssessmentInput",
    "CanonicalEntityIndex",
    "PinnedAssessmentRelease",
    "REFUSED_INPUT_FIELDS",
    "build_assessment_input",
]

ASSESSMENT_INPUT_SCHEMA_VERSION = "pgx-assessment-input/1"

#: The closed vocabulary of care settings a request may declare.
#:
#: Closed, and short, because each member has to correspond to a column of a
#: guideline table this project actually transcribed. A free-text field here
#: would be a place for a diagnosis to arrive under another name.
PERMITTED_CARE_SETTINGS: Tuple[str, ...] = ("ACS_OR_PCI",)

#: Fields whose presence refuses the whole input, with why. Each names a kind
#: of data this product does not accept in P0: interpreting a genotype is a
#: scientific act nobody here is authorised to perform, and a clinical
#: narrative is both outside the intended purpose and a disclosure risk.
REFUSED_INPUT_FIELDS: Mapping[str, str] = {
    "genotype": "a genotype is not a phenotype; inferring one from the other "
                "is a scientific act this system does not perform",
    "diplotype": "a diplotype requires an allele-function table and a "
                 "reviewed translation, neither of which exists here",
    "star_allele": "a star allele requires the same reviewed translation a "
                   "diplotype does, and this system performs none",
    "alleles": "allele data requires a reviewed translation to a phenotype, "
               "which this system does not perform",
    "activity_score": "an activity score is a derived quantity from a "
                      "genotype translation this system does not do",
    "vcf": "variant files are outside the P0 permitted input kinds",
    "vcf_path": "a path to a variant file is a variant file, and variant "
                "files are outside the P0 permitted input kinds",
    "ehr": "electronic health record data is outside P0 and outside the "
           "intended purpose",
    "ehr_id": "a record identifier is a pointer into an electronic health "
              "record, which is outside P0 and the intended purpose",
    "patient_narrative": "free clinical narrative must not influence a "
                         "calculation; it is also identifiable text this "
                         "system has no reason to hold",
    "clinical_notes": "clinical notes must not influence a calculation, and "
                      "are identifiable text this system has no reason to "
                      "hold",
    "narrative": "free narrative must not influence a calculation and is "
                 "identifiable text this system has no reason to hold",
    "diagnosis": "this system does not diagnose",
    "indication": "an indication is a clinical judgement, not an input to a "
                  "coverage or attention calculation",
    "dose": "this system calculates no dose and accepts none",
    "dosage": "this system calculates no dosage and accepts none",
    "patient_name": "identifiable data has no calculation role",
    "date_of_birth": "a date of birth is identifiable data with no "
                     "calculation role here",
    "mrn": "a medical record number is identifiable data with no calculation "
           "role here",
}


def _refused_fields(payload: Mapping[str, Any]) -> Tuple[str, ...]:
    return tuple(sorted(set(payload) & set(REFUSED_INPUT_FIELDS)))


@dataclass(frozen=True, slots=True)
class AssessmentInput:
    """One canonical, immutable assessment question.

    ``medications`` are canonical drug keys, already resolved. This type does
    not resolve free text: turning "Plavix" into a canonical drug is WP-07's
    work, and an input contract that guessed would be inventing the subject of
    its own question. A medication the pinned dataset does not contain is kept
    exactly as supplied, so coverage can report it as unsupported - dropping it
    would make an unanswerable question look answered.
    """

    mode: OperationMode
    input_kind: PermittedInputKind
    profile: Any
    medications: Tuple[str, ...]
    case_id: Optional[str] = None
    requested_release_public_id: Optional[str] = None
    #: The care setting a request declares, from a closed vocabulary.
    #:
    #: **This is not an ``indication``,** which stays refused above. The
    #: difference is what the field decides. An indication is a clinical
    #: judgement about a patient, and accepting one would mean this system
    #: reasoning from a diagnosis. A care setting selects *which column of a
    #: guideline table applies*: CPIC's clopidogrel guideline states one set of
    #: recommendations for ACS and/or PCI and a different set for non-ACS,
    #: non-PCI, and this release transcribed one of them.
    #:
    #: The system never infers it. A request that omits it gets a refusal for
    #: every drug whose evidence is care-setting-specific, because a patient
    #: taking clopidogrel is not thereby in an ACS or PCI setting, and assuming
    #: otherwise would apply a column nobody selected. ``None`` is the default
    #: and is the safe value.
    care_setting: Optional[str] = None
    input_schema_version: str = ASSESSMENT_INPUT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.mode, OperationMode):
            raise AssessmentInputError(
                "mode must be a pgx.domain.claims.OperationMode, got %r. A "
                "free string cannot be checked against the claim boundary."
                % type(self.mode).__name__,
                code="ASSESSMENT_MODE_NOT_PERMITTED", location="$.mode")
        if not isinstance(self.input_kind, PermittedInputKind):
            raise AssessmentInputError(
                "input_kind must be a PermittedInputKind, got %r"
                % type(self.input_kind).__name__,
                code="ASSESSMENT_INPUT_KIND_NOT_PERMITTED",
                location="$.input_kind")
        if self.profile is None or not hasattr(self.profile, "content_hash"):
            raise AssessmentInputError(
                "profile must be a WP-12 normalised phenotype profile",
                code="ASSESSMENT_INPUT_INVALID", location="$.profile")
        if not self.medications:
            raise AssessmentInputError(
                "an assessment names at least one medication",
                code="ASSESSMENT_INPUT_INVALID", location="$.medications")
        seen = []
        for value in self.medications:
            if not isinstance(value, str) or not value.strip():
                raise AssessmentInputError(
                    "each medication is a non-empty canonical drug key",
                    code="ASSESSMENT_INPUT_INVALID", location="$.medications")
            key = value.strip()
            if key in seen:
                raise AssessmentInputError(
                    "medication %r is requested twice. Duplicates are refused "
                    "rather than merged: a caller that asked twice may have "
                    "meant two different things, and collapsing them answers a "
                    "question nobody asked." % key,
                    code="ASSESSMENT_INPUT_INVALID", location="$.medications",
                    detail={"medication": key})
            seen.append(key)
        # Canonically sorted for calculation, so the order a caller happened to
        # type in cannot reach the answer or the hash.
        object.__setattr__(self, "medications", tuple(sorted(seen)))
        if self.case_id is not None and (not isinstance(self.case_id, str)
                                         or not self.case_id.strip()):
            raise AssessmentInputError(
                "case_id is optional; a supplied one is a non-empty string",
                code="ASSESSMENT_INPUT_INVALID", location="$.case_id")
        if self.requested_release_public_id is not None and (
                not isinstance(self.requested_release_public_id, str)
                or not self.requested_release_public_id.strip()):
            raise AssessmentInputError(
                "requested_release_public_id is optional; a supplied one is a "
                "non-empty string",
                code="ASSESSMENT_INPUT_INVALID",
                location="$.requested_release_public_id")

    def _validate_care_setting(self) -> None:
        if self.care_setting is None:
            return
        if self.care_setting not in PERMITTED_CARE_SETTINGS:
            raise AssessmentInputError(
                "care_setting %r is not one of %s. The vocabulary is closed "
                "because each member names a guideline column this project "
                "transcribed; an unrecognised value is refused rather than "
                "ignored, which would silently apply the wrong column."
                % (self.care_setting, ", ".join(PERMITTED_CARE_SETTINGS)),
                code="ASSESSMENT_CARE_SETTING_UNSUPPORTED",
                location="$.care_setting")

    def require_permitted(self, boundary: ClaimBoundary) -> None:
        """Refuse unless this boundary enables the mode and the input kind.

        Checked against the boundary the service was given, never against a
        default read here: a service configured with an unapproved boundary
        must not be rescued by a module-level constant.
        """
        self._validate_care_setting()
        # Order matters: a mode this boundary does not enable is reported by
        # the mode check below, which names the mode. Reporting it here would
        # tell a caller their claim boundary is unapproved when the real
        # problem is that they asked for PILOT.
        if boundary.is_mode_enabled(self.mode) \
                and not boundary.permits_execution(self.mode):
            raise AssessmentInputError(
                "the claim boundary is %r. No assessment executes until named "
                "humans have approved the intended purpose, or until a "
                "project-team provisional candidate boundary is supplied "
                "explicitly; no flag in this codebase sets the human approval."
                % boundary.status,
                code="ASSESSMENT_CLAIM_BOUNDARY_NOT_APPROVED",
                location="$.claim_boundary",
                detail={"phase": boundary.phase.value,
                        "status": boundary.status,
                        "execution_basis": boundary.execution_basis})
        if not boundary.is_mode_enabled(self.mode):
            raise AssessmentInputError(
                "operation mode %s is not enabled in %s"
                % (self.mode.value, boundary.phase.value),
                code="ASSESSMENT_MODE_NOT_PERMITTED", location="$.mode",
                detail={"mode": self.mode.value})
        if self.input_kind not in boundary.permitted_input_kinds:
            raise AssessmentInputError(
                "input kind %s is not permitted in %s"
                % (self.input_kind.value, boundary.phase.value),
                code="ASSESSMENT_INPUT_KIND_NOT_PERMITTED",
                location="$.input_kind",
                detail={"input_kind": self.input_kind.value})

    def semantic_content(self) -> Dict[str, Any]:
        """What was asked, and nothing about the asking.

        Excludes ``case_id`` (a label for the run, not part of the question),
        the actor, the clock, the process, the source path and any UI
        metadata. The profile contributes its own semantic hash, which WP-12
        already computed with the same exclusions.
        """
        return {
            "care_setting": self.care_setting,
            "input_schema_version": self.input_schema_version,
            "mode": self.mode.value,
            "input_kind": self.input_kind.value,
            "profile_content_hash": self.profile.content_hash(),
            "medications": list(self.medications),
        }

    def content_hash(self) -> str:
        return sha256_digest(self.semantic_content())

    def to_json(self) -> Dict[str, Any]:
        payload = self.semantic_content()
        payload["case_id"] = self.case_id
        payload["requested_release_public_id"] = self.requested_release_public_id
        payload["content_hash"] = self.content_hash()
        payload["note"] = (
            "case_id and requested_release_public_id are recorded but are not "
            "part of the semantic input: they label the run rather than the "
            "question, and including them would make two identical questions "
            "hash differently.")
        return payload


def build_assessment_input(payload: Mapping[str, Any], *, profile: Any,
                           mode: OperationMode,
                           input_kind: PermittedInputKind) -> AssessmentInput:
    """Read a caller's request document into a canonical input, or refuse.

    Refuses a refused field before reading anything else, so a request
    carrying a VCF path is rejected as a whole rather than quietly used for
    the parts that happened to be acceptable.
    """
    if not isinstance(payload, Mapping):
        raise AssessmentInputError(
            "an assessment request is an object",
            code="ASSESSMENT_INPUT_INVALID", location="$")
    refused = _refused_fields(payload)
    if refused:
        raise AssessmentInputError(
            "request carries field(s) this product does not accept: %s"
            % "; ".join("%s (%s)" % (name, REFUSED_INPUT_FIELDS[name])
                        for name in refused),
            code="ASSESSMENT_INPUT_KIND_NOT_PERMITTED", location="$",
            detail={"refused_fields": list(refused)})
    return AssessmentInput(
        mode=mode, input_kind=input_kind, profile=profile,
        medications=tuple(payload.get("medications") or ()),
        case_id=payload.get("case_id"),
        requested_release_public_id=payload.get("release_id"))


@dataclass(frozen=True, slots=True)
class CanonicalEntityIndex:
    """Canonical key -> the identity the pinned dataset already holds for it.

    A **lookup table, not a derivation.** ``pgx.domain.identifiers`` refuses
    deterministic UUID5 derivation for genes and drugs on purpose: a
    reproducible identity computed from a name would let two different
    canonical builds silently collide on one row. So identity is minted once,
    when the canonical dataset is built, and everything downstream looks it
    up. This is that lookup, frozen into the pinned release context alongside
    the artifacts it belongs to.

    **Every miss is a refusal.** :meth:`drug_id` and :meth:`gene_id` raise
    rather than returning ``None``, and :meth:`from_pairs` refuses a key that
    two rows claim. There is no path through this type that answers "I do not
    know" with a new UUID, because the caller of that answer - the code that
    persists an assessment - cannot tell a minted identity from a resolved
    one, and neither can anybody reading the row a year later.
    """

    drugs: Mapping[str, str]
    genes: Mapping[str, str]
    dataset_public_id: str = ""
    canonical_build_content_hash: str = ""

    def __post_init__(self) -> None:
        for name in ("drugs", "genes"):
            table = getattr(self, name)
            if not isinstance(table, Mapping):
                raise AssessmentArtifactError(
                    "%s is a mapping of canonical key to identity" % name,
                    code="ASSESSMENT_ENTITY_NOT_RESOLVABLE",
                    location="$." + name)
            frozen = {}
            for key, value in table.items():
                if not isinstance(key, str) or not key.strip():
                    raise AssessmentArtifactError(
                        "%s is keyed by canonical key strings" % name,
                        code="ASSESSMENT_ENTITY_NOT_RESOLVABLE",
                        location="$." + name)
                frozen[key] = str(value)
            object.__setattr__(self, name, freeze_json(frozen))

    # -- construction ----------------------------------------------------

    @classmethod
    def from_pairs(cls, *, drugs=(), genes=(), dataset_public_id: str = "",
                   canonical_build_content_hash: str = ""
                   ) -> "CanonicalEntityIndex":
        """Build from ``(canonical_key, identity)`` pairs, or refuse.

        This is where "exactly one" is enforced. A mapping cannot hold a key
        twice, so a caller that built one from ambiguous rows would have
        already silently dropped the duplicate; pairs preserve the ambiguity
        long enough for it to be refused.
        """
        return cls(drugs=cls._collect(drugs, "drugs"),
                   genes=cls._collect(genes, "genes"),
                   dataset_public_id=dataset_public_id,
                   canonical_build_content_hash=canonical_build_content_hash)

    @staticmethod
    def _collect(pairs, field_name: str) -> Dict[str, str]:
        table: Dict[str, str] = {}
        for key, value in pairs:
            identity = str(value)
            if key in table and table[key] != identity:
                raise AssessmentArtifactError(
                    "canonical key %r resolves to %d identities in the pinned "
                    "dataset (%s, %s). Which one an assessment is about is not "
                    "a question this index may answer by picking."
                    % (key, 2, table[key], identity),
                    code="ASSESSMENT_ENTITY_NOT_RESOLVABLE",
                    location="$." + field_name,
                    detail={"canonical_key": key})
            table[key] = identity
        return table

    # -- resolution ------------------------------------------------------

    def drug_id(self, canonical_key: str) -> DrugId:
        """The pinned identity for one canonical drug key, or a refusal."""
        return DrugId.parse(self._resolve(self.drugs, canonical_key, "drug"))

    def gene_id(self, canonical_key: str) -> GeneId:
        """The pinned identity for one canonical gene key, or a refusal."""
        return GeneId.parse(self._resolve(self.genes, canonical_key, "gene"))

    def has_drug(self, canonical_key: str) -> bool:
        return canonical_key in self.drugs

    def has_gene(self, canonical_key: str) -> bool:
        return canonical_key in self.genes

    @staticmethod
    def _resolve(table: Mapping[str, str], canonical_key: str,
                 kind: str) -> str:
        if not isinstance(canonical_key, str) or not canonical_key.strip():
            raise AssessmentArtifactError(
                "a %s identity is resolved from a canonical key string" % kind,
                code="ASSESSMENT_ENTITY_NOT_RESOLVABLE",
                location="$.%s_canonical_key" % kind)
        try:
            return table[canonical_key]
        except KeyError:
            raise AssessmentArtifactError(
                "canonical %s key %r is not in the pinned canonical dataset, "
                "so it has no identity to record. An assessment does not mint "
                "one: a generated identity would look exactly like a resolved "
                "one and join to nothing." % (kind, canonical_key),
                code="ASSESSMENT_ENTITY_NOT_RESOLVABLE",
                location="$.%s_canonical_key" % kind,
                detail={"canonical_key": canonical_key}) from None

    # -- canonical form --------------------------------------------------

    def to_json(self) -> Dict[str, Any]:
        return {
            "dataset_public_id": self.dataset_public_id,
            "canonical_build_content_hash": self.canonical_build_content_hash,
            "drug_count": len(self.drugs),
            "gene_count": len(self.genes),
            "drugs": {key: self.drugs[key] for key in sorted(self.drugs)},
            "genes": {key: self.genes[key] for key in sorted(self.genes)},
        }

    def content_hash(self) -> str:
        return sha256_digest(self.to_json())


@dataclass(frozen=True, slots=True)
class PinnedAssessmentRelease:
    """The execution context, frozen before calculation and never re-read.

    Holds the loaded artifacts *and* the identities and hashes that name them,
    so a stored assessment can be checked against the artifacts that produced
    it rather than against whatever is on disk later.

    ``active_pointer_generation`` is the generation of the WP-03 pointer at the
    moment this was pinned. The service reads the pointer exactly once, here.
    An activation committing afterwards moves the pointer and changes nothing
    about a calculation already running: the running assessment holds this
    object, and this object cannot be reached from the pointer.
    """

    release_bundle: Any
    provenance: Any
    frozen_ruleset: Any
    coverage_manifest: Any
    drug_catalogue: Tuple[str, ...]
    entity_index: Any = None
    evidence_resolver: Any = None

    def __post_init__(self) -> None:
        for name in ("release_bundle", "provenance", "frozen_ruleset",
                     "coverage_manifest"):
            if getattr(self, name) is None:
                raise AssessmentInputError(
                    "a pinned release names its %s" % name,
                    code="ASSESSMENT_VERSION_MISMATCH", location="$." + name)
        if self.entity_index is None:
            # Its own code, because its own remedy: the release is fine and
            # the canonical identity lookup is missing, which is a different
            # problem from two artifacts pinning different versions.
            raise AssessmentArtifactError(
                "a pinned release names the canonical entity index its "
                "identities are resolved from. Without it an assessment "
                "could only be recorded against minted identities, and a "
                "minted identity is indistinguishable from a resolved one.",
                code="ASSESSMENT_ENTITY_NOT_RESOLVABLE",
                location="$.entity_index")
        object.__setattr__(self, "drug_catalogue",
                           tuple(sorted(set(self.drug_catalogue))))

    def require_entity_index(self) -> CanonicalEntityIndex:
        """The canonical identity lookup, or a refusal.

        Checked where identities are actually needed rather than assumed at
        construction, so the failure names the missing capability instead of
        surfacing as an ``AttributeError`` three frames away.
        """
        if not isinstance(self.entity_index, CanonicalEntityIndex):
            raise AssessmentArtifactError(
                "the pinned release carries no canonical entity index, so no "
                "drug or gene identity can be resolved. Recording an "
                "assessment against minted identities is the one alternative, "
                "and it is not available.",
                code="ASSESSMENT_ENTITY_NOT_RESOLVABLE",
                location="$.entity_index")
        return self.entity_index

    @property
    def active_pointer_generation(self) -> int:
        return self.provenance.active_pointer_generation

    @property
    def release_public_id(self) -> str:
        return self.provenance.release_public_id

    def to_json(self) -> Dict[str, Any]:
        return self.provenance.to_json()
