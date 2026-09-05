# -*- coding: utf-8 -*-
"""Comparing V2 phenotype semantics with the legacy engine's (WP-12).

The legacy matcher is `risk_engine.phenotype_matches`, which normalises both
sides through a synonym table and then consults `PROFILE_MATCH_GROUPS`. Two of
its behaviours are defects this work package exists to remove:

* `rapid` accepts a rule written for `ultrarapid` and the reverse
  (`LEGACY-BUG-001`, `SAFETY-INV-004`);
* `poor` and `intermediate` accept a rule written for the invented group
  `decreased_function`, which the P0 phenotype model does not have.

**Why the legacy module is not imported here.** `pgx/engine` is production
code and must not depend on a legacy script; a boundary test asserts that. So
the legacy behaviour is *transcribed* below, from
`risk_engine.PROFILE_MATCH_GROUPS` and `risk_engine.normalize_profile_phenotype`,
and a test in `tests/unit/engine/` imports the real module and asserts the
transcription still agrees with it. If somebody edits the legacy table, that
test fails rather than this comparison quietly describing behaviour the legacy
engine no longer has.

Nothing here compares clinical output. There is no approved ruleset to compare
against, so the comparison is at the level of normalisation and matcher
semantics only.
"""

from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Mapping, Optional, Sequence, Tuple

from pgx.domain.enums import Phenotype
from pgx.domain.hashing import sha256_digest
from pgx.engine.phenotype import match_observation
from pgx.engine.phenotype_errors import PhenotypeProfileError
from pgx.engine.phenotype_models import PhenotypeObservation, PhenotypeProfile
from pgx.engine.phenotype_normalization import (INPUT_CONTRACT_VERSION,
                                                normalize_phenotype,
                                                normalize_profile)
from pgx.rules.conditions import PhenotypeMatch

__all__ = [
    "ALLOWLIST_SCHEMA_VERSION",
    "EXPECTED_DIFFERENCES",
    "LEGACY_MATCH_GROUPS",
    "LEGACY_PROFILE_SYNONYMS",
    "REGRESSION_REPORT_VERSION",
    "build_regression_report",
    "expected_difference_allowlist",
    "legacy_matches",
    "legacy_normalize_profile_phenotype",
    "load_demo_profiles",
]

REGRESSION_REPORT_VERSION = "pgx-phenotype-regression-report/1"
ALLOWLIST_SCHEMA_VERSION = "pgx-phenotype-regression-allowlist/1"

#: Transcribed from ``risk_engine.PROFILE_MATCH_GROUPS``. Read it as evidence
#: of what the legacy engine does, not as anything V2 consults: no code path
#: in ``pgx/engine`` outside this module's comparison functions reads it.
LEGACY_MATCH_GROUPS: Mapping[str, FrozenSet[str]] = {
    "poor": frozenset({"poor", "decreased_function"}),
    "intermediate": frozenset({"intermediate", "decreased_function"}),
    "normal": frozenset(),
    "rapid": frozenset({"rapid", "ultrarapid"}),
    "ultrarapid": frozenset({"ultrarapid", "rapid"}),
    "decreased_function": frozenset({"poor", "intermediate",
                                     "decreased_function"}),
}

#: The exact-token half of ``risk_engine.normalize_profile_phenotype``. Its
#: substring fallbacks are transcribed separately below, because the substring
#: behaviour is itself one of the things being reported on.
LEGACY_PROFILE_SYNONYMS: Mapping[str, str] = {
    "pm": "poor", "poor": "poor", "poor metabolizer": "poor",
    "zayif": "poor", "zayıf": "poor",
    "im": "intermediate", "intermediate": "intermediate",
    "intermediate metabolizer": "intermediate", "orta": "intermediate",
    "nm": "normal", "normal": "normal", "normal metabolizer": "normal",
    "rm": "rapid", "rapid": "rapid", "rapid metabolizer": "rapid",
    "hizli": "rapid", "hızlı": "rapid",
    "um": "ultrarapid", "ultrarapid": "ultrarapid",
    "ultra rapid": "ultrarapid", "ultrarapid metabolizer": "ultrarapid",
    "ultra-rapid metabolizer": "ultrarapid",
}

