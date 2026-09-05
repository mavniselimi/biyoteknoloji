# -*- coding: utf-8 -*-
"""SAFETY-INV-002 negative controls: a renderer that changes a fact.

No LLM ships in P0. These are test-only doubles standing in for one, so the
fact-preservation detector is proven *before* the feature exists rather than
after it has already rendered something wrong.

Each takes the deterministic report and returns narration text. None of them
calls a model, a network service, or anything outside this module.
"""

from __future__ import annotations

from typing import Any, Mapping


def _base(report: Mapping[str, Any]) -> str:
    facts = report.get("facts", {})
    return ("Assessment for %s. Coverage %s. Release %s, ruleset %s."
            % (facts.get("medication", "the medication"),
               facts.get("coverage"), facts.get("release_id"),
               facts.get("ruleset_version")))


def faithful(report: Mapping[str, Any]) -> str:
    """The safe control: re-worded, nothing changed.

    Present so the detector is shown to accept a legitimate narration. A
    fact-preservation check that rejected everything would be indistinguishable
    from one that works, and would be switched off within a week.
    """
    facts = report.get("facts", {})
    return _base(report) + " Attention level: %s." % facts.get("attention")


def changes_attention(report: Mapping[str, Any]) -> str:
    """NC-INV-002-RENDERER-CHANGES-ATTENTION.

    The report says HIGH; the narration says the medication is low concern.
    This is the failure mode that makes a generative layer unacceptable
    upstream of a clinical fact.
    """
    facts = report.get("facts", {})
    downgraded = "LOW" if facts.get("attention") != "LOW" else "NO_ACTIVE_ATTENTION"
    return _base(report) + " Attention level: %s." % downgraded


def invents_dose(report: Mapping[str, Any]) -> str:
    """NC-INV-002-RENDERER-INVENTS-DOSE.

    A dose appears that the deterministic report never contained and that no
    validated rule in this system produces. There is no dose logic anywhere in
    P0, so any number with a unit is fabricated by definition.
    """
    facts = report.get("facts", {})
    return (_base(report) + " Attention level: %s. Consider 25 mg daily."
            % facts.get("attention"))


def drops_version(report: Mapping[str, Any]) -> str:
    """NC-INV-002-RENDERER-DROPS-VERSION.

    Quieter than the other two and just as serious: the narration is factually
    correct but carries no release or ruleset identity, so the reader cannot
    tell which version of the system said it.
    """
    facts = report.get("facts", {})
    return ("Assessment for %s. Coverage %s. Attention level: %s."
            % (facts.get("medication", "the medication"),
               facts.get("coverage"), facts.get("attention")))


UNSAFE_SUBJECTS = {
    "NC-INV-002-RENDERER-CHANGES-ATTENTION": changes_attention,
    "NC-INV-002-RENDERER-INVENTS-DOSE": invents_dose,
    "NC-INV-002-RENDERER-DROPS-VERSION": drops_version,
}

SAFE_SUBJECT = faithful


def sample_reports():
    """Deterministic reports to narrate. Synthetic; no real medication data."""
    return (
        {"facts": {"medication": "SYNTHDRUG-1", "attention": "HIGH",
                   "coverage": "FULL", "release_id": "REL-TEST-001",
                   "ruleset_version": "1.0.0"},
         "levels_not_present": ("LOW", "NO_ACTIVE_ATTENTION")},
        {"facts": {"medication": "SYNTHDRUG-2", "attention": "NOT_ASSESSED",
                   "coverage": "INSUFFICIENT", "release_id": "REL-TEST-001",
                   "ruleset_version": "1.0.0"},
         "levels_not_present": ("LOW", "NO_ACTIVE_ATTENTION", "HIGH")},
    )
