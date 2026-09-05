# WP-07 legacy difference report

What the canonical build changed relative to the frozen legacy seed, measured
against the real artifacts. Generated form:
`data/canonical/PGX-DATA-20260830-900/legacy-differences.json`
(`pgx-legacy-differences/1`). Reproduce with:

```
python3 scripts/normalize.py compare-legacy \
  --build data/canonical/PGX-DATA-20260830-900 --text
```

Every figure below is derived from the artifacts. Nothing here is
hand-maintained, and no legacy row, column, hint, score, severity or conclusion
crosses into the canonical dataset: this report reads legacy files to *count and
compare* them, and its output is counts and names.

## 1. The 1,572 collision figure is not reproducible

`architecture.md`, WP-07 section, Migration bullet:

> Add regression fixtures for the 1,572 runtime dedup collisions and current
> candidate-merge drift.

The document does not say which artifact, which container set, or which identity
the count was taken over. So every interpretation that can be defined precisely
was measured against `pair_probe_raw.json`:

| Measurement | Value |
| --- | --- |
| Duplicate observations under the per-pair case-folded container family (the LEGACY-BUG-004 measure) | **1,644** |
| Duplicate groups | 1,644 |
| Member observations inside those groups | 3,288 |
| Duplicate observations across all record types | 1,644 |
| Distinct source records | 1,822 |
| Total record observations | 3,466 |
| Observations under `variantAnnotation` alone (one spelling) | 1,614 |
| Distinct variant-annotation IDs across all pair queries | 1,596 |
| Duplicate observations grouping globally by `(family, id)` rather than per pair | 1,665 |
| Rows in the legacy flattening `pair_annotation_rows.csv` | 3,346 |

**None of them is 1,572.** Outside that one sentence of `architecture.md` — and
the two places WP-07 records it as a *claim to be checked*,
`config/wp07-legacy-expectations.json` and this report — the string `1572`
appears nowhere: not in any legacy script, output, CSV or JSON. The first probe
(`clinpgx_outputs/first_probe_results.json`) has no pair endpoint at all, so the
figure did not come from there either.

The observed count is reported as observed. The deduplication key was **not**
distorted to reach the documented number, and no production module contains
`1572` as a constant — a test walks every module under `pgx/` and asserts that
no numeric literal `1572` exists.

Acceptance item **A11 is recorded FAIL** on this basis. The documented figure
should be corrected to 1,644 with its measurement stated, or the measurement it
was originally taken over should be identified; the code stays as it is either
way.

The claim lives in `config/wp07-legacy-expectations.json` as a *claim with a
citation*, measured on every build and reported as agreeing or disagreeing. That
file is data, not code: it records what the project has written down, so a
disagreement is a finding rather than a silent divergence.

## 2. Duplicate collapse

The legacy pair flattening wrote one row per container member, so a record
returned under two case-variant container names became two rows.
`pair_annotation_rows.csv` holds 3,346 rows for 1,681 distinct
`(container family, id)` records.

The canonical build keeps one record per identity **and every locator**. The
collapse is therefore reversible and countable: `duplicate-groups.ndjson` names
all 1,644 groups, `duplicate_group_members` gives every member its own row, and
`provenance.ndjson` links each canonical entity to every place it was seen.

This is a correction, not a scope decision.

## 3. Candidate-merge drift

`clean_mvp_seed_dataset.py` wrote the `.bak` files; `candidate_onboarding.py`
then rewrote the live CSVs **in place**.

| Artifact | Cleaner output (`.bak`) | Live seed | Added |
| --- | --- | --- | --- |
| `supported_drugs.csv` | 11 drugs | 15 drugs | `nortriptyline`, `pantoprazole`, `prasugrel`, `ticagrelor` |
| `drug_gene_guidelines.csv` | 30 rows / 11 pairs | 36 rows / 15 pairs | `CYP2C19::pantoprazole`, `CYP2C19::prasugrel`, `CYP2C19::ticagrelor`, `CYP2D6::nortriptyline` |

Those four drugs and four pairs came from candidate onboarding, not from a
source response. No reviewer selected them.

**The P0 canonical dataset excludes them.** It contains the 11 drugs the source
itself resolved and the 5 genes queried. `candidate_alternatives.csv` (4
manually curated rows) and `mvp_candidate_drug_gene_edges` (8,182 records
across the JSON and its derived CSV) are counted so the exclusion is visible and
arguable, and imported nowhere.

This is a scope decision, and the names are listed so it can be argued with.

## 4. Stale totals — LEGACY-BUG-007

`clinpgx_mvp_seed/mvp_seed_summary.json` was written before the merge and never
regenerated:

| Metric | Summary claims | The file beside it holds |
| --- | --- | --- |
| `supported_drugs` | 11 | 15 |
| `guideline_rows` | 30 | 36 |

Both disagreements are **expected**: they are the defect being documented, and
the report marks them so rather than treating them as surprises. Only the
`architecture.md` collision figure is flagged as an unexplained disagreement.

The V2 equivalent cannot go stale the same way: every summary count in a
canonical build is generated from the artifacts, `pgx-normalize verify`
recomputes them independently from the sealed files, and a disagreement is a
blocking data-quality finding.

## 5. Entity sets compared

| Comparison | Left | Right | Only left | Only right |
| --- | --- | --- | --- | --- |
| drugs: mutated legacy seed vs canonical P0 | 15 | 11 | the four candidate additions | — |
| drugs: cleaner output vs mutated seed | 11 | 15 | — | the four candidate additions |
| guideline pairs: cleaner output vs mutated seed | 11 | 15 | — | the four added pairs |
| genes: legacy seed vs canonical P0 | 5 | 5 | — | — |

Both directions are always reported. "The canonical build has fewer drugs" is
not the same finding as "the canonical build has different drugs", and a
one-directional difference cannot tell them apart.

## 6. Legacy files read

Read-only, for counts and identifiers. None was modified; each is digested so a
later reader can tell whether it has changed since this report was written.

| Label | Path | Rows | SHA-256 |
| --- | --- | --- | --- |
| `supported_drugs_active` | `clinpgx_mvp_seed/supported_drugs.csv` | 15 | `sha256:4ca6294c…` |
| `supported_drugs_cleaner_output` | `clinpgx_mvp_seed/supported_drugs.csv.bak` | 11 | `sha256:253e4747…` |
| `guideline_rows_active` | `clinpgx_mvp_seed/drug_gene_guidelines.csv` | 36 | `sha256:b32940ab…` |
| `guideline_rows_cleaner_output` | `clinpgx_mvp_seed/drug_gene_guidelines.csv.bak` | 30 | `sha256:24800a1e…` |
| `supported_genes` | `clinpgx_mvp_seed/supported_genes.csv` | 5 | `sha256:3726d7dd…` |
| `seed_summary` | `clinpgx_mvp_seed/mvp_seed_summary.json` | — | `sha256:5902d022…` |
| `candidate_alternatives` | `candidate_alternatives.csv` | 4 | `sha256:db5fcaac…` |

## 7. Related legacy bug IDs

`LEGACY-BUG-004` (case-variant pair duplicates), `LEGACY-BUG-007` (stale summary
counts after the seed merge), `LEGACY-BUG-010` and `LEGACY-BUG-011` (candidate
onboarding and acquisition provenance). Full definitions in
`scripts/legacy_bug_registry.py` and [legacy-inventory.md](legacy-inventory.md).
