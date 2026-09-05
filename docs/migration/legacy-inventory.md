# WP-01 - Legacy Inventory and Migration Decision Matrix

| Field | Value |
|---|---|
| Document ID | `DOC-MIG-001` |
| Work package | WP-01 - Legacy Baseline and Migration Harness |
| Status | Observational baseline; no legacy file was modified |
| Machine-readable counterpart | `data/legacy-baseline/manifest.json` |
| Companion document | `docs/migration/legacy-reproducibility.md` |
| Architecture source | `architecture.md` sections 4, 15, 17 (WP-01), 22 |

> **Scope note.** This document records what the legacy system *currently does*.
> Nothing here is scientific validation, clinical evidence, or an approval. The
> migration decisions below are engineering classifications for planning; they
> are not production authorisation for any module.
>
> **WP-00 approval remains BLOCKED.** `CLAIM_BOUNDARY_STATUS` is still
> `DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW` and
> `P0_CLAIM_BOUNDARY.is_approved` is still `False`. WP-01 did not change them.

---

## A. Baseline identity

| Field | Value |
|---|---|
| Baseline ID | `WP01-LEGACY-BASELINE-001` |
| Captured (UTC) | see `captured_at_utc` in `data/legacy-baseline/manifest.json` |
| Python | 3.10.12 |
| Platform | Linux 6.8.0-136-generic, aarch64 |
| Repository root policy | Repo-relative POSIX paths only; absolute paths, `..` traversal, and symlink escapes are rejected |
| Hash algorithm | SHA-256 (exclusively) |
| Legacy + WP-00 artifacts | 64 files, 58,397,974 bytes |
| WP-01 evidence artifacts | hashed separately under `evidence_artifacts` (see section A.3) |
| Git commit | **none** |
| Git checkpoint | **BLOCKED** |
| WP-00 approval | still pending (unchanged by WP-01) |

### A.1 Git checkpoint - BLOCKED, with reasons

A local repository was initialised on branch `main` and a minimal `.gitignore`
was written. **No commit exists.** The blockers recorded in `manifest.json`
under `git_checkpoint.blocked_reasons`:

| Reason code | Detail |
|---|---|
| `GIT_IDENTITY_NOT_CONFIGURED` | Neither `user.name` nor `user.email` is set, locally or globally. WP-01 is forbidden from inventing an identity or changing Git config, so no commit can be authored. |
| `GIT_METADATA_WRITE_NOT_AUTHORIZED` | A stale `.git/index.lock` is present while no git process is running, which means an earlier git write could not finalise. This describes **this session's authorisation to modify `.git` metadata**, nothing more. |
| `NO_COMMIT_ON_BRANCH` | Consequence of the above: `git rev-parse HEAD` has no commit to resolve. |

**Scope of that second reason - corrected.** An earlier draft of this document
claimed the working directory was "a mounted folder that denies `unlink`". That
was an overstatement and has been withdrawn. Ordinary repository files in this
working tree are created, rewritten, and replaced normally - every WP-01 file
was written here. The observation is narrower: this session is not authorised to
remove files under `.git`. `git_checkpoint_state()` no longer writes a probe file
into `.git` and performs no unlink experiment; it reports only read-only
observations.

**Leftovers this session could not remove.** Cleanup was attempted after
confirming no git process was running and that every target is a zero-byte
WP-01 artifact. It returned `Operation not permitted`, so cleanup is **BLOCKED**.
Exact paths:

- `.git/index.lock` (0 bytes)
- `.git/_wp01_unlink_probe` (0 bytes, from the withdrawn probe)
- `.git/_wp01_undeletable/_probe2` (0 bytes)
- `.git/_wp01_undeletable/index.lock.stale` (0 bytes)
- `.git/_wp01_undeletable/index.lock.stale2` (0 bytes)
- `.git/_wp01_undeletable/tTqViwj` (0 bytes)
- `.git/_wp01_undeletable/symlink_probe` (symlink into a deleted temp dir)
- `.git/_wp01_undeletable/` (the directory itself)

