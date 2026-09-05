# WP-01 - Legacy Reproducibility Log

| Field | Value |
|---|---|
| Document ID | `DOC-MIG-002` |
| Work package | WP-01 - Legacy Baseline and Migration Harness |
| Baseline ID | `WP01-LEGACY-BASELINE-001` |
| Captured (UTC) | see `captured_at_utc` in `data/legacy-baseline/manifest.json` |
| Python | 3.10.12 |
| Platform | Linux 6.8.0-136-generic, aarch64 |
| Working directory policy | Every command ran from the repository root |
| Machine-readable counterpart | `data/legacy-baseline/reproduction-run-log.json` |

> Every command, exit code, and hash below was actually executed and recorded.
> Nothing in this log is reconstructed from memory.
>
> **No network call was made.** No ClinPGx endpoint, no Gemini API, no other LLM
> API. `GEMINI_API_KEY` was stripped from every child process environment by
> `run_legacy(..., env_remove=("GEMINI_API_KEY",))`.
>
> These runs reproduce legacy behaviour **including known defects**. They are
> not clinical validation and not protected expected results.

---

## 1. Run summary

| # | Step | Exit | Result | Network | Legacy files changed |
|---|---|---|---|---|---|
| 1 | original cleaner rebuild | 0 | **PASS** | No | none |
| 2 | risk engine P2 CYP2C19-poor | 0 | **PASS** | No | none |
| 3 | alternative ranker beta (clopidogrel) | 0 | **PASS** | No | none |
| 4 | gemini report `--no-api` fallback | 0 | **PASS** | No | none |
| 5 | `clean_mvp_seed_dataset.py --help` | 0 | **PASS** | No | none |
| 6 | `risk_engine.py --help` | 0 | **PASS** | No | none |
| 7 | `gemini_report_generator.py --help` | 0 | **PASS** | No | none |
| 8 | `candidate_onboarding.py --help` | 0 | **PASS** | No | none |
| 9 | `alternative_ranker.py --help` | 0 | **PASS** | No | none |
| 10 | `clinpgx_probe.py` | - | **BLOCKED** | No | none |
| 11 | `clinpgx_probe_v2.py` | - | **BLOCKED** | No | none |
| 12 | candidate onboarding acquisition / `--merge` | - | **BLOCKED** | No | none |

Steps 10-12 are deliberate WP-01 boundaries, not failures.

## 2. Step 1 - Original cleaner rebuild

```
python3 clean_mvp_seed_dataset.py \
  --input-dir clinpgx_outputs_v2 \
  --out-dir <TEMPORARY-DIRECTORY>
```

| Field | Value |
|---|---|
| Output location | `TemporaryDirectory` (never `clinpgx_mvp_seed/`) |
| Exit code | `0` |
| stdout / stderr | 42 lines / 0 lines |
| Result | **PASS** |
| Network | none |
| Legacy files changed | none (active seed hashes re-verified after the run) |

Reproduced counts: **5 genes / 11 drugs / 30 guideline rows / 3,084 effect rows**
- exactly the expected original-cleaner result.

| Artifact | Data rows | Bytes | SHA-256 (truncated) | Matches active seed | Matches `.bak` |
|---|---|---|---|---|---|
| `drug_gene_guidelines.csv` | 30 | 70080 | 24800a1ef628c384... | **no** | yes |
| `mvp_demo_profiles.json` | - | 2166 | 6d370e9358ec0096... | yes | - |
| `mvp_seed_summary.json` | - | 1731 | 5902d022e2b4ef91... | yes | - |
| `phenotype_effect_rules.csv` | 3084 | 2334528 | 7e4f7d2504ec00d0... | yes | yes |
| `supported_drugs.csv` | 11 | 1459 | 253e4747083740bc... | **no** | yes |
| `supported_genes.csv` | 5 | 3743 | 3726d7dde14d3a53... | yes | - |
### 2.1 What this proves