#: The ordered substring fallbacks, transcribed in the legacy order because
#: the order decides the answer: ``"ultrarapid"`` is tested before ``"rapid"``,
#: and reversing them would make every ultrarapid value legacy-``rapid``.
_LEGACY_SUBSTRING_RULES: Tuple[Tuple[str, str], ...] = (
    ("poor", "poor"), ("intermediate", "intermediate"),
    ("ultrarapid", "ultrarapid"), ("ultra-rapid", "ultrarapid"),
    ("rapid", "rapid"), ("normal", "normal"),
    ("decreased", "decreased_function"),
)


def legacy_normalize_profile_phenotype(value: Any) -> str:
    """Transcription of ``risk_engine.normalize_profile_phenotype``.

    Including the substring pass, which is what makes ``"poor response"``
    legacy-``poor``. V2 has no equivalent and never will: a value is a
    canonical token or it is unsupported.
    """
    folded = " ".join(str(value or "").split()).lower()
    if folded in LEGACY_PROFILE_SYNONYMS:
        return LEGACY_PROFILE_SYNONYMS[folded]
    for needle, mapped in _LEGACY_SUBSTRING_RULES:
        if needle in folded:
            return mapped
    return folded


def legacy_matches(profile_value: Any, rule_group: str) -> bool:
    """Transcription of ``risk_engine.phenotype_matches`` for the phenotype
    half. Rule-group normalisation is applied to the group as the legacy
    engine applies it."""
    left = legacy_normalize_profile_phenotype(profile_value)
    right = legacy_normalize_profile_phenotype(rule_group)
    if not left or not right:
        return False
    return right in LEGACY_MATCH_GROUPS.get(left, frozenset({left}))


# ---------------------------------------------------------------------------
# the allowlist of differences that are supposed to exist
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ExpectedDifference:
    """One intentional divergence from legacy matcher behaviour.

    Every field is required. A difference without a safety rationale is a
    difference nobody justified, and a difference without a selector is one
    the harness cannot check for - either would make the allowlist a place to
    hide a regression rather than a record of a decision.
    """

    difference_id: str
    legacy_bug_id: str
    observed_legacy_behavior: str
    required_v2_behavior: str
    safety_rationale: str
    reference: str
    comparison_selector: Mapping[str, Any]
    expected_status: str

    def to_json(self) -> Dict[str, Any]:
        return {
            "difference_id": self.difference_id,
            "legacy_bug_id": self.legacy_bug_id,
            "observed_legacy_behavior": self.observed_legacy_behavior,
            "required_v2_behavior": self.required_v2_behavior,
            "safety_rationale": self.safety_rationale,
            "reference": self.reference,
            "comparison_selector": dict(self.comparison_selector),
            "expected_status": self.expected_status,
        }