None of them affects the working tree or any baseline artifact; read-only git
commands work. **To unblock A14:** configure a Git identity, remove the paths
above, then commit.

### A.2 Secret scan

63 text files scanned across 8 pattern categories (Google API key, AWS key,
private key block, GitHub token, Slack token, OpenAI key, JWT, generic assigned
secret). **Zero `NEEDS_REVIEW` hits.**

One API-key-shaped literal exists at `gemini_report_generator.py:22`. It is a
documentation placeholder inside the module docstring (a truncated `AIza...`
example showing how to export the variable), not a credential. The real code
path reads `os.environ.get("GEMINI_API_KEY")` at line 473. No secret value is
reproduced in this document or in any baseline artifact.

### A.3 Evidence hash chain

`manifest.json` binds two artifact lists, both sorted by path and neither
including the manifest itself:

| List | Contents |
|---|---|
| `artifacts` | 64 legacy + WP-00 files (the inputs WP-01 must preserve) |
| `evidence_artifacts` | 22 WP-01 outputs: the six snapshots, `expected-differences.json`, `reproduction-run-log.json`, the four WP-01 scripts, the regression tests and fixtures, and both migration documents |

The evidence chain makes the baseline tamper-evident without a Git commit:
editing a snapshot, the allowlist, the harness, or these documents makes
`verify-manifest` fail. It is a integrity check, not a trust anchor - a Git
commit is still required for provenance, and A14 stays BLOCKED until one exists.
The builder writes every evidence file **before** the manifest, so the manifest
is always the last thing produced.

## B. Migration decision matrix

One primary decision per module. The finer-grained `architecture.md` section 4.1
decision is preserved in the detail column.

| Module | Primary decision | architecture.md 4.1 detail | V2 target owner |
|---|---|---|---|
| `clinpgx_probe.py` | **RETIRE** | `RETIRE_AFTER_BASELINE` | none; kept as historical evidence only |
| `clinpgx_probe_v2.py` | **MIGRATE** | `MIGRATE` | `pgx/ingestion/clinpgx/` (WP-04) |
| `clean_mvp_seed_dataset.py` | **REPLACE** | `REPLACE_AFTER_MIGRATION` | `pgx/normalization/`, `pgx/curation/`, `pgx/rules/` (WP-07/09/11) |
| `risk_engine.py` | **MIGRATE** | `MIGRATE` | `pgx/engine/`, `pgx/application/` (WP-12/13/14) |
| `gemini_report_generator.py` | **REPLACE** | `SPLIT_AND_MIGRATE_P1` - split: the deterministic fallback renderer migrates, the Gemini adapter is deferred to P1 and is off by default | deterministic part `pgx/reporting/` (WP-15); LLM adapter P1-06 |
| `candidate_onboarding.py` | **KEEP** | `RESTRICT_TO_P1` - retained as a P1 legacy reference only; not migrated into P0 and never executed by V2 | candidate ingestion/curation workflow (P1-02) |
| `alternative_ranker.py` | **RETIRE** | `RETIRE_SCORE_KEEP_CONTEXT_P1` - the 0-100 score is deleted (`LEGACY-BUG-009`); only the therapeutic-context lookup may inform P1 | candidate exploration without score (P1-02) |

These are planning classifications. None of them authorises a module for
production use, and none asserts that a module's output is scientifically valid.

## C. Module detail

### C.1 `clinpgx_probe.py` - RETIRE

