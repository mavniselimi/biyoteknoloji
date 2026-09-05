# WP-15 — migrating the legacy report path

| Field | Value |
|---|---|
| Document ID | `DOC-MIGR-015` |
| Work package | WP-15 — Canonical Structured Result and Deterministic Reporting |
| Legacy artifacts | `risk_engine.render_markdown_report`, `gemini_report_generator.py` |
| Evidence | `data/migration/wp15/report-regression-report.json` |
| Tests | `tests/unit/reporting/test_legacy_report_regression.py` |

---

## 1. What the legacy path did

Two programs produced documents.

`risk_engine.render_markdown_report` rendered a Markdown report from the
legacy result dictionary: an overall risk label, a count of risk flags, the
clinical warning as a block quote, a profile table, and a section per drug
with a per-finding block.

`gemini_report_generator.py` compacted that result into a prompt payload, sent
it to an external model, and rendered what came back — falling back to a
deterministic renderer when it could not.

## 2. What was ported

Layout, and only layout. Four concepts, published as data in
`PORTED_LAYOUT_CONCEPTS` so the claim is a list somebody can check:

| Concept | What it is |
|---|---|
| `warning_near_the_top` | the canonical warning as a block quote before anything else |
| `section_per_medication` | one section per requested medication, in canonical order |
| `gene_phenotype_table` | a table of genes and observed phenotypes |
| `finding_detail_rows` | a labelled row per attribute of a finding, rather than a paragraph |

## 3. What was not ported, and why

| Concept | Why not |
|---|---|
| `risk_label_table` | its central entry maps the absence of a rule to *"Düşük / uyarı yok"* — low, no warning. The compaction is the defect (`LEGACY-BUG-002`) |
| `numeric_score` | the legacy candidate path prints a 0–100 suitability score (`LEGACY-BUG-009`); a number beside a drug name is read as a recommendation however it is captioned |
| `free_prose_fields` | `plain_language`, `guideline_summaries`, `effect_direction` and `risk_meaning` are free scientific text no governed rule carries, and source summaries in that data carry dosing language (`LEGACY-BUG-012`) |
| `model_generated_narration` | the Gemini path sends case content to an external model and renders what returns (`LEGACY-BUG-003`) |

## 4. Status loss, recorded rather than repaired

**A legacy document cannot be upgraded into a WP-15 report.** The information
a WP-15 report is required to show was never computed by the legacy path:

- no coverage status and no coverage reason code — a reader cannot tell a
  complete evaluation from a partial one;
- no rule identity, rule version or rule content hash;
- no curation revision;
- no evidence reference that resolves in a pinned build;
- no pinned release, ruleset or dataset identity;
- no distinction between "the drug is unknown", "no rule matched" and "there
  was nothing to report", all three of which the legacy label collapsed into
  one reassuring phrase.

The harness records that loss as a finding. It does not reconstruct any of it,
because reconstructing a governed fact from a document that never carried it
is the thing this work package exists to make impossible.

## 5. No model was called

`pgx/reporting/legacy_regression.py` reads three files and calls nothing. It
does not import `gemini_report_generator`, builds no prompt, reads no key and
opens no socket, and a boundary test asserts each of those.

What it knows about the Gemini path is that path's source text plus the
recorded observation in
`data/legacy-baseline/snapshots/recorded-report-observation.json`, which was
itself produced offline with `GEMINI_API_KEY` stripped from the child
environment and `used_api` false. The harness reports `live_model_calls: 0`
and `network_used: false`, and a test asserts both.

## 6. The difference allowlist

Five intentional differences, each with the legacy behaviour observed, the
required V2 behaviour, the safety rationale and a reference:

| Difference | Legacy bug |
|---|---|
| `REPORT-ABSENCE-NOT-RENDERED-AS-LOW` | `LEGACY-BUG-002` |
| `REPORT-NO-COVERAGE-CONCEPT-IN-LEGACY` | `LEGACY-BUG-002` |
| `REPORT-NO-MODEL-IN-THE-CANONICAL-PATH` | `LEGACY-BUG-003` |
| `REPORT-NO-FREE-SCIENTIFIC-PROSE` | `LEGACY-BUG-012` |
| `REPORT-NO-SCORE-NO-RANKING` | `LEGACY-BUG-009` |

A difference outside this list is a regression, not a decision. The stored
report records `unexpected_difference_count: 0`.

## 7. The legacy snapshots are never edited

The legacy value is the evidence that something needed correcting. The report
records it so the correction is visible; changing it would delete the evidence.

**No legacy scientific value is described here as validated, approved or
clinically meaningful.** They are recorded as what a previous program
produced, and nothing more.

## 8. Reproducing this

```
pgx-report legacy-regression --text
pgx-report verify-regression --text
```

Both are offline and deterministic. The comparison carries no timestamp, no
path and no host, and regenerating it reproduces the same content hash.
