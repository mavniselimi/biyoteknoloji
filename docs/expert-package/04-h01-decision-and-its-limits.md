# 4. The H01 source-policy decision, and its narrow limits

Record: `data/closure/h01-source-policy-decision.json`
(`content_hash: sha256:2b3d3d87…1ced9`).

## What happened

On 6 September 2026, a pharmacist — **Mehmet Yetiş** — reviewed the H01
package: an evidence table, a proposed-decisions file, a risk summary and a
list of unresolved questions, each bound to a SHA-256 the record carries and
re-measures. All five hashes still match. He recorded, in Turkish, a typed
attestation whose repository decision is `APPROVED WITH CONDITIONS`.

He decided twenty source dispositions. Four became
`APPROVED_WITH_RESTRICTIONS`; sixteen stayed `PENDING_REVIEW`.

## What that approval covers

Use conditions on four sources: private, non-commercial research only; manual
review and citation only; normalised internal derivation permitted; no
verbatim full-text redistribution; no scraping, crawling or bulk download; no
automated access under unknown terms.

## What it explicitly does not cover

The record lists this itself, under `not_approved_by_this_decision`:

- the curation protocol and any scientific interpretation decision (H02);
- intended-purpose and claims-boundary decisions (H03);
- any drug, gene or phenotype recommendation;
- any patient-facing or clinician-facing clinical use;
- **any generated pharmacogenetic rule**;
- any dose or treatment-selection statement;
- any evidence extracted after that review;
- any legacy data lacking acceptable provenance;
- redistribution of any source's text;
- automated access whose terms are unknown.

Every rule in this release falls under the fifth item. **The one human
approval this project holds does not approve a single rule you are about to
read.**

## Why the sources are still not usable by the registry's own rules

The approval did not change `config/scientific-sources`. Six named gaps block
it, and the record says who can clear each:

| Gap | What is missing |
|---|---|
| `EVIDENCE_NOT_VERIFIED` | a retrieval instant and content hash for each source's own terms document |
| `MISSING_VERSION_POLICY` | how a version of the source is identified |
| `MISSING_CITATION_POLICY` | how the source must be cited |
| `NO_CLAIM_CATEGORY_APPROVED` | which claim categories each source may be cited for |
| `REUSE_PERMISSION_UNKNOWN` | all ten reuse dimensions answered; `UNKNOWN` blocks exactly as `PROHIBITED` does |
| `REVIEW_EVIDENCE_URLS_MISMATCH` | the reviewer read this project's package, not each source's own terms page |

The last one matters for how you read the attestation. The reviewer approved
what the project told him about those sources' terms. He did not independently
retrieve the terms.

## Identity

`identity_verification: NONE_PERFORMED`. The signature method was a typed
name. What is recorded is that the project owner relayed a typed attestation
naming this reviewer — not a verified electronic signature. The same will be
true of your review unless you and the project agree on something stronger,
and section `reviewer/03` says so plainly rather than implying otherwise.

## What this package must not do to that attestation

Nothing. It is not extended, reinterpreted or leaned on. It approved a source
policy under conditions, on one date, and this package treats it as covering
exactly that.