| Aspect | Value |
|---|---|
| Responsibility | First-generation ClinPGx OpenAPI/endpoint exploration |
| CLI entrypoint | `main()` under a `__main__` guard; **no argparse** - behaviour is fixed by module constants |
| Arguments | none |
| Reads | ClinPGx HTTP endpoints |
| Writes | `clinpgx_outputs/first_probe_results.json` |
| Network | **Yes** - `https://api.clinpgx.org/v1`, `/openapi.json`, `/swagger/openapi.json` |
| Environment variables | none |
| External dependencies | `requests` (third party) |
| Deterministic / volatile | Volatile: output depends on live API state and response time |
| Side-effect risk | Network egress to a third-party API |
| Offline rerun | **Not executed** - `NETWORK_REQUIRED_NOT_EXECUTED` |
| V2 target | none (historical evidence) |
| LEGACY-BUG IDs | `LEGACY-BUG-011` |

### C.2 `clinpgx_probe_v2.py` - MIGRATE

| Aspect | Value |
|---|---|
| Responsibility | Gene/chemical resolution and ClinPGx retrieval (pairs, guidelines, variant annotations) |
| CLI entrypoint | `main()` under a `__main__` guard; **no argparse** |
| Arguments | none |
| Reads | ClinPGx HTTP endpoints |
| Writes | 12 files in `clinpgx_outputs_v2/` (`resolved_genes.*`, `resolved_chemicals.*`, `pair_probe_raw.json`, `pair_annotation_rows.csv`, `guideline_annotation_rows.csv`, `variant_annotation_filtered_*`, `mvp_candidate_drug_gene_edges.*`, `openapi_snapshot.json`) |
| Network | **Yes** - `https://api.clinpgx.org/v1`, `/openapi.json` |
| Environment variables | none |
| External dependencies | `requests` (third party) |
| Deterministic / volatile | Volatile: no pagination guarantee, no retry policy, no acquisition-run record |
| Side-effect risk | Network egress; partial-result risk on failure |
| Offline rerun | **Not executed** - `NETWORK_REQUIRED_NOT_EXECUTED` |
| V2 target | `pgx/ingestion/clinpgx/` (WP-04) |
| LEGACY-BUG IDs | `LEGACY-BUG-004`, `LEGACY-BUG-011` |

### C.3 `clean_mvp_seed_dataset.py` - REPLACE

| Aspect | Value |
|---|---|
| Responsibility | Normalisation, dedup, manual effect hints, demo seed build |
| CLI entrypoint | `main()` with argparse |
| Arguments | `--input-dir` (default `clinpgx_outputs_v2`), `--out-dir` (required) |
| Reads | `resolved_genes.json`, `resolved_chemicals.json`, `pair_probe_raw.json`, `variant_annotation_filtered_raw.json` |
| Writes | `supported_genes.csv`, `supported_drugs.csv`, `drug_gene_guidelines.csv`, `phenotype_effect_rules.csv`, `mvp_demo_profiles.json`, `mvp_seed_summary.json` |
| Network | none |
| Environment variables | none |
| External dependencies | stdlib only |
| Deterministic / volatile | **Deterministic** - verified byte-identical against the `.bak` backups |
| Side-effect risk | Writes only into `--out-dir`; **see WP01-OBS-001 below** |
| Offline rerun | **PASS** - rebuilds 5 / 11 / 30 / 3084 into a temporary directory |
| V2 target | `pgx/normalization/`, `pgx/curation/`, `pgx/rules/` |
| LEGACY-BUG IDs | `LEGACY-BUG-005`, `LEGACY-BUG-006` |

### C.4 `risk_engine.py` - MIGRATE

| Aspect | Value |
|---|---|
| Responsibility | Phenotype matching, risk flags, same-gene notes, deterministic report input |
| CLI entrypoint | `main()` with argparse |
| Arguments | `--seed-dir`, `--profile-id`, `--profile-json`, `--drugs`, `--out-dir`, `--max-evidence`, `--list-profiles`, `--list-drugs` |
| Reads | the seed CSV/JSON files under `--seed-dir` |
| Writes | `risk_result_full.json`, `risk_findings.csv`, `risk_report.md`, `gemini_input.json` |
| Network | none |
| Environment variables | none |
| External dependencies | stdlib only |
| Deterministic / volatile | **Deterministic** - all four outputs byte-identical across repeated runs |
| Side-effect risk | Writes only into `--out-dir` |
| Offline rerun | **PASS** - P2 CYP2C19-poor case reproduced |
| V2 target | `pgx/engine/`, `pgx/application/` |
| LEGACY-BUG IDs | `LEGACY-BUG-001`, `LEGACY-BUG-002`, `LEGACY-BUG-003` |

