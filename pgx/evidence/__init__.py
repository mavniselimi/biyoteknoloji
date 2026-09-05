# -*- coding: utf-8 -*-
"""The evidence store: what sources stated, and where each statement came from (WP-08).

This package turns a sealed raw snapshot and a canonical build into immutable
evidence records. It records what a source said. It decides nothing about
whether the source was right.

**The boundary, stated plainly because it is the one most likely to erode.**
Nothing here assigns a risk, an attention level, a severity, an evidence
strength, a phenotype-to-effect conclusion or a recommendation. Those are
WP-09's and WP-11's, created by a curator from source facts plus judgement -
never copied from the legacy CSVs, which mixed them in with source facts.
:data:`~pgx.evidence.models.PROHIBITED_METADATA_FIELDS` names them and
:class:`~pgx.evidence.models.EvidenceRecordDraft` refuses to be constructed
carrying one.

**Six decisions that shape everything else.**

1. *Source fields are not project fields.* ClinPGx variant annotations carry
   ``score``, ``significance`` and ``polarity``; guideline annotations carry
   boolean ``recommendation`` and ``dosingInformation`` flags. Those are facts
   about what the source published. They are preserved unchanged under one
   reserved namespace, and the prohibited-field scan never runs there. Running
   it there would delete real source data and prove nothing.

2. *Provider and origin are different sources.* ClinPGx *provided* a DPWG
   guideline annotation; ClinPGx did not *assert* it. Both are recorded. An
   origin is populated only from an explicit source field - a record that
   merely looks pharmacogenomic gets ``NOT_STATED_BY_SOURCE`` and an issue,
   never a guessed CPIC.

3. *An unknown version is not a version.* Records with no retained version
   metadata get ``UNKNOWN_LEGACY``. A fabricated ``v1`` would be
   indistinguishable from a real one a year from now.

4. *Identity is allocated, never derived.* ``EvidenceRecordId`` gets no UUID5.
   The natural key to UUID map is written down and reused, exactly as WP-07
   does for genes and drugs.

5. *A narrower view is not a contradiction.* The same record served at two
   ``view`` depths is folded into the wider payload, because that discards
   nothing. Two payloads that actually disagree keep both, choose neither, and
   block.

6. *One record may name many entities.* A guideline naming three genes gets
   three links, not three copies of itself. Duplicating a record per pair would
   make one statement look like several and every count over it wrong.

**Layers.** Raw payload → extracted source facts → project interpretation
candidate → reviewed curation → executable rule. WP-08 implements the first
three, and the third only in
:mod:`~pgx.evidence.draft_curation`, outside the evidence store, marked
``UNREVIEWED_LEGACY_MIGRATION_CANDIDATE`` and ``NOT_EVIDENCE``.

Modules:

* :mod:`~pgx.evidence.models` - records, provenance, attribution, vocabularies.
* :mod:`~pgx.evidence.record_types` - object class to record type mapping.
* :mod:`~pgx.evidence.payloads` - projection versus conflict.
* :mod:`~pgx.evidence.publications` - structural publication parsing.
* :mod:`~pgx.evidence.extract` - reading a snapshot into record drafts.
* :mod:`~pgx.evidence.allocation` - explicit evidence identity allocation.
* :mod:`~pgx.evidence.build` - gates, assembly and the atomic seal.
* :mod:`~pgx.evidence.detail` - the raw-to-canonical trace, over the artifacts.
* :mod:`~pgx.evidence.draft_curation` - legacy interpretations, extracted out.
* :mod:`~pgx.evidence.ports` - persistence ports.
* :mod:`~pgx.evidence.errors` - typed import failures.
"""
