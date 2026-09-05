# -*- coding: utf-8 -*-
"""Immutable values the phenotype engine produces (WP-12).

Four kinds of thing live here: what a normalisation attempt concluded, what a
whole profile looks like once normalised, what a match decision was, and the
vocabularies both are drawn from. All are frozen dataclasses with canonical
JSON forms, because any of them may end up in a regression report that has to
be byte-identical between runs.

Nothing here carries an attention level, a coverage status, a dose, a
recommendation or a safety statement. Those belong to WP-13, WP-14 and WP-15,
and tests assert by field name that they cannot appear.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

from pgx.domain.enums import Phenotype
from pgx.domain.hashing import sha256_digest
from pgx.domain.immutable import EMPTY_MAPPING, FrozenMapping, freeze_json
from pgx.engine.phenotype_errors import PhenotypeProfileError

__all__ = [
    "MATCH_RESULT_SCHEMA_VERSION",
    "MATCH_STATUSES",
    "NORMALIZATION_REASON_CODES",
    "NORMALIZATION_RESULT_SCHEMA_VERSION",
    "NORMALIZATION_STATUSES",
    "PROFILE_SCHEMA_VERSION",
    "MatchDecision",
    "PhenotypeObservation",
    "PhenotypeProfile",
]

#: Versioned so a stored result can be read later by something that knows
#: which contract produced it.
NORMALIZATION_RESULT_SCHEMA_VERSION = "pgx-phenotype-normalization-result/1"
PROFILE_SCHEMA_VERSION = "pgx-phenotype-profile/1"
MATCH_RESULT_SCHEMA_VERSION = "pgx-phenotype-match-result/1"

#: What a normalisation attempt can conclude. Four outcomes, not two: a caller
#: that could only tell success from failure could not tell a phenotype nobody
#: supplied from one that was supplied and could not be interpreted, and those
#: two facts have different consequences downstream.
NORMALIZATION_STATUSES: Tuple[str, ...] = (
    "NORMALIZED", "MISSING", "INDETERMINATE", "UNSUPPORTED")

#: Why a normalisation did not produce a phenotype. Stable and machine
#: readable: a coverage engine will branch on these, and a report will
#: eventually show them to a person.
NORMALIZATION_REASON_CODES: Mapping[str, str] = {
    "PHENOTYPE_INPUT_MISSING":
        "no value was supplied for this gene; absence is not a phenotype and "
        "is never treated as one",
    "PHENOTYPE_INPUT_INDETERMINATE":
        "the input states that the phenotype could not be determined; that is "
        "a recorded observation, and it matches no rule",
    "PHENOTYPE_INPUT_UNSUPPORTED":
        "the value is not a canonical phenotype token under this input "
        "contract version; it is not guessed at",
    "PHENOTYPE_INPUT_INVALID_TYPE":
        "the value is not a string; a number, boolean, list or object is not "
        "a phenotype and is not coerced into one",
    "PHENOTYPE_INPUT_GENOTYPE_NOT_ALLOWED":
        "the value looks like a genotype, diplotype or star allele; deriving "
        "a phenotype from one is inference this system does not perform",
    "PHENOTYPE_INPUT_BROAD_GROUP_NOT_ALLOWED":
        "the value names a broad functional group rather than a phenotype; "
        "expanding one into POOR or INTERMEDIATE would apply a rule outside "
        "the evidence it was written from",
}

#: What the matcher can decide. The three input statuses are carried through
#: rather than collapsed into NO_MATCH: "this rule does not apply" and "we
#: could not tell whether it applies" are different answers, and only the
#: first is a finding about the input.
MATCH_STATUSES: Tuple[str, ...] = (
    "MATCH", "NO_MATCH", "INPUT_MISSING", "INPUT_INDETERMINATE",
    "INPUT_UNSUPPORTED")

#: How a non-NORMALIZED observation is reported by the matcher. One mapping,
#: so the two vocabularies cannot drift apart.
_STATUS_TO_MATCH_STATUS: Mapping[str, str] = {
    "MISSING": "INPUT_MISSING",
    "INDETERMINATE": "INPUT_INDETERMINATE",
    "UNSUPPORTED": "INPUT_UNSUPPORTED",
}


def _require_status(value: Any, allowed: Tuple[str, ...], field_name: str) -> str:
    if value not in allowed:
        raise PhenotypeProfileError(
            "%s must be one of %s, got %r"
            % (field_name, ", ".join(allowed), value),
            code="PHENOTYPE_STATUS_UNKNOWN", location="$." + field_name)
    return value


@dataclass(frozen=True, slots=True)
class PhenotypeObservation:
    """What normalisation concluded about one gene's supplied value.

    ``phenotype`` is set only when ``status`` is ``NORMALIZED``. The coupling
    is enforced rather than documented: an observation carrying both a failure
    status and a phenotype would let a careless reader use the phenotype.

    ``raw_value`` keeps what was supplied, as text, so a regression report can
    show the input beside the verdict. Nothing that decides anything reads it.
    """

    gene_canonical_key: str
    status: str
    phenotype: Optional[Phenotype] = None
    reason_code: Optional[str] = None
    reason: Optional[str] = None
    raw_value: Optional[str] = None
    input_contract_version: str = ""

    def __post_init__(self) -> None:
        _require_status(self.status, NORMALIZATION_STATUSES, "status")
        if not isinstance(self.gene_canonical_key, str) or \
                not self.gene_canonical_key.strip():
            raise PhenotypeProfileError(
                "an observation names the canonical gene it is about",
                code="PHENOTYPE_OBSERVATION_UNKEYED", location="$.gene_id")
        if self.status == "NORMALIZED":
            if not isinstance(self.phenotype, Phenotype):
                raise PhenotypeProfileError(
                    "a NORMALIZED observation carries a Phenotype",
                    code="PHENOTYPE_OBSERVATION_INCOMPLETE",
                    location="$.phenotype")
            if self.phenotype is Phenotype.INDETERMINATE:
                raise PhenotypeProfileError(
                    "INDETERMINATE is its own status, not a normalised "
                    "phenotype; recording it as NORMALIZED would let it be "
                    "compared with a rule's declared values",
                    code="PHENOTYPE_OBSERVATION_INCONSISTENT",
                    location="$.phenotype")
            if self.reason_code is not None:
                raise PhenotypeProfileError(
                    "a NORMALIZED observation has no failure reason",
                    code="PHENOTYPE_OBSERVATION_INCONSISTENT",
                    location="$.reason_code")
        else:
            if self.phenotype is not None:
                raise PhenotypeProfileError(
                    "a %s observation carries no phenotype; carrying one would "
                    "invite a reader to use it" % self.status,
                    code="PHENOTYPE_OBSERVATION_INCONSISTENT",
                    location="$.phenotype")
            if self.reason_code not in NORMALIZATION_REASON_CODES:
                raise PhenotypeProfileError(
                    "a %s observation names a documented reason code, got %r"
                    % (self.status, self.reason_code),
                    code="PHENOTYPE_REASON_UNKNOWN", location="$.reason_code")

    # -- reading --------------------------------------------------------

    @property
    def is_normalized(self) -> bool:
        return self.status == "NORMALIZED"

    @property
    def match_status_for_failure(self) -> str:
        """The match status this observation forces, or ``""`` if it forces
        none. Kept here so the matcher cannot invent a second mapping."""
        return _STATUS_TO_MATCH_STATUS.get(self.status, "")

    # -- canonical form -------------------------------------------------

    def to_json(self) -> Dict[str, Any]:
        return {
            "result_schema_version": NORMALIZATION_RESULT_SCHEMA_VERSION,
            "input_contract_version": self.input_contract_version,
            "gene_id": self.gene_canonical_key,
            "status": self.status,
            "phenotype": self.phenotype.value if self.phenotype else None,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "raw_value": self.raw_value,
        }

    def semantic_content(self) -> Dict[str, Any]:
        """What identity covers: the verdict, not what was typed.

        ``raw_value`` is excluded on purpose. Two profiles supplying ``"POOR"``
        and ``" poor "`` observed the same thing, and a hash that disagreed
        would make "did this profile change" unanswerable over whitespace.
        """
        return {
            "gene_id": self.gene_canonical_key,
            "status": self.status,
            "phenotype": self.phenotype.value if self.phenotype else None,
            "reason_code": self.reason_code,
        }

    def content_hash(self) -> str:
        return sha256_digest(self.semantic_content())


@dataclass(frozen=True, slots=True)
class PhenotypeProfile:
    """A canonical, immutable set of phenotype observations.

    Observations are held in canonical gene order and every failure is kept as
    an explicit observation rather than dropped. A profile that silently
    omitted the genes it could not interpret would look complete.

    ``metadata`` holds display names and demo descriptions. It is excluded
    from the semantic hash and no matcher reads it: a profile's identity is
    what was observed, not what somebody called it.
    """

    observations: Tuple[PhenotypeObservation, ...]
    input_contract_version: str
    profile_id: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=lambda: EMPTY_MAPPING)
    profile_schema_version: str = PROFILE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.profile_schema_version != PROFILE_SCHEMA_VERSION:
            raise PhenotypeProfileError(
                "profile_schema_version %r is not %r"
                % (self.profile_schema_version, PROFILE_SCHEMA_VERSION),
                code="PHENOTYPE_PROFILE_SCHEMA_VERSION",
                location="$.profile_schema_version")
        seen = set()
        for observation in self.observations:
            if not isinstance(observation, PhenotypeObservation):
                raise PhenotypeProfileError(
                    "a profile holds PhenotypeObservation values",
                    code="PHENOTYPE_PROFILE_MALFORMED",
                    location="$.observations")
            if observation.gene_canonical_key in seen:
                raise PhenotypeProfileError(
                    "gene %s appears twice after normalisation"
                    % observation.gene_canonical_key,
                    code="PHENOTYPE_PROFILE_DUPLICATE_GENE",
                    location="$.observations")
            seen.add(observation.gene_canonical_key)
        object.__setattr__(
            self, "observations",
            tuple(sorted(self.observations,
                         key=lambda item: item.gene_canonical_key)))
        object.__setattr__(self, "metadata",
                           freeze_json(dict(self.metadata or {})))

    # -- reading --------------------------------------------------------

    @property
    def gene_keys(self) -> Tuple[str, ...]:
        return tuple(item.gene_canonical_key for item in self.observations)

    @property
    def observation_count(self) -> int:
        return len(self.observations)

    def observation_for(self, gene_canonical_key: str
                        ) -> Optional[PhenotypeObservation]:
        """The observation for one canonical gene, or ``None``.

        ``None`` means this profile says nothing at all about that gene, which
        is a different fact from an observation whose status is ``MISSING`` -
        that one says somebody supplied the gene and left it blank. The matcher
        distinguishes them in its reason code; both refuse to match.
        """
        for observation in self.observations:
            if observation.gene_canonical_key == gene_canonical_key:
                return observation
        return None

    def frozen(self) -> FrozenMapping:
        return freeze_json(self.to_json())

    # -- canonical form -------------------------------------------------

    def semantic_content(self) -> Dict[str, Any]:
        """Everything the profile hash covers.

        Deliberately excluded: ``metadata`` (display names, demo notes), each
        observation's ``raw_value``, insertion order, the file a profile was
        read from, and the moment it was read. Two callers who observed the
        same phenotypes for the same genes have the same profile.
        """
        return {
            "profile_schema_version": self.profile_schema_version,
            "input_contract_version": self.input_contract_version,
            "profile_id": self.profile_id,
            "observation_count": len(self.observations),
            "observations": [item.semantic_content()
                             for item in self.observations],
        }

    def content_hash(self) -> str:
        return sha256_digest(self.semantic_content())

    def to_json(self) -> Dict[str, Any]:
        payload = self.semantic_content()
        payload["observations"] = [item.to_json() for item in self.observations]
        payload["metadata"] = dict(self.metadata)
        payload["content_hash"] = self.content_hash()
        return payload


@dataclass(frozen=True, slots=True)
class MatchDecision:
    """One phenotype compared with one WP-11 phenotype condition.

    Carries what was compared and what came of it, and nothing about what the
    result should cause. There is no attention level here, no coverage status,
    no dose, no recommendation and no prose, and the published schema refuses
    each of them by name.

    ``condition_hash`` pins the exact condition evaluated, so a stored decision
    can be checked against the rule that produced it rather than against a rule
    sharing its identity and carrying different content.
    """

    status: str
    gene_canonical_key: str
    operator: str
    declared_phenotypes: Tuple[Phenotype, ...]
    condition_hash: str
    observed_phenotype: Optional[Phenotype] = None
    observation_status: str = ""
    reason_code: Optional[str] = None
    match_result_schema_version: str = MATCH_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_status(self.status, MATCH_STATUSES, "status")
        if not self.declared_phenotypes:
            raise PhenotypeProfileError(
                "a decision names the phenotypes the condition declared",
                code="PHENOTYPE_DECISION_INCOMPLETE",
                location="$.declared_phenotypes")
        if self.status == "MATCH" and self.observed_phenotype is None:
            raise PhenotypeProfileError(
                "a MATCH names the phenotype that matched",
                code="PHENOTYPE_DECISION_INCOMPLETE",
                location="$.observed_phenotype")
        if self.status not in ("MATCH", "NO_MATCH") and \
                self.observed_phenotype is not None:
            raise PhenotypeProfileError(
                "a %s decision carries no observed phenotype" % self.status,
                code="PHENOTYPE_DECISION_INCONSISTENT",
                location="$.observed_phenotype")

    @property
    def matched(self) -> bool:
        """True only for ``MATCH``.

        Every other status - the three input failures included - is false.
        There is no status under which "we could not tell" counts as a match.
        """
        return self.status == "MATCH"

    def to_json(self) -> Dict[str, Any]:
        return {
            "match_result_schema_version": self.match_result_schema_version,
            "status": self.status,
            "gene_id": self.gene_canonical_key,
            "operator": self.operator,
            "declared_phenotypes": [value.value
                                    for value in self.declared_phenotypes],
            "observed_phenotype": (self.observed_phenotype.value
                                   if self.observed_phenotype else None),
            "observation_status": self.observation_status,
            "reason_code": self.reason_code,
            "condition_hash": self.condition_hash,
        }

    def content_hash(self) -> str:
        return sha256_digest(self.to_json())