### C.5 `gemini_report_generator.py` - REPLACE (split)

| Aspect | Value |
|---|---|
| Responsibility | Optional Gemini rendering with a deterministic offline fallback |
| CLI entrypoint | `main()` with argparse |
| Arguments | `--input`, `--out-dir`, `--api-key`, `--model`, `--no-api`, `--save-prompt`, `--temperature` |
| Reads | `gemini_input.json` produced by `risk_engine.py` |
| Writes | `gemini_report.md`, `gemini_report_payload.json`, `gemini_report_status.json`, optionally `gemini_prompt.txt` |
| Network | **Conditional** - calls the Gemini API when a key is present; `--no-api` forces the offline fallback |
| Environment variables | `GEMINI_API_KEY` (read at line 473) |
| External dependencies | stdlib for the fallback path |
| Deterministic / volatile | Fallback report is deterministic; `gemini_report_status.json` carries `created_at`, `input_file`, `output_file` (volatile) |
| Side-effect risk | Network egress and API cost when a key is present |
| Offline rerun | **PASS with `--no-api`** and `GEMINI_API_KEY` stripped from the child environment |
| V2 target | deterministic part `pgx/reporting/` (WP-15); LLM adapter P1-06 |
| LEGACY-BUG IDs | `LEGACY-BUG-003`, `LEGACY-BUG-012` |

### C.6 `candidate_onboarding.py` - KEEP (P1 legacy reference only)

| Aspect | Value |
|---|---|
| Responsibility | Candidate chemical resolution and optional merge into the active seed |
| CLI entrypoint | `main()` with argparse |
| Arguments | `--candidate-file`, `--seed-dir`, `--out-dir`, `--clinpgx-outputs-dir`, `--genes`, `--source-drug`, `--current-drugs`, `--profile-id`, `--dry-run`, `--merge` |
| Reads | `candidate_alternatives.csv`, seed files, `clinpgx_outputs_v2/` |
| Writes | 9 files in `clinpgx_mvp_seed/candidate_onboarding_outputs/`; **with `--merge`, rewrites the active seed in place and overwrites `.bak`** |
| Network | **Yes** - `https://api.clinpgx.org/v1` (line 28), via `requests` with a `urllib` fallback |
| Environment variables | none |
| External dependencies | `requests` when available; `urllib` fallback |
| Deterministic / volatile | Volatile: depends on live API responses |
| Side-effect risk | **Highest in the repository** - network egress *and* destructive in-place mutation of the active seed |
| Offline rerun | **`--help` only.** Onboarding, acquisition, and `--merge` were **not executed** (`NETWORK_AND_MUTATION_FORBIDDEN_NOT_EXECUTED`). Its previously recorded outputs are hashed and inventoried instead. |
| V2 target | candidate ingestion/curation workflow (P1-02) |
| LEGACY-BUG IDs | `LEGACY-BUG-007`, `LEGACY-BUG-010`, `LEGACY-BUG-011` |

### C.7 `alternative_ranker.py` - RETIRE (score deleted; context may inform P1)

