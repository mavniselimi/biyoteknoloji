# Source review checklist

| Field | Value |
|---|---|
| Document ID | `DOC-SCI-005` |
| Work package | WP-05 |
| Machine-readable form | `pgx-source-policy review-checklist` |
| Status | **Not yet used. No source has been reviewed.** |

> Every step below is something a person does. No tool in this repository can
> perform any of them, and there is no `approve` subcommand. If you are looking
> for the command that marks a source approved, there isn't one, and that is
> deliberate.

---

## Before you start

You are about to record a conclusion that other people will rely on without
re-deriving it. Two things make that safe: the conclusion is attributed to you
by name, and it is separated from the source's own words so a later reader can
check one against the other.

You are not being asked for a legal opinion, and the record explicitly is not
one. You are being asked to read what a source published about its own terms
and write down what you understood, what you could not establish, and what you
therefore decided.

If you cannot reach the official document, **stop at step 3**. Record the
attempt as `BLOCKED` and leave the source `PENDING_REVIEW`. A source you could
not check is not a source you may approve.

---

## 1. Identify the exact source

Name the provider *and* the specific product or interface. "CPIC" is a
consortium, not a source: its database, its API and its published guidelines
may carry different conditions, and each gets its own `source_key`.

For a drug label, name the jurisdiction. A US FDA statement is not a Turkish
one, and `druglabel.*` entries are registered per regulator for that reason.

## 2. Retrieve the official terms

Open the source's **own** terms, licence or API-conditions document. Record:

- its `https` URL;
- the instant you retrieved it (`retrieved_at`, UTC, with an offset);
- a `sha256:` content hash where you can compute one;
- a short factual summary **in your own words**, under 1000 characters.

Do not paste the document into the repository. A second copy here goes stale
without anybody noticing which one is right; the URL plus the hash is what
makes staleness detectable.

## 3. Reject non-authoritative material

A search-result snippet, a blog post, an encyclopaedia article, a conference
slide or another project's summary is **not** licensing authority. The
`EvidenceType` vocabulary has no member for any of them, deliberately.

If the official document cannot be reached: set `verification: BLOCKED`, write
what happened in `blocked_reason`, and stop. Do not retry until it works. Do
not substitute a mirror or an archive. Do not proceed on the basis that the
source "is obviously open". A failed retrieval is an outstanding obligation.

## 4. Write the project interpretation, separately

In `interpretation`, record:

- `summary` - what you understand the terms to permit, in your words;
- `interpreted_by` - you;
- `interpreted_at` - now, UTC;
- `open_questions` - everything you could not establish.

Keep this apart from the source's wording. If your reading later turns out to
be wrong, the point of the separation is that somebody can see *which* of the
two was wrong.

## 5. Answer all ten reuse dimensions

Every dimension gets `ALLOWED`, `RESTRICTED`, `PROHIBITED`, `UNKNOWN` or
`NOT_APPLICABLE`. See `licensing-and-reuse-matrix.md` for what each asks.

Leaving one out is the same as `UNKNOWN`, and `UNKNOWN` blocks exactly as
`PROHIBITED` does. If you are not sure, the answer is `UNKNOWN` - that is what
it is for, and guessing `ALLOWED` is the failure this whole package exists to
prevent.

`RESTRICTED` must be accompanied by the condition, recorded in the review's
`restrictions` list.

## 6. Decide the acquisition mode

How records may be obtained is a separate question from what may be done with
them. A source may permit reuse of a hand-downloaded file while prohibiting the
crawl that would produce the same bytes.

Automated acquisition (`OFFICIAL_API`, `LICENSED_BULK_EXPORT`) additionally
requires `AUTOMATED_ACQUISITION` to be permitted in the matrix. The validator
checks the two agree.

## 7. Record version and citation policy

- `version_policy` - how a version of this source is identified, in the
  source's own terms (a release number, a date, a DOI).
- `citation_policy` - how the source requires that it be cited.

Both are required before publication. Neither is ever inferred.

## 8. Decide the claim categories

What may this source be cited *for*? A source cleared for phenotype mappings
has not thereby been cleared to carry a prescribing recommendation.

Available categories: `PRIMARY_GUIDELINE_RECOMMENDATION`,
`SUPPORTING_ANNOTATION`, `ALLELE_FUNCTION_ASSIGNMENT`, `PHENOTYPE_MAPPING`,
`DRUG_LABEL_STATEMENT`, `LITERATURE_REFERENCE`, `INTERNAL_BOOKKEEPING`.

An `INTERNAL_SYSTEM` source may only ever carry `INTERNAL_BOOKKEEPING`.

## 9. Record the decision under your own name

In `review`:

| Field | Requirement |
|---|---|
| `decision` | `APPROVE`, `APPROVE_WITH_RESTRICTIONS`, `REJECT`, `REQUEST_MORE_INFORMATION` |
| `reviewer_name` | Your name. Not a role, not a team, not a script |
| `reviewer_role` | What qualifies you to make this call |
| `decided_at` | Now, UTC, with an offset |
| `evidence_urls` | At least one, for any approving decision |
| `restrictions` | Required for `APPROVE_WITH_RESTRICTIONS` |
| `expires_at` | Strongly recommended. A licence read once is not a licence forever |

Then set `status` to match. A record claiming an approving status without an
approving review is **refused at load time** - the file will not parse - and the
database refuses the equivalent row.

Commit the change. The commit is part of the record: it is what puts an author
and a date against a licensing conclusion.

## 10. Check for conflicts

If this source disagrees with an already-approved source, record a
`SourceConflict`. Do **not** resolve it by choosing a winner here. A resolution
is its own decision, with its own rationale and your name against it. See
`source-conflict-policy.md`.

## 11. Re-run the gate

```
pgx-source-policy validate
pgx-source-policy show <source_key> --text
pgx-source-policy evaluate-publication --dataset <D> --source <source_key> [flags]
```

Publication stays blocked until the gate says otherwise. If the gate still
reports a blocker you did not expect, the record is incomplete - fix the
record, not the gate.

---

## What you must never do

- Invent a reviewer name, including your team's name or a placeholder, to make
  a check pass.
- Record a licence identifier you did not read in the source's own document.
- Convert a failed retrieval into an approval, however obvious the source's
  openness seems.
- Copy a terms page into this repository.
- Email or otherwise contact a source owner on the project's behalf without a
  separate decision to do so. Nothing in this repository does that.
- Approve a source because a dataset build is waiting on it.
