# -*- coding: utf-8 -*-
"""Canonicalization, resolution, deduplication and data quality (WP-07).

This package turns an immutable raw snapshot into a canonical build: the genes
and drugs the source actually named, where each came from, what could not be
resolved, what was observed more than once, and the metrics describing all of
it. It decides nothing scientific.

**The boundary, stated plainly because it is the one most likely to erode.**
Nothing here interprets a pharmacogenetic finding, assigns a risk or severity,
maps a phenotype to an effect, recommends a treatment or ranks a source. Those
are WP-08 and later. A canonical entity carries an identity, a normalised
value, the source's own spelling, its external identifiers, its alias proposals
and its provenance - and a test asserts that no interpretation field ever
appears on one.

**Five decisions that shape everything else.**

1. *Ambiguity is data.* A value matching two entities produces an ``AMBIGUOUS``
   outcome carrying **both** candidates and a queue item for a human. It is
   never settled by ranking, by insertion order, by ``results[0]``, by the
   smallest UUID or by a source score. The legacy resolver settled it by taking
   the first result, which is the defect this package exists to remove.

2. *Only an approved alias resolves.* An alternative name observed upstream is
   recorded as a proposal and resolves nothing. Letting a source's spelling
   decide what this project treats as the same thing would put the source, not
   a reviewer, in charge of identity.

3. *Identity is allocated explicitly, never derived.* ``GeneId`` and ``DrugId``
   have no ``derive()`` and none is added: a UUID computed from a name would
   make two independent curation runs collide on one row. Reproducibility comes
   from writing the mapping down in an immutable allocation artifact and
   reusing it, and minting is refused unless the caller asked for it.

4. *Deduplication never discards.* Every member's locator survives in its
   group. Two records claiming one source identity while carrying different
   payloads are not duplicates at all - one is wrong, and discarding either
   would hide which - so that case is always blocking and never merged.

5. *The quality gate fails closed and decides nothing.* Every unanswered
   question blocks. A passing gate is a precondition for a human decision, not
   the decision: there is no function in this package that marks a dataset
   ``QUALITY_CHECKED``, publishes one, or activates a release.

**What the counts mean.** ``source_observed_*`` figures count what a snapshot
mentions. They are not validated coverage, not clinical coverage, not supported
treatment, not safe alternatives and not executable pharmacogenetic rules, and
the reports say so on every page where they appear.

Modules:

* :mod:`~pgx.normalization.normalize` - deterministic value normalisation.
* :mod:`~pgx.normalization.models` - canonical entities, locators, outcomes.
* :mod:`~pgx.normalization.artifacts` - what each raw artifact is for.
* :mod:`~pgx.normalization.extract` - reading a snapshot into candidates.
* :mod:`~pgx.normalization.resolver` - the strict five-step resolver.
* :mod:`~pgx.normalization.dedup` - duplicate detection that keeps provenance.
* :mod:`~pgx.normalization.allocation` - explicit identity allocation.
* :mod:`~pgx.normalization.build` - assembling and sealing a canonical build.
* :mod:`~pgx.normalization.quality` - DQ metrics and the fail-closed gate.
* :mod:`~pgx.normalization.legacy_diff` - what changed against the legacy seed.
* :mod:`~pgx.normalization.ports` - persistence ports.
* :mod:`~pgx.normalization.errors` - typed canonicalization failures.
"""
