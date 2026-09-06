# -*- coding: utf-8 -*-
"""The candidate validation catalogue (WP-C10).

Built on WP-18's existing case machinery - the same
:class:`~pgx.validation.cases.ValidationCaseMetadata`, the same content and
derivation-family fingerprints, the same separation audit that refuses a
holdout derived from a development fixture. Wave 3 adds no new separation
rules, because the existing ones are the ones that matter and inventing a
looser sibling set would be the point at which this catalogue stopped being
comparable to the one the project already trusts.

**The partitions are derived from different parts of the evidence, on purpose.**

``DEVELOPMENT``
    the (gene, drug, phenotype) combinations the candidate rules encode, with
    the expected attention level taken from the curation that produced those
    rules. These cases can only ever confirm that the ruleset does what its
    author meant; that is what they are for.

``INTERNAL_HOLDOUT``
    the twenty amitriptyline CYP2C19 x CYP2D6 combinations, with the expected
    behaviour taken from the guideline's own joint table. **No candidate rule
    is derived from that table** - the rule grammar carries one gene per
    condition and cannot express it - so these cases test the ruleset against
    a source it does not encode.

``EXPERT_HOLDOUT``
    the refusal surface: every combination the first release must fail closed
    on. Sealed and deliberately not evaluated in this wave.

**What none of this is.** One process authored the rules, the cases and the
expected answers. A holdout that shares an author with the thing it tests is
not independent evidence, and no arrangement of partitions inside one build
can make it so. :data:`CATALOGUE_LIMITATIONS` says this in the artifact rather
than only here, because the separation audit passing is exactly the result
somebody would otherwise quote as independence.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Tuple

from pgx.closure.authority import CandidateAuthorityState
from pgx.closure.candidate_curation import CURATIONS
from pgx.closure.candidate_ruleset import REFUSALS, build_candidate_ruleset
from pgx.closure.source_grounding import RETRIEVALS
from pgx.closure.source_rows import AMITRIPTYLINE_JOINT_ROWS
from pgx.validation.cases import (Provenance, ValidationCaseId,
                                  ValidationCaseMetadata)
from pgx.validation.compatibility import ReleaseCompatibility
from pgx.validation.fingerprint import content_fingerprint
from pgx.validation.vocabulary import (DataClassification, ValidationCaseRole,
                                       VisibilityLevel)

__all__ = [
    "CATALOGUE_LIMITATIONS",
    "CATALOGUE_VERSION",
    "CandidateCase",
    "build_catalogue",
]

CATALOGUE_VERSION = "pgx-wave03-candidate-cases/1"

NO_PII = ("These cases carry gene symbols, drug names and phenotype labels "
          "only. No patient, sample, identifier, date of birth or free text "
          "of any kind is present, and none was available to the process that "
          "built them.")

CATALOGUE_LIMITATIONS: Tuple[str, ...] = (
    "one process authored the candidate rules, these cases and their expected "
    "answers; no partition here is independent of the build it tests, and a "
    "passing separation audit says the partitions do not leak into each "
    "other, not that any of them is independent evidence",
    "the INTERNAL_HOLDOUT partition tests against the guideline's joint table, "
    "which no candidate rule encodes; that makes it a stronger check than the "
    "development partition and still not an external one",
    "the EXPERT_HOLDOUT partition is sealed and was not evaluated in this "
    "wave; it is reserved so that a later external reviewer has material this "
    "build has not been scored against",
    "an external expert should bring their own cases: a catalogue this "
    "project wrote cannot tell that project what it failed to think of",
)

#: Short identifier fragments for the refusal reasons. Case identifiers may
#: carry only uppercase letters, digits and hyphens, and are length-capped, so
#: the full reason codes do not fit. The mapping is explicit rather than
#: derived by truncation: two codes that truncated to the same fragment would
#: silently collide into one case identifier.
_REASON_TAG: Mapping[str, str] = {
    "PHENOTYPE_NOT_REPRESENTABLE": "PNR",
    "SOURCE_STATES_NO_RECOMMENDATION": "SNR",
    "AXIS_ABSENT_FROM_SOURCE": "AAS",
    "SOURCE_ROW_ABSENT": "SRA",
}

_BUILT_AT = _dt.datetime(2026, 9, 6, 12, 0, 0, tzinfo=_dt.timezone.utc)


def _compatibility(ruleset_hash: str) -> ReleaseCompatibility:
    # ``ruleset_public_id`` and ``release_public_id`` are deliberately left
    # unset. Both fields are format-checked against PGX-RULESET-YYYYMMDD-NNN
    # and the matching release pattern, which are the identifiers of *governed*
    # artifacts. The candidate ruleset is not one, and minting an identifier
    # in the governed shape would make it indistinguishable from one in every
    # artifact that prints the field. The candidate identity travels in the
    # note, where nothing will mistake it for a registered id.
    return ReleaseCompatibility(
        release_manifest_hash=ruleset_hash,
        note=("candidate ruleset PGX-CANDIDATE-RULESET-WAVE03 in candidate "
              "release PGX-CANDIDATE-RELEASE-WAVE03; neither is a governed "
              "artifact, both are executable in DEMO and VALIDATION only, and "
              "both are pending external expert review"))


def _citation(retrieval_key: str) -> str:
    for item in RETRIEVALS:
        if item.retrieval_key == retrieval_key:
            return ("CPIC via ClinPGx %s, PMID %s, DOI %s"
                    % (item.annotation_id, item.pmid, item.doi))
    raise KeyError("no retrieval named %r" % retrieval_key)


@dataclass(frozen=True, slots=True)
class CandidateCase:
    """One case: its metadata, its input, and what the build should answer.

    ``expected`` is kept beside the metadata rather than inside the fingerprint
    content, so that two cases with the same input and different expectations
    are visibly the same input rather than two unrelated fingerprints.
    """

    metadata: ValidationCaseMetadata
    content: Mapping[str, Any]
    expected: Mapping[str, Any]

    def to_json(self) -> Dict[str, Any]:
        return {
            "content": dict(self.content),
            "expected": dict(self.expected),
            "metadata": self.metadata.to_json(),
        }


def _case(*, case_id: str, role: ValidationCaseRole,
          content: Mapping[str, Any], expected: Mapping[str, Any],
          source_identity: str, derivation_method: str,
          derived_from_development: bool, citation: str,
          visibility: VisibilityLevel, ruleset_hash: str,
          title: str, notes: str) -> CandidateCase:
    return CandidateCase(
        metadata=ValidationCaseMetadata(
            case_id=ValidationCaseId(case_id),
            role=role,
            classification=DataClassification.PUBLISHED_LITERATURE_DERIVED,
            provenance=Provenance(
                source_identity=source_identity,
                derivation_method=derivation_method,
                derived_from_development=derived_from_development,
                citation=citation,
                author=("pgx-closure-wave03 automated pass "
                        "(NOT A HUMAN CASE AUTHOR)")),
            content_fingerprint=content_fingerprint(content),
            no_pii_assertion=NO_PII,
            created_at=_BUILT_AT,
            compatibility=_compatibility(ruleset_hash),
            visibility=visibility,
            title=title,
            notes=notes),
        content=dict(content),
        expected=dict(expected))


def build_catalogue() -> Tuple[CandidateCase, ...]:
    """Build every case. Deterministic: same inputs, same fingerprints."""
    ruleset = build_candidate_ruleset()
    ruleset_hash = ruleset.content_hash()
    cases: List[CandidateCase] = []

    # -- DEVELOPMENT: what the rules encode ---------------------------------
    for item in CURATIONS:
        content = {"gene": item.gene, "drug": item.drug,
                   "phenotype": item.phenotype.value,
                   "context": item.context}
        cases.append(_case(
            case_id=("PGX-VAL-W03-DEV-%s-%s-%s"
                     % (item.drug.upper(), item.gene, item.phenotype.value)),
            role=ValidationCaseRole.DEVELOPMENT,
            content=content,
            expected={"outcome": "ATTENTION",
                      "attention_level": item.attention_level.value},
            source_identity="CPIC single-axis recommendation table: %s / %s / "
                            "%s" % (item.drug, item.gene,
                                    item.phenotype.value),
            derivation_method=("read from the guideline's single-axis "
                               "recommendation table and mapped to an "
                               "attention level by this project"),
            derived_from_development=True,
            citation=_citation(item.retrieval_key),
            visibility=VisibilityLevel.AUTHOR_VISIBLE,
            ruleset_hash=ruleset_hash,
            title="%s / %s / %s" % (item.drug, item.gene,
                                    item.phenotype.value),
            notes=("the candidate rule for this combination was authored from "
                   "the same table row; agreement here confirms the encoding "
                   "and nothing about the science")))

    # -- INTERNAL_HOLDOUT: the joint table no rule encodes -------------------
    for cell in AMITRIPTYLINE_JOINT_ROWS:
        d6 = cell.cyp2d6_member()
        if d6 is None:
            continue
        for c19 in cell.cyp2c19_members():
            content = {"drug": "amitriptyline",
                       "CYP2C19": c19.value,
                       "CYP2D6": d6.value,
                       "context": "higher initial doses, e.g. depression"}
            cases.append(_case(
                case_id=("PGX-VAL-W03-INT-AMI-%s-%s"
                         % (c19.value, d6.value)),
                role=ValidationCaseRole.INTERNAL_HOLDOUT,
                content=content,
                expected={
                    "outcome": "ATTENTION_NOT_WEAKER_THAN_JOINT_TABLE",
                    "joint_recommendation": cell.recommendation_verbatim,
                    "joint_classification": cell.classification},
                source_identity=("CPIC tricyclic antidepressant guideline "
                                 "Table 4 (joint CYP2C19 x CYP2D6 "
                                 "recommendation): %s x %s"
                                 % (c19.value, d6.value)),
                derivation_method=("read from the guideline's joint "
                                   "two-gene table, which no candidate rule "
                                   "encodes"),
                derived_from_development=False,
                citation=_citation("cpic.amitriptyline.cyp2c19_cyp2d6"),
                visibility=VisibilityLevel.RESTRICTED,
                ruleset_hash=ruleset_hash,
                title="amitriptyline joint %s + %s" % (c19.value, d6.value),
                notes=("the candidate rules carry one gene each and cannot "
                       "express this cell; the case checks that combining "
                       "them never comes out weaker than the guideline's own "
                       "joint answer")))

    # -- EXPERT_HOLDOUT: the refusal surface, sealed and not evaluated ------
    for index, item in enumerate(REFUSALS, start=1):
        content = {"drug": item.drug, "gene": item.gene,
                   "source_phenotype": item.source_phenotype,
                   "project_phenotype": item.project_phenotype}
        cases.append(_case(
            case_id=("PGX-VAL-W03-EXP-%02d-%s-%s"
                     % (index, item.drug.upper(), _REASON_TAG[item.reason_code])),
            role=ValidationCaseRole.EXPERT_HOLDOUT,
            content=content,
            expected={"outcome": "REFUSE_FAIL_CLOSED",
                      "reason_code": item.reason_code},
            source_identity=("first-release refusal surface: %s / %s / %s (%s)"
                             % (item.drug, item.gene, item.source_phenotype,
                                item.reason_code)),
            derivation_method=("derived from a phenotype the source states no "
                               "recommendation for, states no row for, or "
                               "this project's vocabulary cannot carry"),
            derived_from_development=False,
            citation=("CPIC first-release scope; see "
                      "data/closure/wave-03-candidate-evidence/refusals.json"),
            visibility=VisibilityLevel.RESTRICTED,
            ruleset_hash=ruleset_hash,
            title="refuse %s / %s / %s" % (item.drug, item.gene,
                                           item.source_phenotype),
            notes=("sealed for a later external reviewer; this wave recorded "
                   "the case and did not evaluate the build against it")))

    identifiers = [case.metadata.case_id.value for case in cases]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("duplicate candidate case identifiers")
    return tuple(cases)
