# -*- coding: utf-8 -*-
"""Governed computable rules and immutable rulesets (WP-11).

A **computable rule** is the only thing the assessment engine will ever be
allowed to execute, and this package is what decides whether one may exist.

The shape of the argument:

* A rule condition is *declarative data* - one canonical gene, one canonical
  drug, and an explicitly enumerated phenotype match. There is no expression
  language, no regex, no wildcard and no default case, because a condition a
  scientist cannot read is a condition nobody reviewed.
* A rule outcome is one member of the controlled attention vocabulary. It is
  not a dose, not a recommendation, not a ranking and not a safety statement.
* A rule reaches ``VALIDATED`` only by descending from a genuinely ``CURATED``
  WP-10 interpretation, at an exact revision whose hash still matches, under a
  complete approval envelope with three separated people, citing evidence that
  resolves inside a pinned build.
* Only ``VALIDATED`` rules enter a ruleset, only a ``FROZEN`` ruleset is
  executable, and freezing is a separate audited act from validating.

None of that is satisfiable in this repository today, and that is the correct
state: the curation protocol awaits expert review, the evidence build is
quarantined, the canonical dataset is ``BUILDING``, and no identity holds any
role. So the real registry exposes zero executable rulesets. The machinery is
complete and provably works; what is missing is human approval, which no code
can supply.

WP-11 does **not** match a phenotype against a patient, compute coverage, or
run an assessment. Those are WP-12 and later. This package stops at a typed,
verified, immutable interface for an engine that does not exist yet.
"""

from __future__ import annotations

__all__ = ["RULES_PACKAGE_VERSION"]

#: Bumped when the shape of anything this package persists or publishes
#: changes. A rule written under one version is not silently readable under
#: another.
RULES_PACKAGE_VERSION = "pgx-rules/1"
