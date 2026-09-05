# -*- coding: utf-8 -*-
"""Duplicate, overlap and conflict detection between rules (WP-11).

Comparison happens on **expanded canonical axes**. A condition covering
``ONE_OF {RAPID, ULTRARAPID}`` becomes two axes, and two rules are compared by
asking which axes they share. That is the only honest way to compare an
enumerated set with a single value, and it is comparison between *rules* -
never evaluation against a patient.

**Nothing here resolves anything.** There is no priority, no ordering, no
"most severe wins", no last-writer-wins and no automatic merge. Two validated
rules producing different attention levels for one axis is a scientific
disagreement between the people who approved them, and the only defensible
behaviour is to refuse the ruleset and hand it back. A system that silently
picked ``HIGH`` because it looks safer would be inventing a conclusion nobody
reviewed - and one that picked ``LOW`` would be worse.

Output is deterministically sorted, so two runs over the same rules produce
byte-identical reports and a diff means something changed.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from pgx.rules.conditions import CanonicalAxis
from pgx.rules.models import ComputableRuleDefinition

__all__ = [
    "CONFLICT_KINDS",
    "BLOCKING_CONFLICT_KINDS",
    "ConflictFinding",
    "ConflictReport",
    "detect_conflicts",
]

#: Every classification, with what it means and whether it blocks. Data rather
#: than prose so the CLI, the schema and the tests cite one list.
CONFLICT_KINDS: Mapping[str, Mapping[str, Any]] = {
    "EXACT_DUPLICATE": {
        "blocking": True,
        "meaning": "two rules make the identical claim under identical "
                   "provenance; one of them is redundant and nobody can tell "
                   "which was intended",
    },
    "REDUNDANT_OVERLAP": {
        "blocking": True,
        "meaning": "two rules overlap on an axis and agree on the outcome, but "
                   "are not the same definition; the set says one thing twice "
                   "and a later edit to one of them would silently disagree",
    },
    "CONFLICTING_OUTCOME": {
        "blocking": True,
        "meaning": "one canonical axis can produce different attention levels; "
                   "this is a disagreement between the people who approved the "
                   "two rules and nothing here may resolve it",
    },
    "IDENTITY_COLLISION": {
        "blocking": True,
        "meaning": "one rule identity carries different content; an approval "
                   "naming that identity no longer says what was approved",
    },
    "VERSION_LINEAGE_ERROR": {
        "blocking": True,
        "meaning": "a family's version lineage is missing, repeated or "
                   "self-referential, so the order of answers is unreconstructible",
    },
    "DATASET_BOUNDARY_CONFLICT": {
        "blocking": True,
        "meaning": "members pin different canonical or evidence builds, so they "
                   "disagree about what the world is",
    },
    "PROTOCOL_BOUNDARY_CONFLICT": {
        "blocking": True,
        "meaning": "members were curated under different protocol or "
                   "source-policy versions, so they were not judged by the same "
                   "standard",
    },
    "SUPERSEDED_MEMBER_PRESENT": {
        "blocking": True,
        "meaning": "a ruleset contains both a rule and the version that "
                   "replaced it, so which answer governs is undefined",
    },
}

#: Every kind blocks. Listed separately anyway, so that a future non-blocking
#: classification is an explicit edit to this line rather than an oversight.
BLOCKING_CONFLICT_KINDS: Tuple[str, ...] = tuple(
    sorted(name for name, entry in CONFLICT_KINDS.items() if entry["blocking"]))


@dataclass(frozen=True, slots=True)
class ConflictFinding:
    """One classified relationship between two or more rules."""

    kind: str
    rule_ids: Tuple[str, ...]
    axis: Tuple[str, ...]
    detail: str

    def __post_init__(self) -> None:
        if self.kind not in CONFLICT_KINDS:
            raise KeyError(
                "%s is not a declared conflict kind; add it to CONFLICT_KINDS "
                "with its meaning rather than reporting an unclassified "
                "finding" % self.kind)
        object.__setattr__(self, "rule_ids", tuple(sorted(self.rule_ids)))
        object.__setattr__(self, "axis", tuple(self.axis))

    @property
    def blocking(self) -> bool:
        return bool(CONFLICT_KINDS[self.kind]["blocking"])

    def sort_key(self) -> Tuple[Any, ...]:
        return (self.kind, self.axis, self.rule_ids, self.detail)

    def to_json(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "blocking": self.blocking,
            "rule_ids": list(self.rule_ids),
            "axis": list(self.axis),
            "detail": self.detail,
            "meaning": CONFLICT_KINDS[self.kind]["meaning"],
        }


@dataclass(frozen=True, slots=True)
class ConflictReport:
    """Every finding, deterministically ordered."""

    findings: Tuple[ConflictFinding, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "findings",
                           tuple(sorted(self.findings, key=lambda f: f.sort_key())))

    @property
    def blocking(self) -> Tuple[ConflictFinding, ...]:
        return tuple(finding for finding in self.findings if finding.blocking)

    @property
    def clean(self) -> bool:
        return not self.blocking

    def to_json(self) -> Dict[str, Any]:
        return {
            "finding_count": len(self.findings),
            "blocking_count": len(self.blocking),
            "clean": self.clean,
            "findings": [finding.to_json() for finding in self.findings],
            "note": ("No finding is resolved automatically. There is no rule "
                     "priority, no ordering and no most-severe-wins: a "
                     "disagreement between approved rules is returned to the "
                     "people who approved them."),
        }


def detect_conflicts(
    definitions: Sequence[ComputableRuleDefinition],
) -> ConflictReport:
    """Classify every relationship between the supplied rules.

    Deterministic in both content and order: the input is sorted by semantic
    key first, so a shuffled database result produces an identical report.
    """
    ordered = sorted(definitions, key=lambda item: item.sort_key())
    findings: List[ConflictFinding] = []

    # -- identity collisions -------------------------------------------
    by_identity: Dict[str, List[ComputableRuleDefinition]] = defaultdict(list)
    for definition in ordered:
        by_identity[definition.rule_id.to_json()].append(definition)
    for rule_id, group in sorted(by_identity.items()):
        hashes = {item.content_hash() for item in group}
        if len(hashes) > 1:
            findings.append(ConflictFinding(
                kind="IDENTITY_COLLISION", rule_ids=(rule_id,), axis=(),
                detail="rule %s carries %d different contents: %s"
                       % (rule_id, len(hashes), ", ".join(sorted(hashes)))))

    # -- version lineage -----------------------------------------------
    by_family: Dict[str, List[ComputableRuleDefinition]] = defaultdict(list)
    for definition in ordered:
        by_family[definition.family_id.to_json()].append(definition)
    for family_id, group in sorted(by_family.items()):
        versions = [item.rule_version for item in group]
        if len(set(versions)) != len(versions):
            repeated = sorted({value for value in versions
                               if versions.count(value) > 1})
            findings.append(ConflictFinding(
                kind="VERSION_LINEAGE_ERROR",
                rule_ids=tuple(item.rule_id.to_json() for item in group),
                axis=(family_id,),
                detail="family %s repeats version %s; two answers claiming to "
                       "be the same revision of one question"
                       % (family_id, ", ".join(str(value) for value in repeated))))
        known = {item.rule_id.to_json() for item in group}
        for item in group:
            predecessor = (item.supersedes_rule_id.to_json()
                           if item.supersedes_rule_id else None)
            if predecessor is not None and predecessor in known:
                findings.append(ConflictFinding(
                    kind="SUPERSEDED_MEMBER_PRESENT",
                    rule_ids=(item.rule_id.to_json(), predecessor),
                    axis=(family_id,),
                    detail="rule %s supersedes %s, and both are present; which "
                           "answer governs is undefined"
                           % (item.rule_id.to_json(), predecessor)))

    # -- provenance boundaries -----------------------------------------
    dataset_keys: Dict[Tuple[str, ...], List[str]] = defaultdict(list)
    protocol_keys: Dict[Tuple[str, ...], List[str]] = defaultdict(list)
    for definition in ordered:
        provenance = definition.provenance
        dataset_keys[(provenance.dataset_public_id.to_json(),
                      provenance.canonical_build_content_hash,
                      provenance.evidence_build_content_hash)].append(
                          definition.rule_id.to_json())
        protocol_keys[(provenance.protocol_version,
                       provenance.protocol_content_hash,
                       provenance.source_policy_version,
                       provenance.source_policy_content_hash)].append(
                           definition.rule_id.to_json())
    if len(dataset_keys) > 1:
        findings.append(ConflictFinding(
            kind="DATASET_BOUNDARY_CONFLICT",
            rule_ids=tuple(sorted(item for group in dataset_keys.values()
                                  for item in group)),
            axis=tuple(sorted("|".join(key) for key in dataset_keys)),
            detail="members pin %d different canonical/evidence boundaries; "
                   "they disagree about what the world is" % len(dataset_keys)))
    if len(protocol_keys) > 1:
        findings.append(ConflictFinding(
            kind="PROTOCOL_BOUNDARY_CONFLICT",
            rule_ids=tuple(sorted(item for group in protocol_keys.values()
                                  for item in group)),
            axis=tuple(sorted("|".join(key) for key in protocol_keys)),
            detail="members pin %d different protocol/source-policy "
                   "boundaries; they were not judged by the same standard"
                   % len(protocol_keys)))

    # -- axis overlap ---------------------------------------------------
    by_axis: Dict[CanonicalAxis, List[ComputableRuleDefinition]] = defaultdict(list)
    for definition in ordered:
        for axis in definition.axes():
            by_axis[axis].append(definition)

    reported_pairs: set = set()
    for axis in sorted(by_axis):
        group = by_axis[axis]
        if len(group) < 2:
            continue
        for index, left in enumerate(group):
            for right in group[index + 1:]:
                pair = tuple(sorted((left.rule_id.to_json(),
                                     right.rule_id.to_json())))
                if left.rule_id == right.rule_id:
                    continue
                if left.outcome.attention_level is not right.outcome.attention_level:
                    findings.append(ConflictFinding(
                        kind="CONFLICTING_OUTCOME", rule_ids=pair,
                        axis=(str(axis),),
                        detail="axis %s can produce %s and %s; two approved "
                               "rules disagree and nothing here chooses between "
                               "them"
                               % (axis, left.outcome.attention_level.value,
                                  right.outcome.attention_level.value)))
                    continue
                if pair in reported_pairs:
                    continue
                reported_pairs.add(pair)
                same_content = left.content_hash() == right.content_hash()
                same_semantics = (
                    left.condition.content_hash() == right.condition.content_hash()
                    and left.outcome.to_json() == right.outcome.to_json()
                    and left.provenance.to_json() == right.provenance.to_json())
                if same_content or same_semantics:
                    findings.append(ConflictFinding(
                        kind="EXACT_DUPLICATE", rule_ids=pair, axis=(str(axis),),
                        detail="two rules make the identical claim under "
                               "identical provenance; nobody can tell which was "
                               "intended"))
                else:
                    findings.append(ConflictFinding(
                        kind="REDUNDANT_OVERLAP", rule_ids=pair, axis=(str(axis),),
                        detail="rules overlap on %s and agree on %s, but are "
                               "different definitions; a later edit to one would "
                               "silently disagree with the other"
                               % (axis, left.outcome.attention_level.value)))

    return ConflictReport(findings=tuple(findings))
