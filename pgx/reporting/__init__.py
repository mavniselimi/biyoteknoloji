# -*- coding: utf-8 -*-
"""Deterministic reporting (WP-15).

One job: turn structured facts that were already calculated into a document a
person can read, **without deciding anything**.

The pipeline is one direction and has no branches:

    AssessmentResult -> StructuredReport -> deterministic renderer
                     -> immutable artifact + manifest

Every stage is a projection. Nothing in this package computes coverage,
computes attention, aggregates, selects a rule, resolves evidence, resolves a
release, adjudicates a conflict, or asks a language model anything. What it is
handed is what it shows; where it was handed nothing, it says so.

Three properties are load-bearing, and each has its own module:

* **Nothing is lost.** ``validator`` builds a machine-checkable ledger of every
  fact the assessment carried and refuses a report that dropped one. A report
  missing an evidence reference, a conflict reference or a coverage reason is
  not a shorter report; it is a different and more reassuring claim.
* **Nothing is added.** ``render`` escapes every value that came from data, so
  a case identifier cannot become a heading and a medication label cannot
  become a link. ``gate`` runs WP-00's prohibited-claim scanner over the
  finished text and blocks publication on any hit.
* **Nothing drifts.** The same report, template and locale render byte for
  byte identically: no timestamp, no path, no environment value, no random id
  and no dictionary ordering reaches the page.

There is no language-model provider here, disabled or otherwise, beyond the
port in ``llm`` that raises. A model can turn ``NOT_ASSESSED`` into
reassurance, invent an effect code, or smooth away a partial-coverage caveat -
and none of those is visible in a hash.
"""

from __future__ import annotations

__all__ = ["REPORTING_PACKAGE_VERSION"]

REPORTING_PACKAGE_VERSION = "pgx-reporting/1"
