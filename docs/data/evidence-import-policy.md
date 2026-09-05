# Evidence import policy (WP-08)

What an import refuses, what it quarantines, and what it is not allowed to
decide.

---

## 1. Two modes, one difference

| | `PRODUCTION` | `LEGACY_MIGRATION` |
| --- | --- | --- |
| A blocking finding | refuses the build | records it and continues |
| Those findings' severity | — | still `BLOCKING` |
| Resulting build | none | quarantined, ineligible |
| Records inside it | — | none publishable |

**Quarantine mode does not turn blockers into warnings.** It stores them
visibly, counts them, and makes the build and every record in it ineligible for
production use. A mode that softened severities would be a way to launder a
refusal into an approval by choosing a flag.

`PRODUCTION` is the default, because the default should be the one that fails
closed.

### The gates, in order

Ordered so a build refused for a corrupt input never proceeds to read it.

1. snapshot verifies against its own manifest
2. snapshot is not quarantined
3. snapshot is an acquisition, not a legacy import
4. canonical build verifies
5. dataset ids match across snapshot and canonical build
6. manifest hashes agree
7. a source policy is on record

On the real dataset, `PRODUCTION` refuses with three findings:

```
$ pgx-evidence build --dataset-id PGX-DATA-20260830-900 --snapshot ... --canonical-build ...
import refused: 3 blocking finding(s) refuse a production evidence import:
RAW_SNAPSHOT_NOT_ACQUIRED, RAW_SNAPSHOT_QUARANTINED, SOURCE_POLICY_MISSING.
  BLOCKING  RAW_SNAPSHOT_QUARANTINED
  BLOCKING  RAW_SNAPSHOT_NOT_ACQUIRED
  BLOCKING  SOURCE_POLICY_MISSING
exit=1
```

Those three are the honest state of this project's only dataset. They are not
worked around.

## 2. What the importer never decides

| Situation | What is **not** done | What is done |
| --- | --- | --- |
| Two containers, conflicting payloads for one identity | choose one | block, keep both locators, emit an issue |
| `label` vs `DrugLabel` equivalence unproven | assume equivalence | keep both types, mark `PENDING_REVIEW`, quarantine, report 28 |
| Record looks pharmacogenomic, states no origin | assign CPIC | `NOT_STATED_BY_SOURCE`, keep the raw value, emit an issue |
| No version metadata survives | write `v1` | `UNKNOWN_LEGACY`, no value |
| Two titles look similar | merge the publications | leave both unidentified |
| A publication is missing details | look it up online | leave it as the bytes said |
| Identity absent from the allocation | mint one quietly | fail, unless `--allocate-new-identities` |
| Same gene/drug pair on two records | collapse them | two records; a pair is not an identity |

Each row is a place where a plausible automatic answer would have been a
scientific claim made by a sort order, a string comparison or a default.

## 3. Identity allocation is an explicit operation

`record_uuid` comes from an allocation file, never from the content.

- A key with no allocated identity is an **error** unless
  `--allocate-new-identities` is passed.
- Rebuilding with the same allocation is byte-identical apart from
  `manifest.json` and `checksums.sha256`, which carry `built_at`.
- A removed record does **not** free its identity. Handing it to a different
  record later would silently redirect every citation of the old one.
- A changed natural key produces a **new** record, visibly, rather than
  mutating the old one.
- Two entries may not share a key, and two may not share a UUID.
- There is no UUID5 over content. Content-derived identity would make a
  corrected record a different record and would let the resolver mint silently.

Measured on the real build: first run 1,794 minted / 0 reused; second run with
`--allocation` 0 minted / 1,794 reused; `compare-builds` reports
`reproducible: True` with 7 of 9 files byte-identical.

## 4. Import issues

Codes are `SCREAMING_SNAKE_CASE` (a database constraint). Severities are
`BLOCKING`, `ADVISORY`, `INFORMATIONAL`.

Real counts for the quarantined build — 3,486 issues, 3,235 blocking:

| Code | Count | Severity | Meaning |
| --- | ---: | --- | --- |
| `ORIGIN_SOURCE_NOT_STATED` | 1,662 | BLOCKING | The record does not say who asserted it. |
| `SOURCE_VERSION_UNKNOWN_LEGACY` | 1,542 | BLOCKING | No version metadata survives this import. |
| `ENTITY_REFERENCE_UNRESOLVED` | 251 | ADVISORY | A named entity has no canonical identity yet. |
| `RECORD_TYPE_PENDING_REVIEW` | 28 | BLOCKING | `label`/`DrugLabel` equivalence is unproven. |

Plus the three build-level gate findings.

That most of the corpus is blocked is the finding, not a failure of the
importer. A legacy flattening that discarded version and attribution metadata
produces exactly this: records whose content survives and whose provenance does
not.

## 5. Sealing

- Assembled in a staging directory beside the destination, then moved with
  `os.rename` — which refuses an existing target. `os.replace` is deliberately
  not used, because it would silently overwrite a sealed build.
- **No `--force` and no `--overwrite` exist.** Two builds of one dataset go to
  two output roots and are compared with `compare-builds`.
- Canonical sorted JSON and NDJSON throughout.
- `built_at` is excluded from `content_hash`, so a rebuild is comparable.
- No absolute path is recorded anywhere in the build.
- No approval field, no reviewer name, no `approved_at`.
- Every quarantined build carries `QUARANTINED`, `LEGACY_MIGRATION`,
  `NOT_CURATED`, `NOT_EXECUTABLE`, `NOT_PUBLICATION_ELIGIBLE`.
- `dataset_lifecycle_state` stays `BUILDING`, asserted in the published schema
  rather than only in prose.

## 6. What this package cannot do

There is no command, flag or function here that approves a source policy,
approves a curation, generates a rule, moves a dataset to `QUALITY_CHECKED`,
publishes, or activates a release. `pgx-evidence`'s subcommand list is
`build`, `verify`, `inspect`, `list`, `trace`, `issues`,
`extract-draft-curation`, `render-rows`, `compare-builds` — and a test asserts
that list exactly, along with the absence of `--force`, `--overwrite`,
`--reviewer`, `--approve`, `--take-first` and `--resolve` on every subcommand.

`render-rows` renders the rows migration 0006 declares and stops. This package
ships no evidence-store persistence adapter, so a command that claimed to have
inserted them would be claiming something no code here can do.