The cleaner is **byte-deterministic**: the rebuild reproduces the `.bak` backups
exactly. Only two files differ from the active seed - `supported_drugs.csv` and
`drug_gene_guidelines.csv` - which are precisely the two files the candidate
merge rewrote.

**Direct proof of `LEGACY-BUG-007`:** the freshly rebuilt `mvp_seed_summary.json`
is byte-identical (`5902d022e2b4ef91...`) to the **active** summary on disk. The
merge updated the two CSV files but never regenerated the summary, so the summary
still describes a pre-merge dataset that no longer exists.

> These counts are evidence of **legacy reproducibility only**. They are not a
> scientific result and carry no claim of correctness.

## 3. Step 2 - Risk engine, P2 CYP2C19-poor

```
python3 risk_engine.py \
  --seed-dir clinpgx_mvp_seed \
  --profile-id P2_cyp2c19_poor \
  --drugs clopidogrel,voriconazole,codeine,warfarin,amitriptyline \
  --out-dir <TEMPORARY-DIRECTORY>
```

| Field | Value |
|---|---|
| Exit code | `0` |
| stdout / stderr | 21 lines / 0 lines |
| Result | **PASS** |
| Network | none |
| Legacy files changed | none |
| Determinism | all four artifacts byte-identical across a repeated run |

Overall: `overall_risk_level = high`, `risk_flag_count = 3`,
`same_gene_attention = 2 entries`.

| Drug | Legacy `overall_risk_level` | Active flags |
|---|---|---|
| `clopidogrel` | high | 1 |
| `voriconazole` | high | 1 |
| `codeine` | none | 0 |
| `warfarin` | none | 0 |
| `amitriptyline` | medium | 1 |
| Artifact | Bytes | SHA-256 (truncated) |
|---|---|---|
| `gemini_input.json` | 6333 | b930d34197e4d764... |
| `risk_findings.csv` | 7812 | 100cc96c554f6723... |
| `risk_report.md` | 4915 | ab7b462806326cc0... |
| `risk_result_full.json` | 30049 | 39399dcecc551339... |
### 3.1 Recorded defects in this run

- **`LEGACY-BUG-002`** - codeine and warfarin return `overall_risk_level = "none"`
  with finding status `gene_drug_known_no_profile_match`. The legacy label map
  renders `none` as `"Düşük / uyarı yok"`, conflating *not assessed* with *low*.
  Recorded, **not** protected as correct.
- **`LEGACY-BUG-003`** - the compact `gemini_input.json` finding payload drops the
  per-finding `status` key that the full result carries, so the LLM input cannot
  distinguish "no active flag" from "not assessed". The snapshot records both key
  sets and their difference.
- **`LEGACY-BUG-001`** - not exercised by this case (POOR/NORMAL phenotypes only),
  so no selector was invented for it.

The legacy warning text was captured verbatim into the snapshot and is explicitly
marked as **not** the canonical warning.

## 4. Step 3 - Alternative ranker beta (clopidogrel)

```
python3 alternative_ranker.py \
  --seed-dir clinpgx_mvp_seed \
  --source-drug clopidogrel \
  --profile-id P2_cyp2c19_poor \
  --current-drugs clopidogrel,voriconazole,codeine,warfarin,amitriptyline \
  --candidate-file candidate_alternatives.csv \
  --graph-file drug_graph_edges.csv \
  --out-dir <TEMPORARY-DIRECTORY>
```

| Field | Value |
|---|---|
| Exit code | `0` |
| stdout / stderr | 17 lines / 0 lines |
| Result | **PASS** |
| Network | none |
| Legacy files changed | none |

| Candidate | `mvp_data_status` | Legacy score (**unprotected**) |
|---|---|---|
| `prasugrel` | insufficient_pgx_rule_data | 59 |
| `ticagrelor` | insufficient_pgx_rule_data | 59 |
| Artifact | Bytes | SHA-256 (truncated) |
|---|---|---|
| `alternative_candidates.csv` | 593 | 6623e50ea8224dda... |
| `alternative_report.md` | 4692 | e8214ec67c90df79... |
| `alternative_result_full.json` | 4835 | aefd724c02a93a09... |
### 4.1 Recorded defects in this run