EXPECTED_DIFFERENCES: Tuple[ExpectedDifference, ...] = (
    ExpectedDifference(
        difference_id="LEGACY-BUG-001-RAPID-TO-ULTRARAPID",
        legacy_bug_id="LEGACY-BUG-001",
        observed_legacy_behavior=(
            "a RAPID profile value satisfies a rule group written for "
            "ULTRARAPID, because PROFILE_MATCH_GROUPS['rapid'] contains "
            "'ultrarapid'"),
        required_v2_behavior=(
            "NO_MATCH. A rule covering both phenotypes must declare both in a "
            "ONE_OF set"),
        safety_rationale=(
            "implicit equivalence applies a rule outside the evidence it was "
            "written from, which is an unreviewed scientific claim"),
        reference="SAFETY-INV-004; architecture.md 9.1",
        comparison_selector={"observed": "RAPID", "operator": "EXACT",
                             "declared": ["ULTRARAPID"]},
        expected_status="NO_MATCH"),
    ExpectedDifference(
        difference_id="LEGACY-BUG-001-ULTRARAPID-TO-RAPID",
        legacy_bug_id="LEGACY-BUG-001",
        observed_legacy_behavior=(
            "an ULTRARAPID profile value satisfies a rule group written for "
            "RAPID, because PROFILE_MATCH_GROUPS['ultrarapid'] contains "
            "'rapid'"),
        required_v2_behavior=(
            "NO_MATCH. The reverse direction is a separate entry because the "
            "legacy table states it separately, and a fix that closed only one "
            "direction would satisfy a single-entry allowlist"),
        safety_rationale=(
            "same defect, opposite direction; both must be closed or a rule "
            "still fires for a phenotype nobody reviewed it against"),
        reference="SAFETY-INV-004; architecture.md 9.1",
        comparison_selector={"observed": "ULTRARAPID", "operator": "EXACT",
                             "declared": ["RAPID"]},
        expected_status="NO_MATCH"),
    ExpectedDifference(
        difference_id="LEGACY-NORMAL-PHENOTYPE-SUPPRESSED",
        legacy_bug_id="LEGACY-BUG-001",
        observed_legacy_behavior=(
            "PROFILE_MATCH_GROUPS['normal'] is the empty set, so a NORMAL "
            "profile value satisfies no rule at all - including a rule written "
            "for NORMAL"),
        required_v2_behavior=(
            "MATCH. NORMAL equals NORMAL; whether a matched rule warrants any "
            "attention is carried by the rule's own outcome, which may be "
            "NO_ACTIVE_ATTENTION, and is decided downstream"),
        safety_rationale=(
            "the legacy table answers 'should this raise a flag?' inside a "
            "function that is asked 'is this the same phenotype?'. Suppressing "
            "the match makes an evaluated rule indistinguishable from an axis "
            "no rule covered, which is the false-reassurance failure "
            "SAFETY-INV-001 exists to prevent. V2 separates the two: equality "
            "here, attention in WP-14"),
        reference="SAFETY-INV-001; architecture.md 9.1, 9.3",
        comparison_selector={"observed": "NORMAL", "operator": "EXACT",
                             "declared": ["NORMAL"]},
        expected_status="MATCH"),
    ExpectedDifference(
        difference_id="LEGACY-BROAD-DECREASED-FUNCTION-GROUPING",
        legacy_bug_id="LEGACY-BUG-001",
        observed_legacy_behavior=(
            "POOR and INTERMEDIATE both satisfy a rule group written for the "
            "invented group 'decreased_function', and a supplied value "
            "containing 'decreased' becomes that group"),
        required_v2_behavior=(
            "'decreased_function' is not a phenotype and is not a rule "
            "vocabulary member: as an input it is UNSUPPORTED, and no "
            "condition can declare it"),
        safety_rationale=(
            "the P0 phenotype model has six members and this is not one of "
            "them; expanding a broad functional group into POOR or "
            "INTERMEDIATE invents a mapping no curator made"),
        reference="architecture.md 9.1; SAFETY-INV-004",
        comparison_selector={"observed_raw": "decreased_function",
                             "expected_normalization_status": "UNSUPPORTED"},
        expected_status="UNSUPPORTED"),
)


def expected_difference_allowlist() -> Dict[str, Any]:
    """The allowlist as a published document."""
    return {
        "allowlist_schema_version": ALLOWLIST_SCHEMA_VERSION,
        "entry_count": len(EXPECTED_DIFFERENCES),
        "entries": [entry.to_json() for entry in EXPECTED_DIFFERENCES],
        "policy": (
            "An entry records a difference between legacy and V2 matcher "
            "semantics that is intended. The harness fails if an entry's "
            "difference stops appearing, if a difference appears that no entry "
            "covers, or if the report is not reproducible byte for byte. An "
            "allowlist that could absorb a new difference silently would be a "
            "way of hiding a regression rather than a record of a decision."),
    }


# ---------------------------------------------------------------------------
# the P1-P6 comparison
# ---------------------------------------------------------------------------

DEMO_PROFILES_RELATIVE = os.path.join("clinpgx_mvp_seed",
                                      "mvp_demo_profiles.json")

#: The phenotype pairs the report walks for every profile value. Declared
#: rather than generated from the enum so the report's shape is stable when
#: the enum is read in a different order.
from pgx.rules.conditions import RULE_PHENOTYPES  # noqa: E402  (after consts)


def load_demo_profiles(repo_root: str = ".") -> Dict[str, Any]:
    """Read the legacy demo profiles, read-only.

    The file is a WP-01 protected legacy artifact. It is opened for reading
    and never written; a test asserts its digest is unchanged by this harness.
    """
    path = os.path.join(repo_root, DEMO_PROFILES_RELATIVE)
    if not os.path.isfile(path):
        raise PhenotypeProfileError(
            "legacy demo profiles not found at %s" % path,
            code="PHENOTYPE_LEGACY_PROFILES_MISSING", location=path)
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _exact(phenotype: Phenotype) -> PhenotypeMatch:
    return PhenotypeMatch(operator="EXACT", values=(phenotype,))