| Aspect | Value |
|---|---|
| Responsibility | Manual candidate comparison and a 0-100 heuristic score |
| CLI entrypoint | `main()` with argparse |
| Arguments | `--seed-dir`, `--source-drug`, `--profile-id`, `--current-drugs`, `--candidate-file`, `--graph-file`, `--out-dir` |
| Reads | seed files, `candidate_alternatives.csv`, `drug_graph_edges.csv`; **imports `risk_engine` directly** |
| Writes | `alternative_result_full.json`, `alternative_candidates.csv`, `alternative_report.md` |
| Network | none |
| Environment variables | none |
| External dependencies | stdlib plus an in-repo import of `risk_engine` |
| Deterministic / volatile | Deterministic given a fixed seed |
| Side-effect risk | Writes only into `--out-dir`; **presentation risk**: emits a score that reads as a safety ranking |
| Offline rerun | **PASS** - clopidogrel beta case reproduced |
| V2 target | candidate exploration without score (P1-02) |
| LEGACY-BUG IDs | `LEGACY-BUG-008`, `LEGACY-BUG-009` |

### C.8 Observed finding not in the architecture registry

| ID | Finding |
|---|---|
| `WP01-OBS-001` | `clean_mvp_seed_dataset.py:239` (`find_file`) silently falls back to `cwd/clinpgx_outputs_v2/<file>` when a file is absent from `--input-dir`. A run with `--input-dir __no_such_dir__` therefore **exits 0** and emits a complete, correct-looking 5/11/30/3084 seed built from a different source, while printing the input directory it did not use. |

**Why this matters.** `--input-dir` cannot be trusted as a provenance record: the
output does not prove which directory it came from. The WP-01 reproduction is
still sound because it ran from the repository root, where the explicit path and
the fallback path coincide - but that is a coincidence of the working directory,
not a guarantee from the tool.

`WP01-OBS-001` is **not** one of the twelve registered `LEGACY-BUG-*` IDs.
`architecture.md` is the source of truth for that registry and WP-01 must not
modify it. Assigning this finding a `LEGACY-BUG-013` ID requires a human
decision and an Architecture Decision Record. It is raised here for review and is
relevant to WP-06 (immutable raw snapshots) and WP-04 (acquisition provenance).
It is recorded, never accepted as correct behaviour.

### C.9 Comparison harness correctness properties

The harness in `scripts/compare_legacy_v2.py` enforces three properties that the
first WP-01 draft did not:

**Exact artifact identity.** An expected-difference rule names one exact
`artifact_id`. There is no basename or suffix fallback, so a file in another
directory that happens to share a name can never borrow a known-bug rule.
Directory comparison derives each identity as a normalised relative POSIX path
from the comparison root and rejects `..`, absolute paths, wildcards, and
symlinks resolving outside the root. Single-file comparison reports
`<UNIDENTIFIED-ARTIFACT>` unless `--artifact-id` is given, and that value can
never match an active rule.

**Identity-addressed list selectors.** Registered lists are addressed by what
their items *are*, not where they sit:
`$.drug_results[drug=codeine].overall_risk_level`. Reordering `drug_results`
therefore cannot move the codeine expectation onto warfarin. List order is still
significant: a changed identity sequence produces its own explicit
`$.drug_results[order]` difference with reason `list_order_mismatch`, which is
not allowlisted. Items added or removed are reported by identity
(`list_item_added` / `list_item_removed`). A duplicate identity is refused with
status `AMBIGUOUS_IDENTITY` and exit code 2 rather than silently matching the
first occurrence. Lists with no registered identity key stay index-addressed,
which is correct for scalar arrays.

**One rule per affected entity.** Bugs with several observable entities carry
one rule each, so a partial V2 fix is visible:

| Bug | Rules |
|---|---|
| `LEGACY-BUG-002` | `...-CODEINE`, `...-WARFARIN` |
| `LEGACY-BUG-003` | `...-COMPACT-KEYS` |
| `LEGACY-BUG-007` | `...-SUPPORTED-DRUGS`, `...-GUIDELINE-ROWS` |
| `LEGACY-BUG-009` | `...-PRASUGREL-SCORE-REMOVAL`, `...-TICAGRELOR-SCORE-REMOVAL` |

