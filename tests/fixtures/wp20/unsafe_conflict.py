# -*- coding: utf-8 -*-
"""SAFETY-INV-008 negative controls: conflicts smoothed into consensus.

Conflict is information. When two validated rules disagree about an axis, that
disagreement is exactly the case a clinician most needs to see - and it is also
the case where the software is under the most pressure to produce something
tidy. All three fixtures here produce a cleaner answer than the truth.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Sequence

#: Highest first. Passed to the evaluator rather than assumed by it.
PRECEDENCE = ("HIGH", "MEDIUM", "LOW", "NO_ACTIVE_ATTENTION", "NOT_ASSESSED")


def conflict_groups() -> Sequence[Sequence[Dict[str, Any]]]:
    """Three disagreements a real ruleset could produce."""
    return (
        ({"rule_id": "R-A", "attention": "HIGH"},
         {"rule_id": "R-B", "attention": "LOW"}),
        ({"rule_id": "R-C", "attention": "MEDIUM"},
         {"rule_id": "R-D", "attention": "NO_ACTIVE_ATTENTION"}),
        ({"rule_id": "R-E", "attention": "HIGH"},
         {"rule_id": "R-F", "attention": "MEDIUM"},
         {"rule_id": "R-G", "attention": "LOW"}),
    )


def safe_resolver(findings: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """The safe control: say it is a conflict, keep the highest, keep them all.

    Coverage becomes ``SOURCE_CONFLICT`` so the disagreement is visible in its
    own field; attention takes the highest level any rule produced, so nothing
    is softened; every finding is retained, so a reviewer can see who said what.
    """
    levels = [str(f.get("attention")) for f in findings]
    known = [level for level in levels if level in PRECEDENCE]
    highest = min(known, key=PRECEDENCE.index) if known else "NOT_ASSESSED"
    return {"coverage": "SOURCE_CONFLICT", "attention": highest,
            "retained": list(findings)}


def takes_lower_level(findings: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """NC-INV-008-CONFLICT-TAKES-LOWER-LEVEL - "be conservative about alarming".

    Presented as caution about over-warning; it is the most reassuring possible
    reading of a disagreement, and it is applied precisely where the evidence
    is weakest.
    """
    levels = [str(f.get("attention")) for f in findings]
    known = [level for level in levels if level in PRECEDENCE]
    lowest = max(known, key=PRECEDENCE.index) if known else "NOT_ASSESSED"
    return {"coverage": "PARTIAL", "attention": lowest,
            "retained": list(findings)}


def averages_levels(findings: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """NC-INV-008-CONFLICT-AVERAGED - a level no rule produced.

    Averaging treats the attention vocabulary as a scale. HIGH and LOW average
    to MEDIUM, which no rule asserted and no evidence supports; the output is
    manufactured.
    """
    levels = [str(f.get("attention")) for f in findings]
    known = [level for level in levels if level in PRECEDENCE]
    if not known:
        return {"coverage": "PARTIAL", "attention": "NOT_ASSESSED",
                "retained": list(findings)}
    middle = sum(PRECEDENCE.index(level) for level in known) // len(known)
    return {"coverage": "PARTIAL", "attention": PRECEDENCE[middle],
            "retained": list(findings)}


def drops_conflicting_rule(findings: Sequence[Mapping[str, Any]]
                           ) -> Dict[str, Any]:
    """NC-INV-008-CONFLICTING-RULE-DROPPED - keep the first, discard the rest.

    The output looks like an ordinary single-rule result. Nothing in it says a
    second validated rule disagreed, so nobody can escalate what they cannot
    see.
    """
    first = list(findings)[:1]
    level = str(first[0].get("attention")) if first else "NOT_ASSESSED"
    return {"coverage": "FULL", "attention": level, "retained": first}


UNSAFE_SUBJECTS = {
    "NC-INV-008-CONFLICT-TAKES-LOWER-LEVEL": takes_lower_level,
    "NC-INV-008-CONFLICT-AVERAGED": averages_levels,
    "NC-INV-008-CONFLICTING-RULE-DROPPED": drops_conflicting_rule,
}

SAFE_SUBJECT = safe_resolver