def _one_of(*phenotypes: Phenotype) -> PhenotypeMatch:
    return PhenotypeMatch(operator="ONE_OF", values=tuple(phenotypes))


def _match_rows(observation: PhenotypeObservation) -> Tuple[Dict[str, Any], ...]:
    """Every EXACT comparison for one observation, plus the RAPID/ULTRARAPID
    ONE_OF case, with the legacy answer beside the V2 answer."""
    rows = []
    for declared in RULE_PHENOTYPES:
        decision = match_observation(observation, _exact(declared))
        legacy = legacy_matches(observation.raw_value, declared.value)
        rows.append({
            "operator": "EXACT",
            "declared": [declared.value],
            "legacy_matched": bool(legacy),
            "v2_status": decision.status,
            "v2_matched": decision.matched,
            "differs": bool(legacy) != decision.matched,
        })
    both = _one_of(Phenotype.RAPID, Phenotype.ULTRARAPID)
    decision = match_observation(observation, both)
    legacy_pair = (legacy_matches(observation.raw_value, "rapid")
                   or legacy_matches(observation.raw_value, "ultrarapid"))
    rows.append({
        "operator": "ONE_OF",
        "declared": [Phenotype.RAPID.value, Phenotype.ULTRARAPID.value],
        "legacy_matched": bool(legacy_pair),
        "v2_status": decision.status,
        "v2_matched": decision.matched,
        "differs": bool(legacy_pair) != decision.matched,
    })
    return tuple(rows)


def _difference_id_for(observed: Optional[str], row: Mapping[str, Any]
                       ) -> Optional[str]:
    """Which allowlist entry covers this difference, if any."""
    for entry in EXPECTED_DIFFERENCES:
        selector = entry.comparison_selector
        if "observed" not in selector:
            continue
        if (selector["observed"] == observed
                and selector.get("operator") == row["operator"]
                and list(selector.get("declared", ())) == list(row["declared"])):
            return entry.difference_id
    return None