Seven active rules in total; the remaining eight bugs stay
`registered_not_allowlisted` with no selector, because no V2 artifact exists yet
to observe. All twelve keep `protected_as_correct: false`.

## D. Data and output areas

| Path | Meaning | Size | Files | Kind | Mutable | V2 treatment | Baseline manifest role | Known issue |
|---|---|---|---|---|---|---|---|---|
| `clinpgx_outputs/` | V1 exploration output | 16,348,350 B | 1 | network output | No | Legacy snapshot only | `legacy_raw_output` | none recorded |
| `clinpgx_outputs_v2/` | Raw/intermediate ClinPGx retrieval output | 36,567,083 B | 12 | network output | No | Input to WP-06 snapshot migration | `legacy_raw_output` | `LEGACY-BUG-004`, `LEGACY-BUG-011` on the pair files |
| `clinpgx_mvp_seed/` (root files) | Active mutable seed | 2,425,540 B | 6 | derived dataset | **Yes** | Legacy dataset snapshot; not an immutable V2 dataset | `legacy_seed_dataset` | `LEGACY-BUG-005/006/007` |
| `clinpgx_mvp_seed/*.bak` | Pre-merge backups | 2,406,067 B | 3 | backup | **Yes (overwritten on re-merge)** | Sole surviving pre-merge evidence | `legacy_seed_backup` | `LEGACY-BUG-010` |
| `clinpgx_mvp_seed/risk_outputs/` | Recorded risk run | part of 207,657 B | 4 | derived output | Yes | Regression evidence | `legacy_derived_output` | `LEGACY-BUG-001/002/003` |
| `clinpgx_mvp_seed/alternative_outputs/` | Recorded ranker run (pre-beta) | part of 207,657 B | 3 | derived output | Yes | P1 reference | `legacy_derived_output` | `LEGACY-BUG-008/009` |
| `clinpgx_mvp_seed/alternative_outputs_beta/` | Recorded beta ranker run | part of 207,657 B | 3 | derived output | Yes | P1 reference | `legacy_derived_output` | `LEGACY-BUG-008/009` |
| `clinpgx_mvp_seed/candidate_onboarding_outputs/` | Recorded onboarding run | part of 207,657 B | 9 | derived output | Yes | P1 reference; **not re-executed** | `legacy_derived_output` | `LEGACY-BUG-007/010/011` |
| `final_report/` | Recorded Gemini report artifacts | 17,600 B | 4 | report output | No | Legacy report snapshot | `legacy_report_artifact` | `LEGACY-BUG-012` |
| `candidate_alternatives.csv` | Manually curated candidate lookup (4 rows) | 425 B | 1 | manual seed | No | P1 development seed only | `legacy_candidate_seed` | `LEGACY-BUG-008` context |
| `drug_graph_edges.csv` | CSV pseudo-graph/context (22 rows) | 1,678 B | 1 | manual seed | No | P1 migration seed only | `legacy_candidate_seed` | `LEGACY-BUG-008` |
| `MVP_1_TEKNIK_DURUM_RAPORU.md` | Historical technical report | 25,808 B | 1 | document | No | Evidence for legacy inventory, **not** current-state authority | `legacy_historical_doc` | counts inside may be stale |

### D.1 Stale-provenance warning

`MVP_1_TEKNIK_DURUM_RAPORU.md` and `clinpgx_mvp_seed/mvp_seed_summary.json` both
predate the candidate merge. Neither may be quoted as the current state. The
authoritative current counts are in `manifest.json` under `baseline_facts`, and
`data/legacy-baseline/snapshots/current-active-seed.json` records both the real
counts and the stale ones side by side.

## E. Legacy to proposed V2 entity field mapping

**Field mapping only.** No V2 model, table, or migration is created by WP-01. The
V2 column names below are proposals for WP-02 and later, not existing schema.

