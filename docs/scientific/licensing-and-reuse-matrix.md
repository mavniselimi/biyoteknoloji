# Licensing and reuse matrix

| Field | Value |
|---|---|
| Document ID | `DOC-SCI-003` |
| Work package | WP-05 |
| Machine-readable form | `config/scientific-sources.json`, `reuse` on each source |
| Status | **Every cell is `UNKNOWN`. Nothing is permitted.** |

> The matrix below is the current state of the repository, generated from the
> registry. It is not a claim about what any of these sources permits. It is a
> record of what this project has established, which is nothing.

---

## 1. Why ten dimensions and not one flag

"Can we use this?" is at least ten different questions, and a single yes/no has
to lie about at least nine of them. A source may permit local storage and
internal analysis while prohibiting verbatim redistribution; may permit manual
download while prohibiting automated acquisition; may permit non-commercial use
only.

| Dimension | The question it answers |
|---|---|
| `LOCAL_STORAGE` | May we keep a copy of retrieved records on project-controlled storage? |
| `INTERNAL_ANALYSIS` | May we read and analyse those records inside the project? |
| `DERIVED_WORK_CREATION` | May we produce derived records - normalised, mapped, summarised? |
| `AGGREGATED_REDISTRIBUTION` | May we publish aggregated or summarised output outside the project? |
| `VERBATIM_REDISTRIBUTION` | May we publish the source's records verbatim? |
| `COMMERCIAL_USE` | May any of this be used in a commercial product or paid service? |
| `AUTOMATED_ACQUISITION` | May we retrieve records by program rather than by hand? |
| `BULK_DOWNLOAD` | May we retrieve whole collections rather than individual records? |
| `THIRD_PARTY_SHARING` | May records be passed to a party outside this project? |
| `PUBLIC_DISPLAY` | May the source's text be shown to an end user in a report or interface? |

## 2. The five answers

| Permission | Meaning | Blocks? |
|---|---|---|
| `ALLOWED` | The source's own published terms permit this use, on the evidence held | No |
| `NOT_APPLICABLE` | The question does not arise for this source | No |
| `RESTRICTED` | Permitted only under conditions the record names | **Yes**, until a review records those conditions as met |
| `PROHIBITED` | The source's own published terms forbid this use | **Yes** |
| `UNKNOWN` | Nobody has established an answer | **Yes** |

`UNKNOWN` and `PROHIBITED` have exactly the same effect on publication. They
differ only in what a reviewer does next. That equivalence is the whole
fail-closed rule, expressed as two vocabulary members rather than as a comment
somebody can delete.

A dimension left out of the file reads as `UNKNOWN`. `ReuseMatrix` materialises
all ten on construction, so absence and an explicit `UNKNOWN` are the same
object and no caller can read absence as permission.

## 3. Which dimensions a given use puts in scope

The gate does not check all ten every time. `PublicationIntent` says what a
dataset proposes to do, and only the dimensions that use actually touches are
required.

| Always in scope | Because |
|---|---|
| `LOCAL_STORAGE`, `INTERNAL_ANALYSIS`, `DERIVED_WORK_CREATION` | Any use at all stores records, reads them, and derives from them |

| Intent flag | Adds |
|---|---|
| `--displays-source-text` | `PUBLIC_DISPLAY` |
| `--redistributes-aggregated` | `AGGREGATED_REDISTRIBUTION` |
| `--redistributes-verbatim` | `VERBATIM_REDISTRIBUTION` |
| `--shares-with-third-party` | `THIRD_PARTY_SHARING` |
| `--commercial-use` | `COMMERCIAL_USE` |
| `--automated-acquisition` | `AUTOMATED_ACQUISITION` |
| `--bulk-download` | `BULK_DOWNLOAD` |

Every flag defaults to false, so a caller who forgets one asks for *less*
permission rather than more.

## 4. Current matrix

Twenty registered sources. Every one of the ten dimensions on every one of them
is `UNKNOWN`, because no terms document has been retrieved and no reviewer has
answered anything.

| Source | Role | Status | Answered dimensions |
|---|---|---|---|
| `aha.publications` | PRIMARY_GUIDELINE | PENDING_REVIEW | 0 / 10 |
| `ausnz.publications` | PRIMARY_GUIDELINE | PENDING_REVIEW | 0 / 10 |
| `clinpgx.api` | SUPPORTING_ANNOTATION | PENDING_REVIEW | 0 / 10 |
| `clinpgx.website` | SUPPORTING_ANNOTATION | PENDING_REVIEW | 0 / 10 |
| `cpic.api` | PRIMARY_GUIDELINE | PENDING_REVIEW | 0 / 10 |
| `cpic.database` | PRIMARY_GUIDELINE | PENDING_REVIEW | 0 / 10 |
| `cpic.publications` | PRIMARY_GUIDELINE | PENDING_REVIEW | 0 / 10 |
| `cpnds.publications` | PRIMARY_GUIDELINE | PENDING_REVIEW | 0 / 10 |
| `dpwg.knmp` | PRIMARY_GUIDELINE | PENDING_REVIEW | 0 / 10 |
| `druglabel.ema` | PRIMARY_GUIDELINE | PENDING_REVIEW | 0 / 10 |
| `druglabel.fda` | PRIMARY_GUIDELINE | PENDING_REVIEW | 0 / 10 |
| `druglabel.hcsc` | PRIMARY_GUIDELINE | PENDING_REVIEW | 0 / 10 |
| `druglabel.pmda` | PRIMARY_GUIDELINE | PENDING_REVIEW | 0 / 10 |
| `druglabel.swissmedic` | PRIMARY_GUIDELINE | PENDING_REVIEW | 0 / 10 |
| `druglabel.titck` | PRIMARY_GUIDELINE | PENDING_REVIEW | 0 / 10 |
| `internal.legacy_mvp_seed` | INTERNAL_SYSTEM | PENDING_REVIEW | 0 / 10 |
| `internal.legacy_probe_outputs` | INTERNAL_SYSTEM | PENDING_REVIEW | 0 / 10 |
| `internal.manual_normalization` | INTERNAL_SYSTEM | PENDING_REVIEW | 0 / 10 |
| `pubmed.literature` | REFERENCE_ONLY | PENDING_REVIEW | 0 / 10 |
| `rnpgx.publications` | PRIMARY_GUIDELINE | PENDING_REVIEW | 0 / 10 |

Regenerate this view with:

```
pgx-source-policy show --text            # every key and its status
pgx-source-policy show <source_key> --text   # one source's ten dimensions
```

## 5. Licence identifiers are never guessed

`license_identifier` holds the licence the source itself names, verbatim. It is
`null` on every entry today. It is never inferred from a similar source, from
the absence of a restriction, or from what a comparable project concluded. A
missing identifier is a `MISSING_LICENSE_IDENTIFIER` blocker, which is the
correct outcome: not knowing the licence is a reason to stop, not a reason to
proceed carefully.

## 6. Restricted is not a soft yes

`RESTRICTED` blocks. A restriction that nobody has recorded as satisfied is not
satisfied, and the place that record lives is the review's `restrictions` list
together with the reviewer's name. `APPROVE_WITH_RESTRICTIONS` that names no
restriction is refused, in the model and in the database.