def build_regression_report(repo_root: str = ".") -> Dict[str, Any]:
    """The deterministic P1-P6 comparison.

    Every profile, every gene, the V2 normalisation verdict, the legacy
    normalisation verdict, and every exact-match comparison with both answers
    side by side. Sorted throughout and carrying no timestamp, no path and no
    host, so two runs on two machines produce identical bytes.
    """
    profiles = load_demo_profiles(repo_root)
    rows = []
    unexpected: list = []
    covered: Dict[str, int] = {entry.difference_id: 0
                               for entry in EXPECTED_DIFFERENCES}

    for profile_id in sorted(profiles):
        raw_profile = profiles[profile_id]
        raw_phenotypes = raw_profile.get("phenotypes", {})
        profile = normalize_profile(
            raw_phenotypes, profile_id=profile_id,
            metadata={"profile_name": raw_profile.get("profile_name"),
                      "demo_use": raw_profile.get("demo_use")})
        genes = []
        for observation in profile.observations:
            raw_value = observation.raw_value
            legacy_token = legacy_normalize_profile_phenotype(raw_value)
            match_rows = _match_rows(observation)
            for row in match_rows:
                if not row["differs"]:
                    continue
                difference_id = _difference_id_for(
                    observation.phenotype.value if observation.phenotype
                    else None, row)
                if difference_id is None:
                    unexpected.append({
                        "profile_id": profile_id,
                        "gene_id": observation.gene_canonical_key,
                        "observed": (observation.phenotype.value
                                     if observation.phenotype else None),
                        "operator": row["operator"],
                        "declared": row["declared"],
                        "legacy_matched": row["legacy_matched"],
                        "v2_status": row["v2_status"],
                    })
                else:
                    covered[difference_id] += 1
                    row["expected_difference_id"] = difference_id
            genes.append({
                "gene_id": observation.gene_canonical_key,
                "raw_value": raw_value,
                "v2_status": observation.status,
                "v2_phenotype": (observation.phenotype.value
                                 if observation.phenotype else None),
                "v2_reason_code": observation.reason_code,
                "legacy_normalized": legacy_token,
                "match_rows": list(match_rows),
            })
        rows.append({
            "profile_id": profile_id,
            "profile_content_hash": profile.content_hash(),
            "gene_count": len(genes),
            "genes": genes,
        })

    # The two synthetic cross-match cases. The demo profiles contain no RAPID
    # value, so LEGACY-BUG-001's first direction cannot be observed from P1-P6
    # alone - which is exactly what WP-01 recorded when it registered the bug
    # without a selector. These rows supply the missing direction explicitly,
    # marked as constructed rather than read from the profiles.
    cross = []
    for observed, declared in ((Phenotype.RAPID, Phenotype.ULTRARAPID),
                               (Phenotype.ULTRARAPID, Phenotype.RAPID)):
        observation = normalize_phenotype(
            observed.value, gene_canonical_key="GENE:CYP2D6")
        decision = match_observation(observation, _exact(declared))
        legacy = legacy_matches(observed.value, declared.value)
        difference_id = _difference_id_for(observed.value, {
            "operator": "EXACT", "declared": [declared.value]})
        if legacy != decision.matched and difference_id:
            covered[difference_id] += 1
        cross.append({
            "case": "constructed",
            "observed": observed.value,
            "operator": "EXACT",
            "declared": [declared.value],
            "legacy_matched": bool(legacy),
            "v2_status": decision.status,
            "v2_matched": decision.matched,
            "differs": bool(legacy) != decision.matched,
            "expected_difference_id": difference_id,
        })
    both = match_observation(
        normalize_phenotype("RAPID", gene_canonical_key="GENE:CYP2D6"),
        _one_of(Phenotype.RAPID, Phenotype.ULTRARAPID))
    cross.append({
        "case": "constructed",
        "observed": Phenotype.RAPID.value,
        "operator": "ONE_OF",
        "declared": [Phenotype.RAPID.value, Phenotype.ULTRARAPID.value],
        "legacy_matched": True,
        "v2_status": both.status,
        "v2_matched": both.matched,
        "differs": False,
        "expected_difference_id": None,
    })

    # The broad-group case, likewise constructed: no demo profile supplies
    # "decreased_function", and the legacy engine would map it to a group V2
    # does not have.
    broad_observation = normalize_phenotype(
        "decreased_function", gene_canonical_key="GENE:CYP2C9")
    broad = {
        "case": "constructed",
        "raw_value": "decreased_function",
        "legacy_normalized": legacy_normalize_profile_phenotype(
            "decreased_function"),
        "legacy_matches_poor_rule": legacy_matches("decreased_function",
                                                   "poor"),
        "legacy_matches_intermediate_rule": legacy_matches(
            "decreased_function", "intermediate"),
        "v2_status": broad_observation.status,
        "v2_reason_code": broad_observation.reason_code,
        "v2_phenotype": None,
        "expected_difference_id": "LEGACY-BROAD-DECREASED-FUNCTION-GROUPING",
    }
    if broad_observation.status == "UNSUPPORTED":
        covered["LEGACY-BROAD-DECREASED-FUNCTION-GROUPING"] += 1

    missing = sorted(name for name, count in covered.items() if count == 0)

    report: Dict[str, Any] = {
        "report_schema_version": REGRESSION_REPORT_VERSION,
        "input_contract_version": INPUT_CONTRACT_VERSION,
        "source_profiles": DEMO_PROFILES_RELATIVE,
        "profile_count": len(rows),
        "profiles": rows,
        "constructed_cross_match_cases": cross,
        "constructed_broad_group_case": broad,
        "expected_differences": [entry.to_json()
                                 for entry in EXPECTED_DIFFERENCES],
        "expected_difference_hits": dict(sorted(covered.items())),
        "expected_differences_not_observed": missing,
        "unexpected_differences": sorted(
            unexpected,
            key=lambda item: (item["profile_id"], item["gene_id"],
                              item["operator"], tuple(item["declared"]))),
        "note": (
            "This report compares phenotype normalisation and matcher "
            "semantics only. It compares no clinical output, because no "
            "approved ruleset exists to produce one. A difference listed here "
            "is a difference in how a value is read or compared, never a "
            "statement about any medicine."),
    }
    report["content_hash"] = sha256_digest(
        {key: value for key, value in report.items() if key != "content_hash"})
    return report