### E.1 `supported_genes.csv` (5 rows)

| Legacy field | Proposed V2 entity.field | Note |
|---|---|---|
| `gene` | `Gene.symbol` | canonical HGNC symbol expected in V2 |
| `gene_id` | `Gene.legacy_source_id` | ClinPGx identifier; keep for traceability |
| other descriptive columns | `Gene.metadata` | not authoritative until WP-07 canonicalisation |

### E.2 `supported_drugs.csv` (active 15 / original 11)

| Legacy field | Proposed V2 entity.field | Note |
|---|---|---|
| `drug` | `Drug.display_name` | |
| `drug_id` | `Drug.legacy_source_id` | |
| `canonical_name` | `Drug.canonical_name` | WP-07 resolves the true canonical form |
| `types` | `Drug.classification[]` | |
| `drug_behavior_hint` | `Drug.behavior_hint` | descriptive only; must not drive attention |
| `pediatric` | `Drug.pediatric_flag` | |
| `mvp_supported` | *(dropped)* | replaced by the ruleset coverage manifest (WP-13) |
| `smiles` | `Drug.structure_smiles` | |

### E.3 `drug_gene_guidelines.csv` (active 36 / original 30)

| Legacy field | Proposed V2 entity.field | Note |
|---|---|---|
| pair identifiers | `Interpretation.drug_id` + `Interpretation.gene_id` | |
| guideline name/source | `EvidenceRecord.source_ref` | |
| summary text | `EvidenceRecord.source_text` | preserved verbatim; **never** rendered to users unscanned (`LEGACY-BUG-012`) |
| implied strength | `Interpretation.evidence_strength` | must be re-derived per record, not per pair (`LEGACY-BUG-005`) |

### E.4 `phenotype_effect_rules.csv` (3,084 rows)

| Legacy field | Proposed V2 entity.field | Note |
|---|---|---|
| `gene`, `drug` | `Rule.gene_id`, `Rule.drug_id` | |
| phenotype | `Rule.phenotype_set[]` | **explicit set**; no implicit RAPID/ULTRARAPID equivalence (`LEGACY-BUG-001`) |
| effect direction | `Rule.effect_code` | |
| severity / risk level | `Rule.attention_level` | renamed; `NOT_ASSESSED` is not on the same scale |
| evidence strength | `Interpretation.evidence_strength` | moves off the rule row (`LEGACY-BUG-005`) |
| manual hint rows | `CurationProposal` with `state=DRAFT` | never auto-validated (`LEGACY-BUG-006`) |
| *(absent)* | `Rule.lifecycle_state`, `Rule.version`, `Rule.approved_by` | new in V2; no legacy source |

### E.5 `mvp_demo_profiles.json` (6 profiles)

| Legacy field | Proposed V2 entity.field | Note |
|---|---|---|
| `profile_id` | `ValidationCase.case_id` | |
| `profile_name` | `ValidationCase.title` | |
| `phenotypes` | `ValidationCase.phenotypes{gene: phenotype}` | |
| `demo_use` | `ValidationCase.rationale` | |
| *(absent)* | `ValidationCase.role` | **must become `DEVELOPMENT`** - these six are development/regression seeds only (`SAFETY-INV-009`) |
| *(absent)* | `ValidationCase.provenance`, `.synthetic_status`, `.no_pii_assertion`, `.who_has_seen` | new in WP-18 |

### E.6 `risk_result_full.json`