- **`LEGACY-BUG-009`** - both candidates carry
  `mvp_data_status = insufficient_pgx_rule_data` **and** a numeric score of 59
  under the label `MVP alternatif uygunluk ön skoru`. A score attached to a
  candidate with no usable rule creates a false impression of evaluability. The
  score is recorded as legacy evidence and is **explicitly not** a protected
  expected result; V2 deletes it.
- **`LEGACY-BUG-008`** - `drug_graph_edges.csv` is consumed as a flat lookup, not
  traversed. The "graph" naming overstates the capability.

**No candidate preference or safety conclusion is drawn from this run.** The
snapshot records data availability only (`SAFETY-INV-005`).

## 5. Step 4 - Recorded report artifacts and offline fallback

Recorded artifacts hashed **without executing anything**:

| Artifact | Bytes | SHA-256 (truncated) |
|---|---|---|
| `final_report/gemini_prompt.txt` | 6881 | 052ed7288f4bed3f... |
| `final_report/gemini_report.md` | 4536 | 84d71835057f9bc3... |
| `final_report/gemini_report_payload.json` | 5812 | 7c120e3f446cee7d... |
| `final_report/gemini_report_status.json` | 371 | 819cbad38f688e51... |
Offline fallback observation:

```
python3 gemini_report_generator.py \
  --input clinpgx_mvp_seed/risk_outputs/gemini_input.json \
  --no-api \
  --out-dir <TEMPORARY-DIRECTORY>
```

| Field | Value |
|---|---|
| Exit code | `0` |
| stdout / stderr | 11 lines / 0 lines |
| Result | **PASS** |
| `used_api` | `false` |
| `fallback_used` | `true` |
| API key supplied | **no** - `GEMINI_API_KEY` stripped from the child environment |
| Network | none |
| Legacy files changed | none |

This is a **fallback output**, not a Gemini rendering.

### 5.1 Volatile-field normalisation

`gemini_report_status.json` is **not** excluded from hashing. It is normalised
on exactly three documented fields and then hashed as canonical JSON, so every
remaining field stays covered:

| Artifact | JSON path | Reason | Normalised to |
|---|---|---|---|
| `gemini_report_status.json` | `$.created_at` | wall-clock timestamp | `<NORMALIZED:TIMESTAMP>` |
| `gemini_report_status.json` | `$.input_file` | absolute temporary path | `<NORMALIZED:TEMP_PATH>` |
| `gemini_report_status.json` | `$.output_file` | absolute temporary path | `<NORMALIZED:TEMP_PATH>` |

The snapshot records `raw_sha256`, `normalized_sha256`, the exact
`normalized_json_paths` applied, and the non-volatile field values
(`used_api`, `fallback_used`, `validation_warnings`, `metadata`). Two
regression tests pin the behaviour:

- changing only a timestamp or a path leaves `normalized_sha256` unchanged;
- changing `used_api`, `fallback_used`, `validation_warnings`, or `metadata`
  changes it.

Every other artifact from this run is hashed as raw bytes. A scan confirmed that
`risk_result_full.json`, `gemini_input.json`, `alternative_result_full.json`,
and `gemini_report_payload.json` contain **zero** temporary paths and **zero**
timestamps, so no normalisation was needed or applied to them.

There is no wildcard rule, no subtree ignore, and no whole-file exclusion
anywhere in the baseline.

Legacy warning wording in the fallback report is preserved as legacy evidence
and is **not** marked canonical.

## 6. Steps 5-9 - CLI contracts

`--help` captured for every offline-safe argparse module. Each exited `0`; the
help text hash and the declared option set are stored in
`data/legacy-baseline/snapshots/cli-contracts.json`.

