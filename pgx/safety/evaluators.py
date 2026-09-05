# -*- coding: utf-8 -*-
"""The twelve detectors, written against injected subjects.

Every evaluator here takes the thing it judges as an **argument** rather than
importing it. That single decision is what makes a negative control mean
something: the real implementation and the deliberately unsafe double go
through the *same* function, and the function's answer is the evidence.

Written the other way - each evaluator importing the production module it
checks - a mutant could only ever be inspected, never evaluated, and
"the fixture contains the string 'safety score'" would be standing in for
"the detector rejects a safety score". Those are not the same claim, and only
one of them is worth a release gate.

Each returns a ``Verdict``: compliant or not, a stable refusal code, and the
observations behind it. No evaluator raises on unsafe input - unsafe input is
the expected case half the time, and an exception would be indistinguishable
from a detector that crashed.

Framework-free, offline, no database, no model. Every evaluator is a pure
function of its arguments.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import (Any, Callable, Dict, Iterable, List, Mapping, Optional,
                    Sequence, Tuple)

from pgx.safety.vocabulary import InvariantId

__all__ = [
    "Verdict",
    "evaluate_absence_never_reassures",
    "evaluate_renderer_preserves_facts",
    "evaluate_only_validated_rules_execute",
    "evaluate_phenotype_matching_is_exact",
    "evaluate_no_candidate_preference",
    "evaluate_findings_are_evidence_backed",
    "evaluate_persistence_requires_complete_bundle",
    "evaluate_conflict_is_preserved",
    "evaluate_partition_separation",
    "evaluate_no_prohibited_claim",
    "evaluate_no_real_patient_data",
    "evaluate_deterministic_result",
    "EVALUATORS",
]


@dataclass(frozen=True)
class Verdict:
    """What one evaluator concluded about one subject."""

    invariant_id: InvariantId
    compliant: bool
    #: Empty when compliant. Otherwise the stable code from the registry.
    refusal_code: str = ""
    #: One line naming the specific unsafe observation, for a human.
    detail: str = ""
    #: How many cases were examined. A verdict from an empty sweep is not a
    #: pass, and callers check this rather than trusting ``compliant``.
    examined: int = 0
    violations: Tuple[str, ...] = ()

    @property
    def is_meaningful(self) -> bool:
        """Whether anything was actually examined."""
        return self.examined > 0

    def as_document(self) -> Dict[str, Any]:
        return {
            "compliant": self.compliant,
            "detail": self.detail,
            "examined": self.examined,
            "invariant_id": self.invariant_id.value,
            "refusal_code": self.refusal_code,
            "violations": list(self.violations),
        }


def _verdict(invariant: InvariantId, code: str, examined: int,
             violations: Sequence[str]) -> Verdict:
    if violations:
        return Verdict(invariant, False, code, violations[0], examined,
                       tuple(violations))
    return Verdict(invariant, True, "", "", examined, ())


# ---------------------------------------------------------------------------
# SAFETY-INV-001 - absence must never read as reassurance
# ---------------------------------------------------------------------------

#: The two answers that tell a reader "nothing to worry about here".
_REASSURING = ("LOW", "NO_ACTIVE_ATTENTION")


def evaluate_absence_never_reassures(
        aggregator: Callable[..., Any],
        coverage_values: Sequence[Any],
        level_values: Sequence[Any],
        full_status: Any) -> Verdict:
    """No absence path may produce ``LOW`` or ``NO_ACTIVE_ATTENTION``.

    ``aggregator(levels, coverage=...)`` is the subject. Swept over every
    coverage status with **no calculated levels** - which is what absence looks
    like to the aggregator - plus every single-level case, so a subject that
    lowers a real finding because coverage was incomplete is caught too.

    ``NO_ACTIVE_ATTENTION`` is legitimate from exactly one place: ``FULL``
    coverage with nothing calculated. That is *we looked and found nothing*.
    Every other route to it is *we did not look*, dressed up.
    """
    violations: List[str] = []
    examined = 0

    for coverage in coverage_values:
        examined += 1
        try:
            answer = aggregator([], coverage=coverage)
        except Exception as exc:  # a subject that raises has not answered
            violations.append("empty levels with coverage %s raised %s: %s"
                              % (coverage, type(exc).__name__, exc))
            continue
        name = getattr(answer, "value", str(answer))
        if coverage == full_status:
            if name not in ("NO_ACTIVE_ATTENTION",):
                violations.append(
                    "FULL coverage with no finding produced %s; the one "
                    "legitimate reassuring answer is NO_ACTIVE_ATTENTION"
                    % name)
        elif name in _REASSURING:
            violations.append(
                "coverage %s with no calculated level produced %s - absence "
                "rendered as reassurance" % (coverage, name))

    # A real finding must survive incomplete coverage rather than being
    # softened by it.
    for coverage in coverage_values:
        for level in level_values:
            level_name = getattr(level, "value", str(level))
            if level_name in ("NOT_ASSESSED",):
                continue
            examined += 1
            try:
                answer = aggregator([level], coverage=coverage)
            except Exception as exc:
                violations.append("level %s with coverage %s raised %s"
                                  % (level_name, coverage, type(exc).__name__))
                continue
            name = getattr(answer, "value", str(answer))
            if name != level_name:
                violations.append(
                    "a calculated %s under coverage %s became %s; a finding "
                    "must not be weakened by incomplete coverage"
                    % (level_name, coverage, name))

    return _verdict(InvariantId.INV_001, "SAFETY_FALSE_REASSURANCE",
                    examined, violations)


# ---------------------------------------------------------------------------
# SAFETY-INV-002 - a renderer must not alter a calculated fact
# ---------------------------------------------------------------------------

#: Numbers followed by a dose unit. Deliberately narrow: this looks for a dose
#: the deterministic report never carried, not for every number.
_DOSE_PATTERN = re.compile(
    r"\b\d+(?:[.,]\d+)?\s?(?:mg|mcg|µg|ug|g|ml|mL|IU|ünite|unit)s?\b",
    re.IGNORECASE)


def evaluate_renderer_preserves_facts(
        renderer: Callable[[Mapping[str, Any]], str],
        reports: Sequence[Mapping[str, Any]]) -> Verdict:
    """A narration may re-word. It may not change or invent a fact.

    ``renderer(report) -> str`` is the subject; it is a **test-only double**
    in P0, because no LLM ships. The check is deliberately blunt, in the
    direction of catching too much rather than too little:

    * every attention level, coverage status and version string in the report
      must still appear in the narration;
    * a level that is *not* in the report must not appear;
    * a dose must not appear at all, because the deterministic report never
      contains one.
    """
    violations: List[str] = []
    examined = 0

    for report in reports:
        examined += 1
        try:
            narration = renderer(report)
        except Exception as exc:
            violations.append("the renderer raised %s" % type(exc).__name__)
            continue
        if narration is None:
            violations.append("the renderer produced nothing")
            continue
        text = str(narration)

        facts = report.get("facts", {})
        for key in ("attention", "coverage", "release_id", "ruleset_version"):
            expected = facts.get(key)
            if expected and str(expected) not in text:
                violations.append(
                    "the narration dropped %s %r, which the deterministic "
                    "report carried" % (key, expected))

        for forbidden in report.get("levels_not_present", ()):
            if str(forbidden) in text:
                violations.append(
                    "the narration asserts attention %r, which the "
                    "deterministic report does not contain" % forbidden)

        dose = _DOSE_PATTERN.search(text)
        if dose is not None:
            violations.append(
                "the narration introduced a dose (%r); the deterministic "
                "report contains none and no dose logic is validated"
                % dose.group(0))

    return _verdict(InvariantId.INV_002, "SAFETY_LLM_ALTERED_FACT",
                    examined, violations)


# ---------------------------------------------------------------------------
# SAFETY-INV-003 - only validated pinned rules execute
# ---------------------------------------------------------------------------

def evaluate_only_validated_rules_execute(
        selector: Callable[[Sequence[Mapping[str, Any]], str],
                           Sequence[Mapping[str, Any]]],
        rules: Sequence[Mapping[str, Any]],
        pinned_ruleset_id: str) -> Verdict:
    """Draft, curated, deprecated or unpinned rules must not participate.

    ``selector(rules, pinned_ruleset_id)`` returns the rules that would
    execute. Anything it returns whose status is not ``VALIDATED``, or whose
    ruleset is not the pinned one, is a violation.
    """
    violations: List[str] = []
    examined = 0
    try:
        executed = list(selector(rules, pinned_ruleset_id))
    except Exception as exc:
        return Verdict(InvariantId.INV_003, False,
                       "SAFETY_UNVALIDATED_RULE_EXECUTED",
                       "the rule selector raised %s" % type(exc).__name__,
                       1, ("selector raised",))

    for rule in executed:
        examined += 1
        status = str(rule.get("status", ""))
        ruleset = str(rule.get("ruleset_id", ""))
        if status != "VALIDATED":
            violations.append(
                "rule %s executed with status %s; only VALIDATED rules may "
                "participate" % (rule.get("rule_id"), status or "<missing>"))
        if ruleset != pinned_ruleset_id:
            violations.append(
                "rule %s executed from ruleset %s, which is not the pinned "
                "%s" % (rule.get("rule_id"), ruleset or "<missing>",
                        pinned_ruleset_id))

    # A selector that silently returns nothing has also failed: an invalid
    # ruleset must fail closed, not quietly produce a clean, empty answer.
    if not executed and any(rule.get("status") == "VALIDATED"
                            and rule.get("ruleset_id") == pinned_ruleset_id
                            for rule in rules):
        examined += 1
        violations.append(
            "the selector returned no rule although the pinned ruleset "
            "contains a VALIDATED one; silently filtering to an empty, "
            "reassuring result is the failure this invariant exists for")

    return _verdict(InvariantId.INV_003, "SAFETY_UNVALIDATED_RULE_EXECUTED",
                    max(examined, 1), violations)


# ---------------------------------------------------------------------------
# SAFETY-INV-004 - phenotype matching is exact
# ---------------------------------------------------------------------------

def evaluate_phenotype_matching_is_exact(
        matcher: Callable[[Any, Sequence[Any]], bool],
        phenotypes: Sequence[Any]) -> Verdict:
    """The whole matrix: a phenotype matches a rule set iff it is in it.

    Swept over every ordered pair, so ``RAPID`` against ``{ULTRARAPID}`` and
    ``ULTRARAPID`` against ``{RAPID}`` are both checked - a one-directional
    test would miss a matcher that is asymmetric.
    """
    violations: List[str] = []
    examined = 0

    for observed in phenotypes:
        for declared in phenotypes:
            examined += 1
            expected = observed == declared
            try:
                actual = bool(matcher(observed, [declared]))
            except Exception as exc:
                violations.append("matching %s against {%s} raised %s"
                                  % (observed, declared, type(exc).__name__))
                continue
            if actual != expected:
                verb = "matched" if actual else "failed to match"
                violations.append(
                    "%s %s a rule declaring {%s}; matching must be exact "
                    "string equality with no prefix, synonym or ordinal rule"
                    % (getattr(observed, "value", observed), verb,
                       getattr(declared, "value", declared)))

    # An explicit multi-phenotype rule set is legitimate and must still work.
    if len(phenotypes) >= 2:
        pair = list(phenotypes[:2])
        for observed in pair:
            examined += 1
            try:
                if not matcher(observed, pair):
                    violations.append(
                        "%s failed to match a rule explicitly declaring both "
                        "%s; an explicit set is how a rule covers two "
                        "phenotypes"
                        % (getattr(observed, "value", observed),
                           [getattr(p, "value", p) for p in pair]))
            except Exception as exc:
                violations.append("explicit-set matching raised %s"
                                  % type(exc).__name__)

    return _verdict(InvariantId.INV_004, "SAFETY_PHENOTYPE_CROSS_MATCH",
                    examined, violations)


# ---------------------------------------------------------------------------
# SAFETY-INV-005 - no candidate preference
# ---------------------------------------------------------------------------

#: Words that turn a data-availability listing into a recommendation. Turkish
#: and English, because the interface ships both.
_PREFERENCE_WORDS = (
    "safer", "safest", "preferred", "prefer", "suitable", "recommended",
    "recommend", "better", "best", "optimal", "first-line", "first line",
    "daha guvenli", "daha güvenli", "en guvenli", "en güvenli", "tercih",
    "uygun", "onerilen", "önerilen", "onerilir", "önerilir", "en iyi",
    "en uygun", "tavsiye",
)

#: Field names that encode a ranking, whatever they are called.
_SCORE_FIELDS = (
    "score", "suitability", "suitability_score", "safety_score", "ranking",
    "rank", "preference", "recommendation_score", "puan", "siralama",
    "sıralama", "uygunluk",
)


def evaluate_no_candidate_preference(
        listings: Sequence[Mapping[str, Any]]) -> Verdict:
    """A candidate listing may report data status. It may not rank or label.

    Three ways a listing becomes a recommendation, all checked: a score field,
    an ordering derived from attention, and preference language anywhere in the
    rendered strings.
    """
    violations: List[str] = []
    examined = 0

    for listing in listings:
        examined += 1
        candidates = list(listing.get("candidates", ()))

        for candidate in candidates:
            for key in candidate:
                if str(key).strip().lower() in _SCORE_FIELDS:
                    violations.append(
                        "candidate %r carries field %r; a score mixes 'we have "
                        "data' with 'this is a good option'"
                        % (candidate.get("name"), key))

        order_key = listing.get("ordered_by")
        if order_key and str(order_key).strip().lower() in (
                "attention", "attention_level", "risk", "score", "safety"):
            violations.append(
                "the listing is ordered by %r; a ranked list reads as a "
                "recommendation whatever the disclaimer says" % order_key)

        for text in listing.get("rendered_strings", ()):
            folded = str(text).lower()
            for word in _PREFERENCE_WORDS:
                if word in folded:
                    violations.append(
                        "candidate output contains %r, which labels a "
                        "candidate as preferable" % word)
                    break

    return _verdict(InvariantId.INV_005, "SAFETY_CANDIDATE_PREFERENCE",
                    examined, violations)


# ---------------------------------------------------------------------------
# SAFETY-INV-006 - every finding carries resolvable pinned evidence
# ---------------------------------------------------------------------------

def evaluate_findings_are_evidence_backed(
        emitter: Callable[[Sequence[Mapping[str, Any]], Mapping[str, Any]],
                          Sequence[Mapping[str, Any]]],
        candidate_findings: Sequence[Mapping[str, Any]],
        evidence_index: Mapping[str, Any],
        pinned_dataset_id: str) -> Verdict:
    """A finding survives only if its evidence resolves inside the pinned set.

    ``emitter(candidate_findings, evidence_index)`` returns the findings that
    would actually be released. Anything it releases whose evidence is absent,
    empty, or from another dataset version is a violation - the correct
    behaviour is to drop the finding and degrade coverage with
    ``EVIDENCE_REFERENCE_MISSING``, never to emit it with a broken chain.
    """
    violations: List[str] = []
    examined = 0
    try:
        emitted = list(emitter(candidate_findings, evidence_index))
    except Exception as exc:
        return Verdict(InvariantId.INV_006, False,
                       "SAFETY_EVIDENCE_NOT_RESOLVABLE",
                       "the finding emitter raised %s" % type(exc).__name__,
                       1, ("emitter raised",))

    for finding in emitted:
        examined += 1
        references = list(finding.get("evidence_refs", ()))
        if not references:
            violations.append(
                "finding %r was emitted with no evidence reference"
                % finding.get("finding_id"))
            continue
        for reference in references:
            record = evidence_index.get(reference)
            if record is None:
                violations.append(
                    "finding %r cites evidence %r, which resolves to nothing"
                    % (finding.get("finding_id"), reference))
                continue
            dataset = str(record.get("dataset_id", ""))
            if dataset != pinned_dataset_id:
                violations.append(
                    "finding %r cites evidence %r from dataset %s, not the "
                    "pinned %s" % (finding.get("finding_id"), reference,
                                   dataset or "<missing>", pinned_dataset_id))

    return _verdict(InvariantId.INV_006, "SAFETY_EVIDENCE_NOT_RESOLVABLE",
                    max(examined, 1), violations)


# ---------------------------------------------------------------------------
# SAFETY-INV-007 - persistence requires the complete pinned bundle
# ---------------------------------------------------------------------------

#: Every field that must be present before an assessment may be stored. Each is
#: omitted individually, because a check that only counts fields would pass a
#: record missing one and carrying a duplicate.
REQUIRED_PERSISTENCE_FIELDS: Tuple[str, ...] = (
    "release_id", "software_version", "dataset_version", "ruleset_version",
    "input_hash", "output_hash",
)


def evaluate_persistence_requires_complete_bundle(
        persist: Callable[[Mapping[str, Any]], Any],
        complete_record: Mapping[str, Any]) -> Verdict:
    """Omit each required field in turn; every omission must be refused.

    ``persist(record)`` either stores or raises. A subject that stores a
    record missing any one field has violated the invariant, and so has one
    that refuses the *complete* record - a persistence boundary that rejects
    everything is not enforcement, it is breakage.
    """
    violations: List[str] = []
    examined = 0

    examined += 1
    try:
        persist(dict(complete_record))
    except Exception as exc:
        violations.append(
            "the complete record was refused (%s); a boundary that rejects "
            "everything enforces nothing" % type(exc).__name__)

    for field_name in REQUIRED_PERSISTENCE_FIELDS:
        examined += 1
        incomplete = {key: value for key, value in complete_record.items()
                      if key != field_name}
        try:
            persist(incomplete)
        except Exception:
            continue           # refused, which is correct
        violations.append(
            "a record missing %r was persisted; the release bundle and both "
            "hashes must be complete before anything is stored" % field_name)

    # Partial persistence: the record stored, its children abandoned.
    examined += 1
    partial = dict(complete_record)
    partial["_simulate_partial_commit"] = True
    try:
        outcome = persist(partial)
    except Exception:
        outcome = None
    if isinstance(outcome, Mapping) and outcome.get("partial"):
        violations.append(
            "the store committed an assessment row and abandoned its "
            "children; a partly-verified assessment is one whose trustworthy "
            "half cannot be told from the rest")

    return _verdict(InvariantId.INV_007, "SAFETY_RELEASE_BUNDLE_INCOMPLETE",
                    examined, violations)


# ---------------------------------------------------------------------------
# SAFETY-INV-008 - a conflict must stay visible
# ---------------------------------------------------------------------------

def evaluate_conflict_is_preserved(
        resolver: Callable[[Sequence[Mapping[str, Any]]], Mapping[str, Any]],
        conflicts: Sequence[Sequence[Mapping[str, Any]]],
        precedence: Sequence[str]) -> Verdict:
    """Disagreement is information; it must not be smoothed away.

    ``resolver(findings)`` returns ``{"coverage": ..., "attention": ...,
    "retained": [...]}``. Three failures, all of them tempting because all
    three produce a cleaner answer: taking the lower level, averaging, and
    dropping the rule that disagrees.
    """
    violations: List[str] = []
    examined = 0
    order = list(precedence)

    for group in conflicts:
        examined += 1
        levels = [str(item.get("attention")) for item in group]
        try:
            outcome = resolver(group)
        except Exception as exc:
            violations.append("conflict resolution raised %s"
                              % type(exc).__name__)
            continue

        coverage = str(outcome.get("coverage", ""))
        attention = str(outcome.get("attention", ""))
        retained = list(outcome.get("retained", ()))

        if coverage != "SOURCE_CONFLICT":
            violations.append(
                "conflicting validated rules produced coverage %s; a "
                "disagreement must surface as SOURCE_CONFLICT"
                % (coverage or "<missing>"))

        known = [level for level in levels if level in order]
        if known:
            highest = min(known, key=order.index)
            if attention in order and order.index(attention) > order.index(highest):
                violations.append(
                    "a conflict between %s resolved to %s - the lower level, "
                    "which is the most reassuring possible answer"
                    % (levels, attention))
            if attention not in levels and attention in order:
                violations.append(
                    "a conflict between %s resolved to %s, a level no rule "
                    "produced; averaging invents a finding" % (levels, attention))

        if len(retained) < len(group):
            violations.append(
                "conflict resolution retained %d of %d findings; dropping the "
                "rule that disagrees hides the case a clinician most needs"
                % (len(retained), len(group)))

    return _verdict(InvariantId.INV_008, "SAFETY_CONFLICT_COLLAPSED",
                    examined, violations)


# ---------------------------------------------------------------------------
# SAFETY-INV-009 - partitions must not overlap
# ---------------------------------------------------------------------------

def evaluate_partition_separation(
        auditor: Callable[[Sequence[Any]], Any],
        case_sets: Sequence[Tuple[str, Sequence[Any], bool]]) -> Verdict:
    """Development and holdout must not overlap, by identity or by content.

    ``auditor(cases)`` is WP-18's ``audit_partition`` or an unsafe double.
    Each entry is ``(label, cases, expected_clean)``, so the sweep proves both
    directions: a clean set is not flagged, and each kind of overlap is.
    """
    violations: List[str] = []
    examined = 0

    for label, cases, expected_clean in case_sets:
        examined += 1
        try:
            audit = auditor(list(cases))
        except Exception as exc:
            violations.append("%s: the partition auditor raised %s"
                              % (label, type(exc).__name__))
            continue
        is_clean = bool(getattr(audit, "is_clean", False))
        if expected_clean and not is_clean:
            violations.append(
                "%s: a correctly separated set was reported as overlapping"
                % label)
        if not expected_clean and is_clean:
            violations.append(
                "%s: an overlapping set was reported clean; once a holdout "
                "leaks into development no later analysis can undo it" % label)

    return _verdict(InvariantId.INV_009, "SAFETY_PARTITION_OVERLAP",
                    examined, violations)


# ---------------------------------------------------------------------------
# SAFETY-INV-010 - prohibited claims block release
# ---------------------------------------------------------------------------

def evaluate_no_prohibited_claim(
        scanner: Callable[[str], Any],
        surfaces: Sequence[Tuple[str, str, bool]]) -> Verdict:
    """Every user-facing surface is scanned before release.

    ``scanner(text)`` returns something with ``has_violations``. Each entry is
    ``(surface, text, expected_blocking)``. Both directions matter: a clean
    template must not be blocked, or the gate becomes noise somebody disables.
    """
    violations: List[str] = []
    examined = 0

    for surface, text, expected_blocking in surfaces:
        examined += 1
        try:
            result = scanner(text)
        except Exception as exc:
            violations.append("%s: the claim scanner raised %s"
                              % (surface, type(exc).__name__))
            continue
        blocked = bool(getattr(result, "has_violations", False))
        if expected_blocking and not blocked:
            violations.append(
                "%s: prohibited claim text was released; a blocking claim "
                "must prevent release and must never be auto-edited into "
                "compliance" % surface)
        if not expected_blocking and blocked:
            violations.append(
                "%s: compliant text was blocked; a scanner that blocks safe "
                "output gets switched off" % surface)

    return _verdict(InvariantId.INV_010, "SAFETY_PROHIBITED_CLAIM",
                    examined, violations)


# ---------------------------------------------------------------------------
# SAFETY-INV-011 - no real patient or genomic data
# ---------------------------------------------------------------------------

def evaluate_no_real_patient_data(
        detector: Callable[[Any], Sequence[str]],
        payloads: Sequence[Tuple[str, Any, bool]]) -> Verdict:
    """Prohibited real-data fields are refused at any nesting depth.

    ``detector(payload)`` returns the prohibited paths it found. Each entry is
    ``(label, payload, expected_prohibited)``. The negative direction matters
    as much: ``CYP2D6`` is public gene nomenclature, not patient data, and a
    detector that refused it would make the product unusable for its actual
    purpose.
    """
    violations: List[str] = []
    examined = 0

    for label, payload, expected_prohibited in payloads:
        examined += 1
        try:
            found = list(detector(payload))
        except Exception as exc:
            violations.append("%s: the input detector raised %s"
                              % (label, type(exc).__name__))
            continue
        if expected_prohibited and not found:
            violations.append(
                "%s: a prohibited real-data field was accepted; P0 takes only "
                "synthetic and protocol-defined input" % label)
        if not expected_prohibited and found:
            violations.append(
                "%s: permitted input was refused as patient data (%s); public "
                "gene and drug nomenclature is not patient data"
                % (label, ", ".join(found[:3])))

    return _verdict(InvariantId.INV_011, "SAFETY_REAL_PATIENT_DATA",
                    examined, violations)


# ---------------------------------------------------------------------------
# SAFETY-INV-012 - determinism
# ---------------------------------------------------------------------------

def evaluate_deterministic_result(
        calculate: Callable[[Mapping[str, Any]], Mapping[str, Any]],
        base_input: Mapping[str, Any],
        orderings: Sequence[Sequence[Any]],
        repeats: int = 3) -> Verdict:
    """The same pinned input and release must produce the same bytes.

    Two sweeps. Repetition catches wall-clock and iteration-order leakage;
    re-ordering the medication list catches a subject whose output depends on
    the order its input arrived in. Both compare the ``output_hash`` the
    subject reports, which is what a release is attributed by.
    """
    violations: List[str] = []
    examined = 0
    hashes: List[str] = []

    for _ in range(max(2, repeats)):
        examined += 1
        try:
            result = calculate(dict(base_input))
        except Exception as exc:
            violations.append("repeated calculation raised %s"
                              % type(exc).__name__)
            continue
        hashes.append(str(result.get("output_hash")))

    if len(set(hashes)) > 1:
        violations.append(
            "repeating the same input produced %d different output hashes; a "
            "result that cannot be reproduced cannot be reviewed, defended or "
            "retracted" % len(set(hashes)))

    baseline: Optional[str] = hashes[0] if hashes else None
    for ordering in orderings:
        examined += 1
        shuffled = dict(base_input)
        shuffled["medications"] = list(ordering)
        try:
            result = calculate(shuffled)
        except Exception as exc:
            violations.append("re-ordered calculation raised %s"
                              % type(exc).__name__)
            continue
        digest = str(result.get("output_hash"))
        if baseline is not None and digest != baseline:
            violations.append(
                "re-ordering the input changed the output hash; the order "
                "medications arrived in must not influence the result")

    return _verdict(InvariantId.INV_012, "SAFETY_NON_DETERMINISTIC_RESULT",
                    examined, violations)


#: Every evaluator, keyed by the invariant it decides. Used by the report
#: builder to prove that all twelve have one, and by the tests that assert no
#: invariant is left without a detector.
EVALUATORS: Mapping[InvariantId, Callable[..., Verdict]] = {
    InvariantId.INV_001: evaluate_absence_never_reassures,
    InvariantId.INV_002: evaluate_renderer_preserves_facts,
    InvariantId.INV_003: evaluate_only_validated_rules_execute,
    InvariantId.INV_004: evaluate_phenotype_matching_is_exact,
    InvariantId.INV_005: evaluate_no_candidate_preference,
    InvariantId.INV_006: evaluate_findings_are_evidence_backed,
    InvariantId.INV_007: evaluate_persistence_requires_complete_bundle,
    InvariantId.INV_008: evaluate_conflict_is_preserved,
    InvariantId.INV_009: evaluate_partition_separation,
    InvariantId.INV_010: evaluate_no_prohibited_claim,
    InvariantId.INV_011: evaluate_no_real_patient_data,
    InvariantId.INV_012: evaluate_deterministic_result,
}
