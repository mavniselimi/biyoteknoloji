# -*- coding: utf-8 -*-
"""SAFETY-INV-003 negative controls: rules that should not have executed.

The scientific claim of the product rests entirely on rule governance. A rule
that fires without being VALIDATED makes the approval workflow decorative -
which is what legacy `MANUAL_EFFECT_HINTS` was (``LEGACY-BUG-006``): curated
content applied at assessment time with no review record at all.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

PINNED_RULESET = "RS-PINNED-001"
OTHER_RULESET = "RS-OTHER-002"


def rule_set() -> Sequence[Mapping[str, Any]]:
    """A mixed ruleset: two that may execute, four that may not."""
    return (
        {"rule_id": "R-VALID-1", "status": "VALIDATED",
         "ruleset_id": PINNED_RULESET},
        {"rule_id": "R-VALID-2", "status": "VALIDATED",
         "ruleset_id": PINNED_RULESET},
        {"rule_id": "R-DRAFT-1", "status": "DRAFT",
         "ruleset_id": PINNED_RULESET},
        {"rule_id": "R-CURATED-1", "status": "CURATED",
         "ruleset_id": PINNED_RULESET},
        {"rule_id": "R-DEPRECATED-1", "status": "DEPRECATED",
         "ruleset_id": PINNED_RULESET},
        {"rule_id": "R-UNPINNED-1", "status": "VALIDATED",
         "ruleset_id": OTHER_RULESET},
    )


def safe_selector(rules, pinned_ruleset_id):
    """The safe control: VALIDATED, and from the pinned ruleset. Both."""
    return [rule for rule in rules
            if rule.get("status") == "VALIDATED"
            and rule.get("ruleset_id") == pinned_ruleset_id]


def draft_rule_fires(rules, pinned_ruleset_id):
    """NC-INV-003-DRAFT-RULE-FIRES - a plausible off-by-one on lifecycle.

    "Anything past DRAFT review" sounds careful and admits DRAFT itself,
    because the author was thinking about the workflow rather than the gate.
    """
    allowed = ("VALIDATED", "DRAFT")
    return [rule for rule in rules
            if rule.get("status") in allowed
            and rule.get("ruleset_id") == pinned_ruleset_id]


def deprecated_rule_fires(rules, pinned_ruleset_id):
    """NC-INV-003-DEPRECATED-RULE-FIRES - a rule retired for a reason.

    Deprecation usually means the evidence behind the rule was withdrawn.
    Keeping it "until the replacement lands" applies a claim its own curators
    have retracted.
    """
    return [rule for rule in rules
            if rule.get("status") in ("VALIDATED", "DEPRECATED")
            and rule.get("ruleset_id") == pinned_ruleset_id]


def unpinned_ruleset_accepted(rules, pinned_ruleset_id):
    """NC-INV-003-UNPINNED-RULESET-ACCEPTED - status checked, pinning not.

    Every rule returned is VALIDATED. It is still wrong: one of them belongs to
    a ruleset this release never pinned, so the assessment cannot be attributed
    to the bundle it claims.
    """
    return [rule for rule in rules if rule.get("status") == "VALIDATED"]


UNSAFE_SUBJECTS = {
    "NC-INV-003-DRAFT-RULE-FIRES": draft_rule_fires,
    "NC-INV-003-DEPRECATED-RULE-FIRES": deprecated_rule_fires,
    "NC-INV-003-UNPINNED-RULESET-ACCEPTED": unpinned_ruleset_accepted,
}

SAFE_SUBJECT = safe_selector
