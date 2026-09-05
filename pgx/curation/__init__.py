# -*- coding: utf-8 -*-
"""The scientific curation protocol (WP-09).

Pure domain. Standard library plus :mod:`pgx.domain`; no database, no network,
no filesystem beyond reading artifacts whose paths a caller supplies.

**What this package is.** The contract the fourth pipeline stage must satisfy:

    RawArtifact -> Canonical Entity -> EvidenceRecord ->
    CuratedInterpretation -> ComputableRule

WP-06 sealed the raw bytes, WP-07 canonicalised the entities, WP-08 recorded
what sources stated. This package defines what it means for a human to reach a
conclusion about that evidence, and refuses conclusions that would not
withstand review.

**What this package is not.** It runs no workflow, enforces no authorization,
writes no database row, and creates no
:class:`pgx.domain.models.CuratedInterpretation`. There is no function here
that turns one of WP-08's 1,559 legacy proposals into an approved
interpretation, and adding one would be the exact failure this work package
exists to prevent: a project's own prior conclusions promoted to reviewed
science by a program. WP-10 owns the workflow; WP-11 owns rules.

Six shaping decisions, each of which cost something:

1. **A source's word and a curator's conclusion are different objects.**
   ClinPGx's ``significance=yes`` and ``score=3.75`` are held in
   :class:`~pgx.curation.models.SourceReportedValues` for comparison and are
   never mapped to a conclusion. The cost is that a curator must write the
   explanation the source's flag would otherwise have supplied for free.

2. **The unit of curation is a question, not a gene/drug pair.** Gene, drug,
   phenotype scope, effect dimension, population. The legacy seed produced
   3,084 rows by applying pair-level conclusions broadly; the cost of not
   doing that is far fewer conclusions, each narrower.

3. **No vocabulary is ordered and none carries a number.** Comparing two
   members raises. There is no confidence, no strength, no risk score. The
   cost is that nothing can be sorted, aggregated or thresholded - which is
   the point, because arithmetic over judgement produces a result nobody
   reviewed.

4. **Excluded evidence stays.** With a controlled reason and a written
   rationale. Contradictory, older, other-organisation and unknown-version
   evidence may never be excluded by rule. The cost is longer records.

5. **INSUFFICIENT is a real answer and never a reassuring one.** Screened for
   reassuring language, and required to say what is missing. ``SAFETY-INV-001``:
   the worst failure of a pharmacogenomic tool is a reader taking "we did not
   look" as "there is nothing there".

6. **Nothing here can supply a person.** Every state that names a decision
   requires a named human, placeholders are treated as absence rather than as
   weak identity, and the protocol's own status is
   ``AWAITING_EXPERT_REVIEW``. The cost is that this package cannot finish its
   own job, which is the honest description of where the project is.
"""
