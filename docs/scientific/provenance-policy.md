# Provenance policy

| Field | Value |
|---|---|
| Document ID | `DOC-SCI-002` |
| Work package | WP-05 |
| Companion documents | `source-strategy.md`, `licensing-and-reuse-matrix.md` |
| Status | **No evidence has been verified. Every source blocks.** |

> This document says what must be recorded about where a fact came from, and
> what must happen when it cannot be. It approves nothing.

---

## 1. What provenance means here

For every record this project might one day publish, four questions must have
answers, and each has a different source of truth:

1. **Which source published it?** A registered `source_key`, not a free-text
   label.
2. **Which version of that source?** The source's own version identity,
   recorded under `version_policy`.
3. **How must it be cited?** The source's own citation requirement, recorded
   under `citation_policy`.
4. **On what evidence do we believe we may use it?** An official artefact,
   retrieved and hashed.

None of the four is ever inferred. A missing answer blocks publication; it does
not default to a permissive one.

## 2. Evidence: what is stored, and what deliberately is not

An evidence reference (`SourceEvidenceReference`) records five things:

| Field | Why |
|---|---|
| `evidence_type` | What kind of official artefact this is |
| `official_url` | Where it lives, on the source's own site. `https` only |
| `retrieved_at` | When this project actually fetched it |
| `content_hash` | `sha256:<64 hex>` of what was fetched, where computable |
| `summary` | A short factual summary **in this project's words**, capped at 1000 characters |

**The artefact's text is not stored.** Copying a terms page into this
repository would create a second, uncontrolled copy of somebody else's document
that goes stale without anybody noticing which one is right. The URL plus the
hash is what makes staleness detectable; the text would only make it invisible.
The schema and the database both enforce the size cap, and a test asserts there
is no `terms_text`-shaped column anywhere.

## 3. What counts as evidence

Only official artefacts:

| Type | Example |
|---|---|
| `OFFICIAL_TERMS_PAGE` | The source's own terms-of-use page |
| `OFFICIAL_LICENSE_FILE` | A licence file the source publishes |
| `OFFICIAL_API_DOCUMENTATION` | The source's own API docs, where they state use conditions |
| `OFFICIAL_PUBLICATION` | A peer-reviewed article by the source owners, cited by DOI or PMID |
| `DIRECT_WRITTEN_PERMISSION` | Written permission addressed to this project, held on file |

There is deliberately **no member** for a search-result snippet, a blog post,
an encyclopaedia article or another project's summary. Giving one a slot in the
vocabulary would invite its use as licensing authority. A test asserts the
absence.

## 4. Verification states

Naming a URL is not reading the document at it. `verification` records which of
those actually happened.

| State | Meaning | Effect |
|---|---|---|
| `NOT_ATTEMPTED` | Nobody has tried to retrieve it | Blocks |
| `BLOCKED` | Retrieval was attempted and failed. `blocked_reason` is required | Blocks |
| `VERIFIED` | Retrieved, hashed and summarised. `official_url` and `retrieved_at` required | Satisfies the evidence check |
| `STALE` | Retrieved once; the recorded hash no longer matches | Blocks |

`NOT_OBTAINED` evidence can never be `VERIFIED`, and a `BLOCKED` reference
without a reason is refused - an unexplained block is indistinguishable from an
untried one. Both rules hold in the model and as database check constraints.

## 5. Network failure is never converted into approval

This is the rule that matters most in this repository today.

A single retrieval attempt was made during WP-05, to `https://api.clinpgx.org/`
and `https://www.clinpgx.org/`. Both failed before any request left the
environment:

```
URLError <urlopen error Tunnel connection failed: 403 Forbidden>
```

What was recorded, on both ClinPGx entries:

- `evidence_type: NOT_OBTAINED` - because no artefact was obtained, and naming
  a type we did not read would assert that the URL *is* the terms page.
- `verification: BLOCKED`, with the exact error and the date in
  `blocked_reason`.
- `official_url` set to the URL actually attempted.
- `retrieved_at: null` - nothing was retrieved, and a timestamp here would
  imply otherwise.

What was **not** recorded: a licence identifier, a permission, a reuse answer,
a claim category, or an approving status. The source still reports
`MISSING_OFFICIAL_EVIDENCE` alongside `EVIDENCE_RETRIEVAL_BLOCKED`, because a
failed retrieval is an outstanding obligation and not a weak form of evidence.

No further attempt was made. Retrying a blocked request until it succeeds is
not evidence-gathering.

## 6. Interpretation is kept apart from the source's wording

`SourceInterpretation` records what somebody here concluded the terms mean,
with their name and the instant they concluded it. It exists because a
conclusion must be re-examinable when the source's wording turns out to have
said something else - which is impossible if the two are the same field.

`is_legal_opinion` is a property that always returns `False`. There is no way
to set it true. This project's engineers are not its lawyers, and a field that
*could* be set would eventually be set.

## 7. Expiry

A licence read in 2026 is not a licence in 2029. `ReviewRecord.expires_at` is
optional but strongly recommended, and an expired approval reads as
`PENDING_REVIEW` rather than as approved-but-stale: the work needed to use the
source again is exactly the review work.

A review that expires at or before the instant it was decided is refused - it
was never in force.

## 8. Provenance in the operational record

The registry file is where a policy is *decided*, in version control, with an
author against each change. Migration `0003` adds the *operational* record:
which policy content hash was in force when a dataset was evaluated, which
review was cited, which conflicts were open.

Two of those tables are append-only in the database, not merely by convention:

- `source_policy_reviews` - a review decision that could be edited afterwards
  is not evidence of anything.
- `dataset_publication_evaluations` - a verdict that could be rewritten could
  not answer "what did the policy say when we shipped this?".

`UPDATE` and `DELETE` on either raise `restrict_violation`. Verified against
PostgreSQL 16.13; see `docs/evidence/wp05-validation.md`.
