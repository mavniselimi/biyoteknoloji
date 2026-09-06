# -*- coding: utf-8 -*-
"""The Wave 4 validation catalogue (WP-C10).

Built on WP-18's case machinery - the same ``ValidationCaseMetadata``, content
and derivation-family fingerprints, and separation audit. Wave 4 adds no new
separation rules; a looser sibling set would stop the result being comparable
to the one the project already trusts.

**The Wave 3 catalogue is reclassified, not reused.** Its 56 cases were built
against the Wave 3 standalone ruleset, which no longer exists as an executable
artifact, and its expected answers came from the same curation that produced
the rules. Those cases are internal consistency evidence and are described that
way; they are preserved unchanged under
``data/closure/wave-03-candidate-release/``.

**Three partitions, derived from three different things.**

``DEVELOPMENT``
    every combination the candidate rules encode, with the expected attention
    level taken from the curation that produced them. These can only confirm
    that the ruleset does what its author meant. That is what they are for.

``INTERNAL_HOLDOUT``
    the *behaviour* the rules do not state: refusals, boundary conditions,
    missing axes, absent care settings, out-of-scope drugs. Their expected
    answers come from the first-release scope rules and the guideline's own
    silences, not from any rule's outcome, so a ruleset can encode every rule
    correctly and still fail these.

``EXPERT_HOLDOUT``
    reserved for a later external reviewer, and carrying **no expected
    answer**. Recording one would be inventing an expert judgment, which is
    the thing this partition exists to avoid. Each case carries its input and
    the question to be answered, and nothing else.

**Sealing.** :func:`seal` writes the catalogue and its fingerprints before any
benchmark runs. After that, an expected answer that disagrees with a run
becomes a recorded issue; it does not become a corrected expectation.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.closure.wave03b_build import (CARE_SETTING_ACS_PCI,
                                       build_candidate_interpretations)
from pgx.domain.authority import CandidateAuthorityState
from pgx.domain.enums import AttentionLevel, Phenotype
from pgx.validation.cases import (Provenance, ValidationCaseId,
                                  ValidationCaseMetadata)
from pgx.validation.compatibility import ReleaseCompatibility
from pgx.validation.fingerprint import content_fingerprint
from pgx.validation.vocabulary import (DataClassification, ValidationCaseRole,
                                       VisibilityLevel)

__all__ = [
    "CATALOGUE_LIMITATIONS",
    "CATALOGUE_VERSION",
    "Wave4Case",
    "build_catalogue",
]

CATALOGUE_VERSION = "pgx-wave04-validation-catalogue/1"

AUTHOR = ("pgx-closure-wave04 automated pass (NOT A HUMAN CASE AUTHOR)")

NO_PII = ("These cases carry gene symbols, drug names, phenotype labels and a "
          "care setting from a closed vocabulary. No patient, sample, "
          "identifier, date of birth or free text of any kind is present, and "
          "none was available to the process that built them.")

CATALOGUE_LIMITATIONS: Tuple[str, ...] = (
    "one process authored the candidate rules, these cases and the expected "
    "answers for two of the three partitions; no partition here is "
    "independent of the build it tests, and a passing separation audit says "
    "the partitions do not leak into each other, not that any of them is "
    "independent evidence",
    "the DEVELOPMENT partition can only confirm that the ruleset encodes what "
    "its author intended; it is internal consistency evidence and is never "
    "validation of the science",
    "the INTERNAL_HOLDOUT partition tests refusal and boundary behaviour that "
    "no rule states, so a ruleset can encode every rule correctly and still "
    "fail it; that makes it a stronger check than the development partition "
    "and still not an external one",
    "the EXPERT_HOLDOUT partition carries no expected answers at all, because "
    "recording one would be inventing an expert judgment; it is reserved "
    "unopened for a later external reviewer",
    "results from this catalogue may be described as INTERNAL_VALIDATION or "
    "LITERATURE_DERIVED_VALIDATION and as nothing else",
)

_SEALED_AT = _dt.datetime(2026, 9, 6, 12, 0, 0, tzinfo=_dt.timezone.utc)


@dataclass(frozen=True, slots=True)
class Wave4Case:
    """One case: metadata, the request, and the expected answer if any."""

    metadata: ValidationCaseMetadata
    request: Mapping[str, Any]
    expected: Optional[Mapping[str, Any]]
    question: str

    def to_json(self) -> Dict[str, Any]:
        return {
            "expected": (dict(self.expected)
                         if self.expected is not None else None),
            "metadata": self.metadata.to_json(),
            "question": self.question,
            "request": dict(self.request),
        }


def _compatibility(release_id: str, manifest_hash: str
                   ) -> ReleaseCompatibility:
    # ruleset_public_id and release_public_id are left unset: both are
    # format-checked against the governed identifier shapes, and minting one
    # would make a candidate artifact indistinguishable from a registered one
    # everywhere the field is printed.
    return ReleaseCompatibility(
        release_manifest_hash=manifest_hash,
        note=("candidate release %s; not a governed artifact, executable in "
              "DEMO and VALIDATION only, pending external expert review"
              % release_id))


def _case(*, case_id: str, role: ValidationCaseRole,
          request: Mapping[str, Any], expected: Optional[Mapping[str, Any]],
          question: str, source_identity: str, derivation_method: str,
          derived_from_development: bool, citation: str,
          visibility: VisibilityLevel, release_id: str, manifest_hash: str,
          title: str, notes: str) -> Wave4Case:
    return Wave4Case(
        metadata=ValidationCaseMetadata(
            case_id=ValidationCaseId(case_id),
            role=role,
            classification=DataClassification.PUBLISHED_LITERATURE_DERIVED,
            provenance=Provenance(
                source_identity=source_identity,
                derivation_method=derivation_method,
                derived_from_development=derived_from_development,
                citation=citation, author=AUTHOR),
            content_fingerprint=content_fingerprint(request),
            no_pii_assertion=NO_PII,
            created_at=_SEALED_AT,
            compatibility=_compatibility(release_id, manifest_hash),
            visibility=visibility, title=title, notes=notes),
        request=dict(request), expected=expected, question=question)


def _dev_cases(release_id: str, manifest_hash: str,
               ruleset) -> List[Wave4Case]:
    """One case per combination the rules encode."""
    cases: List[Wave4Case] = []
    interpretations = {item.interpretation_key: item
                       for item in build_candidate_interpretations()}
    for rule in sorted(ruleset.rules, key=lambda r: r.rule_key):
        drug = rule.drug_canonical_key
        care = (CARE_SETTING_ACS_PCI if rule.care_setting else None)
        if rule.is_joint:
            combos = [{item.gene_canonical_key: value.value
                       for item in rule.condition.genes
                       for value in (v,)} for v in ()]
            import itertools
            per_gene = [[(item.gene_canonical_key, value)
                         for value in item.phenotype.values]
                        for item in rule.condition.genes]
            combos = [dict(pairs) for pairs in itertools.product(*per_gene)]
        else:
            combos = [{rule.condition.gene_canonical_key: value}
                      for value in rule.condition.phenotype.values]
        for index, combination in enumerate(combos, 1):
            phenotypes = {key: value.value if isinstance(value, Phenotype)
                          else value for key, value in combination.items()}
            request = {"care_setting": care, "medications": [drug],
                       "mode": "VALIDATION", "phenotypes": phenotypes}
            slug = "-".join(
                [drug.split(":", 1)[1].upper()[:12]]
                + [v for _k, v in sorted(phenotypes.items())])[:40]
            citation = (rule.provenance.citations[0]
                        if rule.provenance.citations else "CPIC")
            cases.append(_case(
                case_id="PGX-VAL-W4-DEV-%s-%02d" % (
                    "".join(c for c in slug.upper() if c.isalnum() or c == "-"),
                    index),
                role=ValidationCaseRole.DEVELOPMENT,
                request=request,
                expected={"outcome": "ATTENTION",
                          "attention_level":
                              rule.outcome.attention_level.value},
                question=("what attention level does the candidate release "
                          "report for this combination?"),
                source_identity="candidate rule %s" % rule.rule_key,
                derivation_method=("enumerated from the combination the rule "
                                   "encodes; the expected answer is the "
                                   "rule's own outcome"),
                derived_from_development=True,
                citation=citation,
                visibility=VisibilityLevel.AUTHOR_VISIBLE,
                release_id=release_id, manifest_hash=manifest_hash,
                title="%s %s" % (drug, ", ".join(
                    "%s=%s" % (k.split(":", 1)[1], v)
                    for k, v in sorted(phenotypes.items()))),
                notes=("internal consistency: the rule and the expectation "
                       "have one author, so agreement confirms the encoding "
                       "and nothing about the science")))
    return cases


#: The refusal and boundary behaviours the rules do not state. Each expected
#: answer comes from the first-release scope decisions and the guideline's own
#: silences, so a ruleset can encode every rule correctly and still fail here.
_HOLDOUT_SPECS: Tuple[Tuple[str, Dict[str, Any], str, str, str], ...] = (
    ("CLOPIDOGREL-NO-CARE-SETTING",
     {"care_setting": None, "medications": ["DRUG:clopidogrel"],
      "phenotypes": {"GENE:CYP2C19": "POOR"}},
     "CARE_SETTING_NOT_DECLARED",
     "CPIC clopidogrel guideline Table 1 states separate recommendations for "
     "ACS and/or PCI and for non-ACS, non-PCI; only the first was transcribed",
     "the release must not answer without knowing which column applies"),
    ("CLOPIDOGREL-NO-SETTING-NORMAL",
     {"care_setting": None, "medications": ["DRUG:clopidogrel"],
      "phenotypes": {"GENE:CYP2C19": "NORMAL"}},
     "CARE_SETTING_NOT_DECLARED",
     "as above; a normal metabolizer is not an exception",
     "the refusal must not depend on the phenotype being an alarming one"),
    ("CODEINE-RAPID",
     {"care_setting": None, "medications": ["DRUG:codeine"],
      "phenotypes": {"GENE:CYP2D6": "RAPID"}},
     "PHENOTYPE_NOT_SUPPORTED",
     "CPIC's CYP2D6 activity-score model has no rapid metabolizer band",
     "an axis absent from the evidence must not be answered"),
    ("AMITRIPTYLINE-2D6-RAPID",
     {"care_setting": None, "medications": ["DRUG:amitriptyline"],
      "phenotypes": {"GENE:CYP2C19": "NORMAL", "GENE:CYP2D6": "RAPID"}},
     "PHENOTYPE_NOT_SUPPORTED",
     "as above, on the joint axis",
     "a joint rule must refuse an unsupported phenotype on either gene"),
    ("AMITRIPTYLINE-ONLY-2C19",
     {"care_setting": None, "medications": ["DRUG:amitriptyline"],
      "phenotypes": {"GENE:CYP2C19": "NORMAL"}},
     "PHENOTYPE_NOT_PROVIDED",
     "CPIC tricyclic guideline Table 4 is a two-gene matrix",
     "a missing axis must refuse rather than answer from the present one"),
    ("AMITRIPTYLINE-ONLY-2D6",
     {"care_setting": None, "medications": ["DRUG:amitriptyline"],
      "phenotypes": {"GENE:CYP2D6": "POOR"}},
     "PHENOTYPE_NOT_PROVIDED",
     "as above, with the other gene missing",
     "the refusal must not depend on which gene is absent"),
    ("AMITRIPTYLINE-NO-GENES",
     {"care_setting": None, "medications": ["DRUG:amitriptyline"],
      "phenotypes": {}},
     "PHENOTYPE_NOT_PROVIDED",
     "as above, with neither gene supplied",
     "an empty profile must refuse"),
    ("OMEPRAZOLE-NO-GENE",
     {"care_setting": None, "medications": ["DRUG:omeprazole"],
      "phenotypes": {}},
     "PHENOTYPE_NOT_PROVIDED",
     "a single-gene axis with no observation",
     "a single-gene drug must refuse when its gene is absent"),
    ("WARFARIN-OUT-OF-SCOPE",
     {"care_setting": None, "medications": ["DRUG:warfarin"],
      "phenotypes": {"GENE:CYP2C19": "POOR"}},
     "DRUG_NOT_IN_CANONICAL_DATASET",
     "warfarin is outside the four-drug first-release scope",
     "an out-of-scope drug must refuse, not be silently dropped"),
    ("TAMOXIFEN-OUT-OF-SCOPE",
     {"care_setting": None, "medications": ["DRUG:tamoxifen"],
      "phenotypes": {"GENE:CYP2D6": "POOR"}},
     "DRUG_NOT_IN_CANONICAL_DATASET",
     "as above, on the other gene",
     "the refusal must not depend on the gene"),
    ("CODEINE-WRONG-GENE",
     {"care_setting": None, "medications": ["DRUG:codeine"],
      "phenotypes": {"GENE:CYP2C19": "POOR"}},
     "PHENOTYPE_NOT_PROVIDED",
     "codeine's evidence axis is CYP2D6; a CYP2C19 observation is not it",
     "an observation on a gene the drug's axis does not name must not be used"),
    ("OMEPRAZOLE-WRONG-GENE",
     {"care_setting": None, "medications": ["DRUG:omeprazole"],
      "phenotypes": {"GENE:CYP2D6": "POOR"}},
     "PHENOTYPE_NOT_PROVIDED",
     "as above, with the genes exchanged",
     "the refusal must not depend on which gene was supplied"),
    ("CLOPIDOGREL-NO-GENE-NO-SETTING",
     {"care_setting": None, "medications": ["DRUG:clopidogrel"],
      "phenotypes": {}},
     "CARE_SETTING_NOT_DECLARED",
     "two reasons to refuse at once",
     "the care-setting refusal must come first, because without it the "
     "question of which column applies has not been settled"),
    ("CLOPIDOGREL-SETTING-NO-GENE",
     {"care_setting": "ACS_OR_PCI", "medications": ["DRUG:clopidogrel"],
      "phenotypes": {}},
     "PHENOTYPE_NOT_PROVIDED",
     "the care setting is declared and the gene is absent",
     "declaring a care setting must not substitute for an observation"),
    ("CODEINE-INDETERMINATE",
     {"care_setting": None, "medications": ["DRUG:codeine"],
      "phenotypes": {"GENE:CYP2D6": "INDETERMINATE"}},
     "PHENOTYPE_NOT_PROVIDED",
     "CPIC states no recommendation for an indeterminate CYP2D6 phenotype",
     "an indeterminate observation must not be treated as a phenotype"),
    ("OMEPRAZOLE-INDETERMINATE",
     {"care_setting": None, "medications": ["DRUG:omeprazole"],
      "phenotypes": {"GENE:CYP2C19": "INDETERMINATE"}},
     "PHENOTYPE_NOT_PROVIDED",
     "as above, on the other gene",
     "the refusal must not depend on the gene"),
    ("AMITRIPTYLINE-ONE-INDETERMINATE",
     {"care_setting": None, "medications": ["DRUG:amitriptyline"],
      "phenotypes": {"GENE:CYP2C19": "INDETERMINATE",
                     "GENE:CYP2D6": "NORMAL"}},
     "PHENOTYPE_NOT_PROVIDED",
     "one axis of a two-gene matrix is indeterminate",
     "a joint rule must refuse when one axis cannot be determined, and must "
     "not answer from the axis that could"),
    ("AMITRIPTYLINE-2C19-RAPID-2D6-RAPID",
     {"care_setting": None, "medications": ["DRUG:amitriptyline"],
      "phenotypes": {"GENE:CYP2C19": "RAPID", "GENE:CYP2D6": "RAPID"}},
     "PHENOTYPE_NOT_SUPPORTED",
     "CYP2C19 rapid is supported and CYP2D6 rapid is not",
     "a joint rule must refuse when either axis is unsupported, even when the "
     "other is a phenotype the guideline does answer"),
    ("TWO-OUT-OF-SCOPE-DRUGS",
     {"care_setting": None,
      "medications": ["DRUG:tamoxifen", "DRUG:warfarin"],
      "phenotypes": {"GENE:CYP2C19": "POOR", "GENE:CYP2D6": "POOR"}},
     "DRUG_NOT_IN_CANONICAL_DATASET",
     "neither drug is in the four-drug first-release scope",
     "a request that can answer nothing must report nothing, not an empty "
     "reassurance"),
    ("AMITRIPTYLINE-WRONG-GENES-ONLY",
     {"care_setting": None, "medications": ["DRUG:amitriptyline"],
      "phenotypes": {"GENE:CYP2C9": "POOR"}},
     "PHENOTYPE_NOT_PROVIDED",
     "an observation on a gene outside the first-release scope entirely",
     "an out-of-scope gene must not satisfy an axis"),
    ("CODEINE-AND-AMITRIPTYLINE-ONE-GENE",
     {"care_setting": None,
      "medications": ["DRUG:amitriptyline", "DRUG:codeine"],
      "phenotypes": {"GENE:CYP2D6": "POOR"}},
     "PHENOTYPE_NOT_PROVIDED",
     "codeine can be answered from CYP2D6 alone; amitriptyline cannot",
     "one drug answering must not cause the other to be answered from the "
     "same single observation"),
)


def _holdout_cases(release_id: str, manifest_hash: str) -> List[Wave4Case]:
    cases: List[Wave4Case] = []
    for index, (slug, request, reason, source, why) in enumerate(
            _HOLDOUT_SPECS, 1):
        payload = dict(request)
        payload["mode"] = "VALIDATION"
        cases.append(_case(
            case_id="PGX-VAL-W4-INT-%02d-%s" % (index, slug),
            role=ValidationCaseRole.INTERNAL_HOLDOUT,
            request=payload,
            expected={"outcome": "REFUSE", "reason_code": reason,
                      "attention_level": "NOT_ASSESSED"},
            question=("does the candidate release refuse this input, with "
                      "this reason, and without reporting an attention "
                      "level?"),
            source_identity="first-release refusal surface: %s" % slug,
            derivation_method=("derived from the first-release scope "
                               "decisions and the guideline's silences, not "
                               "from any rule's outcome"),
            derived_from_development=False,
            citation=source,
            visibility=VisibilityLevel.RESTRICTED,
            release_id=release_id, manifest_hash=manifest_hash,
            title=slug.replace("-", " ").lower(),
            notes=why))
    return cases


#: Reserved for a later external reviewer. Inputs and questions only.
#:
#: **Every request here is structurally distinct from every development case.**
#: The first version of this list asked good questions about single-drug
#: combinations, and the separation audit refused it: the development partition
#: enumerates every combination the rules encode, so any single-drug request
#: about a covered combination has the same content fingerprint as a case the
#: build has already been scored on. A reserved case that duplicates a
#: development case tells a reviewer nothing the build has not already seen.
#:
#: So these are multi-drug requests, requests carrying an observation on a gene
#: the drug's axis does not name, and requests mixing covered and uncovered
#: drugs - shapes the development partition does not contain, and shapes a
#: real user would produce.
_EXPERT_SPECS: Tuple[Tuple[str, Dict[str, Any], str], ...] = (
    ("TWO-DRUGS-ONE-GENE",
     {"care_setting": "ACS_OR_PCI",
      "medications": ["DRUG:clopidogrel", "DRUG:omeprazole"],
      "phenotypes": {"GENE:CYP2C19": "POOR"}},
     "two drugs sharing one gene, in opposite directions - clopidogrel needs "
     "activation and omeprazole is cleared. Is reporting them separately, "
     "with no interaction claim, the right product behaviour?"),
    ("TWO-DRUGS-ONE-GENE-NORMAL",
     {"care_setting": "ACS_OR_PCI",
      "medications": ["DRUG:clopidogrel", "DRUG:omeprazole"],
      "phenotypes": {"GENE:CYP2C19": "NORMAL"}},
     "the same pair on a normal metabolizer: is the difference between the "
     "two answers legible to a clinician reading the output?"),
    ("ALL-FOUR-DRUGS",
     {"care_setting": "ACS_OR_PCI",
      "medications": ["DRUG:amitriptyline", "DRUG:clopidogrel",
                      "DRUG:codeine", "DRUG:omeprazole"],
      "phenotypes": {"GENE:CYP2C19": "POOR", "GENE:CYP2D6": "POOR"}},
     "the whole first-release scope at once, with both genes poor. Is the "
     "aggregate presentation honest about which answers are findings and "
     "which are refusals?"),
    ("ALL-FOUR-DRUGS-MIXED",
     {"care_setting": "ACS_OR_PCI",
      "medications": ["DRUG:amitriptyline", "DRUG:clopidogrel",
                      "DRUG:codeine", "DRUG:omeprazole"],
      "phenotypes": {"GENE:CYP2C19": "ULTRARAPID",
                     "GENE:CYP2D6": "INTERMEDIATE"}},
     "the same four drugs with mixed phenotypes: does the highest attention "
     "level dominating the summary hide the drugs that were refused?"),
    ("COVERED-AND-OUT-OF-SCOPE",
     {"care_setting": None,
      "medications": ["DRUG:codeine", "DRUG:warfarin"],
      "phenotypes": {"GENE:CYP2D6": "POOR"}},
     "one covered drug and one out of scope: is the partial answer presented "
     "so that a reader cannot mistake it for a whole one?"),
    ("COVERED-AND-TWO-OUT-OF-SCOPE",
     {"care_setting": None,
      "medications": ["DRUG:codeine", "DRUG:tamoxifen", "DRUG:warfarin"],
      "phenotypes": {"GENE:CYP2D6": "ULTRARAPID"}},
     "one covered drug and two out of scope, on a phenotype the guideline "
     "treats as a toxicity risk: does the refusal noise obscure the finding?"),
    ("EXTRA-GENE-OBSERVED",
     {"care_setting": None, "medications": ["DRUG:codeine"],
      "phenotypes": {"GENE:CYP2C19": "POOR", "GENE:CYP2D6": "NORMAL"}},
     "an observation is supplied for a gene codeine's axis does not name. It "
     "is ignored. Should the output say so, rather than silently using only "
     "what it needed?"),
    ("EXTRA-GENE-OBSERVED-CLOPIDOGREL",
     {"care_setting": "ACS_OR_PCI", "medications": ["DRUG:clopidogrel"],
      "phenotypes": {"GENE:CYP2C19": "INTERMEDIATE", "GENE:CYP2D6": "POOR"}},
     "as above, where the ignored observation is one a clinician might expect "
     "to matter. Is silence the right behaviour?"),
    ("AMITRIPTYLINE-WITH-A-SECOND-DRUG",
     {"care_setting": None,
      "medications": ["DRUG:amitriptyline", "DRUG:codeine"],
      "phenotypes": {"GENE:CYP2C19": "INTERMEDIATE",
                     "GENE:CYP2D6": "INTERMEDIATE"}},
     "a joint two-gene drug beside a single-gene one, on the cell where "
     "combining single-gene readings would have given a different answer from "
     "the guideline's joint table. Is the joint answer the right one, and is "
     "it distinguishable in the output from the single-gene one beside it?"),
    ("IRRELEVANT-CARE-SETTING",
     {"care_setting": "ACS_OR_PCI",
      "medications": ["DRUG:amitriptyline", "DRUG:omeprazole"],
      "phenotypes": {"GENE:CYP2C19": "NORMAL", "GENE:CYP2D6": "NORMAL"}},
     "a care setting is supplied for two drugs that do not require one. It is "
     "ignored. Should the release refuse an irrelevant qualifier instead?"),
    ("NO-ACTIVE-ATTENTION-BESIDE-A-REFUSAL",
     {"care_setting": None,
      "medications": ["DRUG:codeine", "DRUG:clopidogrel"],
      "phenotypes": {"GENE:CYP2D6": "NORMAL", "GENE:CYP2C19": "NORMAL"}},
     "one drug reports NO_ACTIVE_ATTENTION and the other refuses for want of "
     "a care setting. Are the two distinguishable enough in the product's own "
     "output that a clinician will not read the refusal as reassurance?"),
    ("EVERY-AXIS-REFUSED",
     {"care_setting": None,
      "medications": ["DRUG:clopidogrel", "DRUG:warfarin"],
      "phenotypes": {"GENE:CYP2D6": "RAPID"}},
     "nothing can be answered: one drug lacks its care setting, the other is "
     "out of scope, and the only observation is on an unsupported phenotype "
     "of an unrelated gene. Is a wholly empty result presented as clearly not "
     "an assessment?"),
)


def _expert_cases(release_id: str, manifest_hash: str) -> List[Wave4Case]:
    cases: List[Wave4Case] = []
    for index, (slug, request, question) in enumerate(_EXPERT_SPECS, 1):
        payload = dict(request)
        payload["mode"] = "VALIDATION"
        cases.append(_case(
            case_id="PGX-VAL-W4-EXP-%02d-%s" % (index, slug),
            role=ValidationCaseRole.EXPERT_HOLDOUT,
            request=payload,
            expected=None,
            question=question,
            source_identity="reserved external-expert question: %s" % slug,
            derivation_method=("chosen to put a question to an external "
                               "reviewer; no expected answer is recorded, "
                               "because recording one would invent the "
                               "judgment the reviewer is being asked for"),
            derived_from_development=False,
            citation=("CPIC first-release scope; see "
                      "docs/closure/wave-03b-integration-report.md"),
            visibility=VisibilityLevel.RESTRICTED,
            release_id=release_id, manifest_hash=manifest_hash,
            title=slug.replace("-", " ").lower(),
            notes=("reserved and unopened; this wave listed its metadata and "
                   "did not evaluate the build against it")))
    return cases


def build_catalogue(release_id: str, manifest_hash: str,
                    ruleset) -> Tuple[Wave4Case, ...]:
    cases = (_dev_cases(release_id, manifest_hash, ruleset)
             + _holdout_cases(release_id, manifest_hash)
             + _expert_cases(release_id, manifest_hash))
    identifiers = [case.metadata.case_id.value for case in cases]
    if len(set(identifiers)) != len(identifiers):
        duplicates = sorted({i for i in identifiers
                             if identifiers.count(i) > 1})
        raise ValueError("duplicate case identifiers: %s" % duplicates)
    for case in cases:
        if case.metadata.role is ValidationCaseRole.EXPERT_HOLDOUT \
                and case.expected is not None:
            raise ValueError(
                "%s carries an expected answer; a reserved expert case must "
                "not, because recording one invents the judgment the reviewer "
                "is being asked for" % case.metadata.case_id.value)
    return tuple(cases)
