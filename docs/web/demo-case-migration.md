# WP-17 — Migration of the legacy demo profiles P1–P6

## The source

```
clinpgx_mvp_seed/mvp_demo_profiles.json
sha256:6d370e9358ec0096fa6a7af59b88abe2435ce458ed2eaae213922f7f3f9bd1ca
2166 bytes
```

Six keys: `P1_normal`, `P2_poor_2d6`, `P3_ultrarapid_2d6`, `P4_poor_2c19`,
`P5_multiple_variants`, `P6_mixed_high_attention`. Each carries a
`profile_name`, a `phenotypes` map, and a `demo_use` string.

The source file is **not modified** by the migration. It is read, hashed, and
left where it is.

## The result

```
data/demo/wp17-development-cases.json         (7 cases)
data/demo/wp17-demo-case-manifest.json        (identity of the above)
schemas/wp17/demo-case-catalog.schema.json    (what a case may contain)
```

Regenerate with `python -m apps.web.artifacts`. The migration is deterministic:
the same source file produces byte-identical output.

Seven cases, not six: `WP17-CASE-P1` … `WP17-CASE-P6` are migrated, and
`WP17-CASE-INSUFFICIENT` is **authored** in `apps/web/demo_migration.py` to
demonstrate insufficient coverage. The manifest reports `migrated_case_count: 6`
and `authored_case_count: 1` separately, because a reader must be able to tell
which cases came from somewhere and which were written.

## What each case carries

```json
{
  "case_id": "WP17-CASE-P1",
  "case_role": "DEVELOPMENT",
  "is_synthetic": true,
  "is_validation_evidence": false,
  "is_holdout": false,
  "legacy_profile_key": "P1_normal",
  "source_file": "clinpgx_mvp_seed/mvp_demo_profiles.json",
  "source_file_sha256": "sha256:6d370e…",
  "label": "Normal metabolizma profili",
  "observations": [{"gene": "GENE:CYP1A2", "value": "NORMAL"}, …],
  "observation_count": 5,
  "demonstrates": "…",
  "migration_note": "…",
  "no_pii_assertion": "…"
}
```

Every case, without exception: `case_role: DEVELOPMENT`, `is_synthetic: true`,
`is_validation_evidence: false`, `is_holdout: false`, and the source hash.

## What was dropped, and why

**`demo_use` is not migrated.** In the legacy file it is prose of the form
"shows that patient X should avoid drug Y" — a named medicine and a conclusion
about it. Carrying it forward would have put an unreviewed clinical claim into
a catalogue, and then onto a page. Each case instead has a `migration_note`
saying the prose was dropped and why, and a `demonstrates` field written
against the *input* ("a profile reporting normal function in all five genes"),
never against an outcome.

**No medication is inferred.** The legacy prose mentions drugs; a migration
that turned those mentions into a medication list would be inventing an
assessment request that nobody made. Medications are chosen by the operator on
the case page, from the release's own catalogue.

**Phenotypes are canonicalised, not reinterpreted.**
`apps/web/demo_migration.py` calls WP-12's `normalize_profile` — the single
permitted `pgx.engine` import in this layer, exempted precisely so that the web
layer does not acquire a second normaliser that could drift from the first
(SAFETY-INV-004). Two compensating tests hold the exemption down: it reaches
that one module and no other, and no runtime module imports `demo_migration`.

**Labels are scanned.** Every label carried over from the legacy file passes
through `_checked_label()`, which runs it through the claim scanner. A legacy
label that made a prohibited claim would fail the build rather than reach a
page.

## What a case may not contain

`FORBIDDEN_CASE_FIELDS` in `apps/web/demo_cases.py` names 34 field names, and
`DevelopmentCase.__post_init__` refuses any of them **at any nesting depth**:
`genotype`, `diplotype`, `allele`, `haplotype`, `vcf`, `patient_name`, `mrn`,
`dob`, `diagnosis`, `dose`, `narrative`, `free_text`, and so on.

The constructor also refuses:

- any `case_role` other than `DEVELOPMENT`;
- `is_validation_evidence: true`;
- `is_holdout: true`.

## There is no expected result

`DevelopmentCase` has **no field for an expected outcome**, and
`FORBIDDEN_CASE_FIELDS` refuses one under any of its plausible names. This is
structural on purpose: a catalogue that recorded what each case "should"
produce would be a scoreable answer key, and a scoreable answer key is a
validation set. These are not validation cases.

`P1–P6` are development fixtures for exercising an interface. They are not
validation evidence, they are not a holdout set, and no metric may be computed
from them. The validation architecture is WP-18; the metrics are WP-21.

## Verifying the artifact

The manifest carries two hashes, because they answer two different questions:

- `catalog_file_sha256` is over the exact bytes of
  `data/demo/wp17-development-cases.json`. This is what `sha256sum` reports:

  ```
  sha256sum data/demo/wp17-development-cases.json
  ```

- `catalog_sha256` is over a canonical compact serialisation of the catalogue
  *content*. It survives the file being reformatted or re-serialised by a
  different tool, and it is the identity to quote when referring to the
  catalogue rather than to the file.

`tests/unit/web/test_demo_migration.py` asserts both against the committed
files, and asserts that they differ — a manifest whose two hashes were equal
would teach a reader nothing by having both.