| Legacy field | Proposed V2 field | Note |
|---|---|---|
| `overall_risk_level` | `overall_attention` | `none` must become `NOT_ASSESSED` or `NO_ACTIVE_ATTENTION` (`LEGACY-BUG-002`) |
| `overall_risk_label_tr` | *(dropped)* | localisation belongs to the render layer |
| `overall_risk_score` | *(dropped)* | no numeric risk score in V2 |
| `risk_flag_count` | `finding_count` | |
| `drug_results[].status` | `medications[].coverage` + `coverage_reasons[]` | `gene_drug_known_no_profile_match` becomes an explicit reason code |
| `findings[].risk_level` | `findings[].attention` | |
| `findings[].effect_direction` | `findings[].effect_code` | |
| `findings[].plain_language` | *(regenerated)* | must be claim-scanned (`SAFETY-INV-010`) |
| `findings[].guideline`, `evidence_examples` | `findings[].evidence_refs[]` | must be resolvable IDs (`SAFETY-INV-006`) |
| `clinical_warning` | `canonical_clinical_warning(language)` | one canonical text from `pgx/domain/claims.py` |
| `same_gene_attention` | `warnings[]` | explicitly not a drug-drug interaction claim |
| *(absent)* | `release`, `input_hash`, `output_hash` | new in WP-03/WP-14 (`SAFETY-INV-007`) |

### E.7 `gemini_input.json`

| Legacy field | Proposed V2 field | Note |
|---|---|---|
| compact `findings[]` | `StructuredReport.findings[]` | the compact form **drops `status`** and must not (`LEGACY-BUG-003`) |
| `must_include_warning` | `StructuredReport.warning` | full canonical text, not a truncated first sentence |
| `task`, `style.avoid[]` | *(dropped)* | replaced by a schema-constrained renderer contract (P1-06) |

### E.8 Candidate onboarding outputs (9 files)

| Legacy artifact | Proposed V2 target | Note |
|---|---|---|
| `candidate_supported_drugs_extension.csv` | `CurationProposal` (drug scope) | draft state only |
| `candidate_drug_gene_guidelines_extension.csv` | `CurationProposal` (interpretation scope) | draft state only |
| `candidate_phenotype_effect_rules_extension.csv` | `CurationProposal` (rule scope) | legacy already marks these `usable_for_mvp=no`; V2 keeps them unapproved (`LEGACY-BUG-006`) |
| `candidate_label_rows.csv`, `candidate_variant_annotation_rows.csv` | `EvidenceRecord` | separate from rules |
| `candidate_pair_probe_raw.json` | immutable raw snapshot (WP-06) | |
| `candidate_onboarding_result_full.json`, `..._report.md` | run artifact | not a dataset |

### E.9 `candidate_alternatives.csv` (4 rows) and `drug_graph_edges.csv` (22 rows)

| Legacy field | Proposed V2 field | Note |
|---|---|---|
| candidate rows | `CandidateContext.candidate_drug` | P1-02 only |
| edge rows | `CandidateContext.relation` | a flat lookup, **not** graph traversal (`LEGACY-BUG-008`) |
| *(derived)* score | *(deleted)* | removed from V2 P0/P1 (`LEGACY-BUG-009`) |

### E.10 Report artifacts

| Legacy artifact | Proposed V2 target | Note |
|---|---|---|
| `final_report/gemini_report.md` | `DeterministicReport` render | the deterministic report is the final P0 report |
| `final_report/gemini_report_payload.json` | `StructuredReport` | |
| `final_report/gemini_report_status.json` | audit record (WP-23) | volatile fields (`created_at`, `input_file`, `output_file`) become audit metadata |
| `final_report/gemini_prompt.txt` | P1-06 prompt artifact | retained as legacy evidence |

## F. What WP-01 did not do

- did not modify any legacy `.py`, `.csv`, `.json`, `.md`, `.txt`, or `.bak` file;
- did not run the cleaner against the active seed;
- did not run `candidate_onboarding.py` beyond `--help`, and never with `--merge`;
- did not make any network call - no ClinPGx, no Gemini, no other LLM;
- did not read or set `GEMINI_API_KEY`;
- did not fix any known legacy defect;
- did not change risk or phenotype semantics;
- did not create V2 domain models, a database, an API, or packaging;
- did not modify `architecture.md` or any WP-00 file;
- did not change the WP-00 approval status.
