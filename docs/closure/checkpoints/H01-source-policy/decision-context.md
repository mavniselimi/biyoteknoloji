# H01 - source policy: what has to be decided

Twenty sources sit in `config/scientific-sources.json`, every one of them `PENDING_REVIEW`, every reuse dimension `UNKNOWN`, and no acquisition mode decided. Nothing may be acquired until somebody with the standing to do so says which sources this project may use and on what terms. WP-C04 did the reading; it did not and could not do the deciding.

## What was read, and what was not

Each researched source was read from a primary document - a licence file, a provider's own terms page, a regulator's own labelling. No row in `evidence-table.csv` rests on a search-result snippet or a secondary summary. Where a document could not be retrieved, the row says `RETRIEVAL_FAILED` or `NOT_ESTABLISHED` and the licence stays `UNKNOWN`.

Twelve of the twenty sources were not researched at all, because the first release does not depend on them. That is recorded as `NOT_RESEARCHED_THIS_WAVE` rather than left to look like an absence of findings.

## Two things this package refuses to merge

**Scientific authority** is whether this project would cite a source. **Legal permission** is whether it may hold, transform or republish that source's material. DPWG scores high on the first and is entirely unestablished on the second; neither fact is evidence for the other.

**API terms** and **website terms** are separate documents even for one provider, and this package keeps them in separate rows. `clinpgx.website` publishes a data statement; `clinpgx.api` has no terms document the project could find, and the evidence build already in this repository was acquired through it.

## What the proposals mean

`APPROVE_FOR_ACQUISITION_SUBJECT_TO_NAMED_CONDITIONS` means the project read a licence that would permit the use it needs, and still wants a person to say so. The named conditions are not waived by the proposal.

`ESCALATE_BEFORE_ANY_ACQUISITION` means the source's own terms contradict each other, or the source cannot be reached at all. These are not maintainer decisions.

`RESEARCH_FURTHER_BEFORE_DECIDING` means the source is needed and its terms are unknown. Nothing may be acquired from it in the meantime.

`DEFER_OUTSIDE_FIRST_RELEASE_SCOPE` is a statement about this release's scope, not about the source.

## Why code cannot decide this

Every one of these turns on a reading of terms, a jurisdictional judgement, or an appetite for risk that belongs to whoever answers for the project. The ClinPGx row is the clearest case: a licence that permits commercial use sits beside a restriction forbidding it, in the same statement, and choosing which half governs is a legal question with consequences for anything built on it.