| Module | Exit | Help lines | Result |
|---|---|---|---|
| `clean_mvp_seed_dataset.py` | 0 | 12 | **PASS** |
| `risk_engine.py` | 0 | 21 | **PASS** |
| `gemini_report_generator.py` | 0 | 17 | **PASS** |
| `candidate_onboarding.py` | 0 | 17 | **PASS** |
| `alternative_ranker.py` | 0 | 22 | **PASS** |

`candidate_onboarding.py --help` is safe and was the **only** invocation of that
module. Its acquisition path and `--merge` were never run.

## 7. Steps 10-12 - Deliberately not executed

| Step | Reason code | Why |
|---|---|---|
| `clinpgx_probe.py` | `NETWORK_REQUIRED_NOT_EXECUTED` | Live ClinPGx HTTP retrieval via the third-party `requests` package. No argparse; behaviour is fixed by module constants. Running it would make a network call. |
| `clinpgx_probe_v2.py` | `NETWORK_REQUIRED_NOT_EXECUTED` | Same, plus it writes into `clinpgx_outputs_v2/`, which is frozen baseline input. |
| `candidate_onboarding.py` acquisition / `--merge` | `NETWORK_AND_MUTATION_FORBIDDEN_NOT_EXECUTED` | Calls `https://api.clinpgx.org/v1` **and** `--merge` rewrites the active seed in place while overwriting the only `.bak` backups (`LEGACY-BUG-010`). |

Instead of executing them, WP-01 recorded, by static AST inspection: main
entrypoint presence, CLI argument mechanism, third-party imports, hardcoded base
URLs, and declared output filenames. Their previously recorded outputs are
hashed and inventoried.

**A module that was not executed is not a baseline failure.** It is a recorded
boundary with a reason code.

## 7.1 Comparison harness properties exercised

Beyond the legacy reruns, the regression suite proves the harness itself:

| Property | Negative proof |
|---|---|
| Exact artifact identity | a file with the same basename in another directory does not match an active rule |
| Identity-addressed selectors | reordering `drug_results` does not apply the codeine rule to warfarin |
| Explicit order difference | a reordered list still produces `$.drug_results[order]`, unallowlisted |
| Duplicate identity | refused with `AMBIGUOUS_IDENTITY` and exit 2, never a silent first match |
| Per-entity rules | prasugrel and ticagrelor each match only their own rule |
| Evidence chain | a mutated snapshot or allowlist hash makes `verify-manifest` fail |
| Normalisation scope | a non-volatile status field change alters the normalized hash |
| No silent skips | a missing required baseline artifact fails; it does not skip |

## 8. Preservation verification

The seven legacy scripts, `architecture.md`, all WP-00 files, and every legacy
data/output artifact were SHA-256 hashed **before** any WP-01 file was created
and **again** after all work completed.

| Scope | Files | Result |
|---|---|---|
| Seven legacy Python modules | 7 | **unchanged** |
| `architecture.md` | 1 | **unchanged** |
| WP-00 docs, code, tests | 8 | **unchanged** |
| Legacy seed, backups, raw outputs, reports, candidate seeds | 48 | **unchanged** |
| **Total** | **64** | **0 differences** |

Each reproduction step additionally re-hashed the nine active seed files
immediately after the run and asserted they were unchanged; those assertions are
part of the regression suite, not just this log.

## 9. Reproducing this baseline

```
python3 scripts/build_legacy_baseline.py --repo-root .
python3 scripts/compare_legacy_v2.py verify-manifest \
  --repo-root . --manifest data/legacy-baseline/manifest.json
python3 -m unittest discover -s tests/regression -p 'test*.py' -v
```

The builder writes only into `data/legacy-baseline/`; every legacy rerun it
performs goes to a `TemporaryDirectory` and it refuses, via
`assert_not_live_seed()`, to target `clinpgx_mvp_seed/`.
