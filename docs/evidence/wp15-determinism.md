# WP-15 — determinism and the two hashes

| Field | Value |
|---|---|
| Document ID | `DOC-EVID-015A` |
| Work package | WP-15 — Canonical Structured Result and Deterministic Reporting |
| Contract versions | `pgx-structured-report/1`, `pgx-report-template/1`, `pgx-report-renderer/1` |
| Source | `pgx/reporting/render.py`, `pgx/reporting/structured.py` |
| Tests | `tests/unit/reporting/test_determinism.py`, `tests/integration/reporting/test_report_end_to_end.py` |

---

## 1. The contract

*The same report, template and locale render byte for byte identically, on any
machine, at any time.*

That is what makes a checksum of the rendered document worth recording. A byte
difference between two renders is then always a difference in the facts or in
the template, and never in the weather.

## 2. What is excluded from the rendered document

- a timestamp of any kind, including a "generated at" line
- any filesystem path, including the artifact's own
- any environment value: hostname, user, process id, interpreter version
- any random or generated identifier
- dictionary and set iteration order; every collection is sorted or was
  already canonically ordered upstream
- the assessment's `created_at`, `completed_at` and `actor`, which label the
  run rather than the answer

Tested by rendering the same report twice and comparing bytes, by searching
the document for each excluded value, and by rendering one assessment through
two independently constructed reports.

## 3. What is excluded from `report_hash`

`report_hash` covers the validated report **plus** the template version, the
locale and the report schema version. It excludes the case label, the actor
and both timestamps, so two reports of one assessment remain comparable across
them.

## 4. The three digests, and why there are three

| Digest | Covers | Moves when |
|---|---|---|
| `output_hash` | the governed assessment facts | a fact or a pinned version changes |
| `report_hash` | the validated report, the template, the locale, the schema | the facts change, or the presentation contract does |
| `rendered_checksum` | the bytes on disk | any of the above, or the renderer's spacing |

A renderer change moves the third and not the first two. That is precisely the
distinction an operator needs when a diff appears in a review: *did the
answer change, did the document change, or did only the whitespace change?*

Two locales of one assessment demonstrate the split directly: same
`output_hash`, two `report_hash` values, two documents.

## 5. What must change the render

- a different locale changes the document and the `report_hash`, and does not
  change the `output_hash`
- a different fact changes all three
- a different template version changes the `report_hash` and the document

## 6. Ordering

Medication sections are rendered in canonical drug-key order. Axes are in
canonical axis order inside each section. Observations are in canonical gene
order. Evidence and conflict references are sorted and deduplicated. Every one
of those is asserted.

## 7. Line endings and shape

The document uses `\n` only, starts with a level-one heading, ends with
exactly one newline, and contains no `\r` and no Python `None` repr.

## 8. How this was verified

Two renders of one report compared byte for byte; two structured reports built
independently from one canonical result compared byte for byte; a report
regenerated from its own canonical document compared with the original; the
rendered text searched for every excluded value, including the temporary
directory the synthetic ruleset happened to live in; and the whole pipeline
run twice through the application service, comparing Markdown, JSON and
checksum.

**Everything verified here is synthetic.** No real assessment exists in this
repository, so no real report has been rendered and no real document has been
published.
