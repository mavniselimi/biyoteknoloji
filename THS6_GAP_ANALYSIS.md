# THS 6 Gap Analysis

**Audit type:** read-only current-state gap analysis
**Audit date:** 2026-09-05 (UTC)
**Rule applied throughout:** the existence of a file, class, endpoint,
workflow or configuration is not evidence that the capability is complete.

---

## 1. Test execution — the one number people misread

```
command:   python3 -W error::ResourceWarning -m unittest discover -s tests -p 'test_*.py' -t .
started:   2026-09-05T16:24:23Z
finished:  2026-09-05T16:32:23Z
wall time: 471.3 s
exit code: 0
result:    Ran 7247 tests — OK (skipped=33)
```

| Field | Value |
|---|---|
| Tests discovered and run | **7,247** |
| Failures | **0** |
| Errors | **0** |
| Skipped | **33** (all classified; `unexplained_skip_count: 0`) |
| Exit code | **0** |

**What this number proves:** the software behaves as its 270 test files
describe.

**What it does not prove — and this is the central misreading risk in the
whole project:** it is not clinical validation, not scientific validation,
not expert review, and not evidence that any pharmacogenomic statement is
correct. WP-19's own artifact carries this sentence:

> *"Everything in this document is software verification. A green suite means
> the software behaved as its tests describe. It is not a validated ruleset,
> a reviewed validation case, an expert opinion, a clinical result, or an
> approval."*

The 33 skips are classified and explained; `unexplained_skip_count` is 0.

**Coverage percentage: `UNKNOWN / NO EXECUTABLE EVIDENCE`** — no coverage
tool is installed, and the repository reports that rather than estimating.

---

## 2. Current capability matrix

Status vocabulary is used strictly. `IMPLEMENTED_NOT_EXECUTED` means the code
is complete and correct as far as tests can tell, and has never been run
against the real thing.

### 2.1 Platform

| Capability | Status | Evidence | Actually executed? | Blocking issue |
|---|---|---|---|---|
| Modular architecture | `IMPLEMENTED_AND_VERIFIED` | 319 `pgx/` modules; AST test proves `pgx/` imports no web framework | Yes — 7,247 tests | — |
| PostgreSQL schema | `IMPLEMENTED_NOT_EXECUTED` | 44 tables via SQLAlchemy metadata | No | No server reachable |
| Migrations | `CONFIGURED_NOT_EXECUTED` | 11 files `0001`–`0011`; `migration_0011_present: true` | No — `migration_0011_executed: false` | No server |
| Transactions | `IMPLEMENTED_NOT_EXECUTED` | `governed_transaction()`, single-transaction assessment persist | No | No server |
| Version registry | `IMPLEMENTED_NOT_EXECUTED` | `software_versions`, `dataset_versions`, `ruleset_versions`, `release_bundles`, `active_release` | No | No server, no content |
| Release bundle | `IMPLEMENTED_NOT_EXECUTED` | `release-manifest.schema.json`; `pgx-release` CLI | No — 0 releases | Nothing to release |
| Rollback | `IMPLEMENTED_NOT_EXECUTED` | `pgx/deployment/rollback.py`, `docs/operations/rollback-runbook.md` | No — `rollback_drill: BLOCKED` | No two released versions |
| **Git provenance** | **`MISSING`** | `.git` exists on branch `main` with **0 commits, 0 tracked files, 0 tags, 0 remotes**, 1,720 untracked | **No** | Nobody has committed |

### 2.2 Scientific data

| Capability | Status | Evidence | Actually executed? | Blocking issue |
|---|---|---|---|---|
| Source registry | `IMPLEMENTED_NOT_EXECUTED` | 20 entries, 4 roles, per-source blocking reasons | Registry built; **0 approved** | `BLOCKED_BY_HUMAN_REVIEW` |
| ClinPGx adapter | `PARTIAL` | `pgx/ingestion/` + legacy probe output | Legacy probe ran historically; **no V2 acquisition run exists** | `BLOCKED_BY_EXTERNAL_SYSTEM` (no network, no licence decision) |
| CPIC integration | `SCAFFOLD_ONLY` | 3 registered sources (`cpic.api`, `cpic.database`, `cpic.publications`), all `PENDING_REVIEW`, `acquisition_mode: NOT_DETERMINED` | No | No adapter, no licence decision |
| DPWG integration | `SCAFFOLD_ONLY` | `dpwg.knmp` registered, `PENDING_REVIEW` | No | Same |
| Drug-label sources | `SCAFFOLD_ONLY` | 6 regulators registered (FDA, EMA, TITCK, PMDA, Swissmedic, HCSC), all `PENDING_REVIEW` | No | Same |
| Provenance | `IMPLEMENTED_AND_VERIFIED` | `evidence-provenance.ndjson`, 4,051 locators, 15-field rule provenance contract | Yes over legacy content | — |
| Immutable snapshots | `IMPLEMENTED_AND_VERIFIED` | 1 snapshot, hash-sealed, 12 artifacts, one-way lifecycle | Yes | Snapshot is `QUARANTINED` |
| Canonical resolver | `IMPLEMENTED_AND_VERIFIED` | 29 `RESOLVED`, 0 `AMBIGUOUS`, 0 `UNRESOLVED`, 0 `BROKEN_REFERENCE` | Yes | — |
| Deduplication | `IMPLEMENTED_AND_VERIFIED` | 1,644 semantic dup groups (3,288 members), 0 exact, 0 conflicting-identity | Yes | — |
| Data quality | `IMPLEMENTED_AND_VERIFIED` | 18 metrics, 6 issues, 4 reconciliations | Yes — and it **failed closed**: `passed: false` | 3 blocking findings |
| `EvidenceRecord` | `IMPLEMENTED_AND_VERIFIED` | 1,794 records, 3,432 text fragments, 1,952 publication refs | Yes | All quarantined; `production_eligible_record_count: 0` |

### 2.3 Scientific governance

| Capability | Status | Evidence | Actually executed? | Blocking issue |
|---|---|---|---|---|
| Curation protocol | `BLOCKED_BY_HUMAN_REVIEW` | `docs/scientific/curation-protocol-v1.md` | Written; status `AWAITING_EXPERT_REVIEW` | No expert signatory |
| Curation workflow | `IMPLEMENTED_NOT_EXECUTED` | 19 modules, 9 tables, revisions/reviews/adjudications | No | No approved protocol |
| Curator roles | `IMPLEMENTED_NOT_EXECUTED` | `curation_role_assignments`, role matrix doc | No — **0 curators assigned, 0 responses, no adjudicator** | `BLOCKED_BY_HUMAN_REVIEW` |
| Rule specification | `IMPLEMENTED_AND_VERIFIED` | `computable-rule.schema.json`: 13 required top-level + 15 required provenance fields | Verified over fixtures | — |
| Rule approval | `BLOCKED_BY_HUMAN_REVIEW` | Approval-envelope machinery | **0 eligible envelopes** | No curated interpretation |
| Frozen ruleset | `BLOCKED_BY_DATA` | A **real build was attempted**: `outcome: REFUSED`, `stopped_at: NO_VALIDATED_RULES` | Attempted and correctly refused | 0 validated rules |
| Active release | `BLOCKED_BY_DATA` | `active_release` table, `pgx-release` CLI | No — 0 active | No frozen ruleset, no published dataset |

### 2.4 PGx engine

| Capability | Status | Evidence | Actually executed? | Blocking issue |
|---|---|---|---|---|
| Phenotype engine | `IMPLEMENTED_AND_VERIFIED` | 6-value closed enum, exact matching, legacy regression harness | Yes — over fixtures and legacy baseline | Never run on governed content |
| RAPID/ULTRARAPID separation | `IMPLEMENTED_AND_VERIFIED` | `SAFETY-INV-004` `COMPLIANT`, `PASS`, 3 negative controls | Yes | — |
| Coverage engine | `IMPLEMENTED_NOT_EXECUTED` | 6 statuses, 8 reason codes, manifest with declared expected scope | Fixtures only — **0 real coverage executions, 0 supported axes** | Expected gene scope requires a human declaration |
| Deterministic risk engine | `IMPLEMENTED_AND_VERIFIED` | `AttentionLevel` 5 values incl. `NOT_ASSESSED`; determinism evidence doc | Yes over fixtures | Never run against a release |
| Source-conflict handling | `IMPLEMENTED_AND_VERIFIED` | `CoverageStatus.SOURCE_CONFLICT`, `VALIDATED_RULES_CONFLICT`; `SAFETY-INV-008` `COMPLIANT`/`PASS` | Yes over fixtures | 0 real conflicts seen (0 rules) |
| Failure/refusal behaviour | `IMPLEMENTED_AND_VERIFIED` | 8 coverage reason codes, `ASSESSMENT_ACTIVE_RELEASE_MISSING`, 45 API error codes, 18 review error codes | Yes — the refusal path is the *only* path currently exercised end to end | — |

### 2.5 Reporting

| Capability | Status | Evidence | Actually executed? | Blocking issue |
|---|---|---|---|---|
| `StructuredReport` | `IMPLEMENTED_NOT_EXECUTED` | `pgx-structured-report/1`, renderer `pgx-report-renderer/1`, template `pgx-report-template/1`, locale `tr` | Synthetic only — `synthetic_only: true` | 0 real assessments |
| Deterministic reporting | `IMPLEMENTED_AND_VERIFIED` | `docs/evidence/wp15-determinism.md`, reproducibility generators | Yes over fixtures | — |
| LLM reporting | `OUT_OF_SCOPE` (P1) | `llm_enabled: false`, `llm_provider_implemented: false` | No | Deliberate — P1-06 |
| LLM safety gateway | `IMPLEMENTED_AND_VERIFIED` (as a refusal) | `REPORT_LLM_DISABLED`; `SAFETY-INV-002` `NOT_PRESENT` with 3 negative controls proving the detector fires before the feature exists | Yes | Enforcement completes only when P1 ships a renderer |

### 2.6 Application

| Capability | Status | Evidence | Actually executed? | Blocking issue |
|---|---|---|---|---|
| API | `IMPLEMENTED_NOT_EXECUTED` | 14 routes, 45 error codes, 43 contract models, 0 stubs, committed OpenAPI | Contract tests yes; **`asgi_runtime_tests_executed: false`, `real_api_assessment_count: 0`**, `data/api/wp16-runtime-verification.json` **absent** | No ASGI runtime run recorded |
| Web UI | `PARTIAL` | 15 routes, 14 templates, 7 browser screenshots captured | Templates render and are claim-scanned; **`validation_dashboard_status: EMPTY_STATE_ONLY`** | No governed content to display |
| Evidence viewer | `IMPLEMENTED_NOT_EXECUTED` | `GET /evidence/{evidence_id}` + API equivalent | No real evidence served | Evidence build is quarantined |
| Validation UI | `SCAFFOLD_ONLY` | `GET /validation` renders an empty state | Renders; shows nothing | 0 metrics, 0 cases |
| Expert review UI | `IMPLEMENTED_NOT_EXECUTED` | 4 web routes + 6 API routes, 8-step workflow | No — 0 reviewers | `BLOCKED_BY_HUMAN_REVIEW` |

**Recorded contradiction:** `data/web/wp17-real-gate-status.json` states
`expert_review_workflow_status: NOT_IMPLEMENTED` while
`data/expert-review/wp22-real-gate-status.json` states
`implementation_status: IMPLEMENTED` with a delivered workflow. One of the two
artifacts is out of date. Recorded, not resolved.

### 2.7 Validation

| Capability | Status | Evidence | Actually executed? | Blocking issue |
|---|---|---|---|---|
| Development cases | `IMPLEMENTED_AND_VERIFIED` | 7 cases (6 migrated + 1 authored), sealed catalogue + manifest | Yes | **May never count as validation evidence** |
| Independent holdout | `MISSING` | `holdout_case_count: 0`, `internal_holdout_case_count: 0`, `expert_holdout_case_count: 0` | No | `BLOCKED_BY_HUMAN_REVIEW` — nobody has authored one |
| Negative controls | `IMPLEMENTED_AND_VERIFIED` | 37 declared, **37 detected** | Yes | — |
| Safety invariants | `PARTIAL` | 12 registered, 12 executed: **7 `PASS`, 5 `BLOCKED`** (2 by P1 scope, 2 by operations, 1 by curators) | Locally yes; **`ci_job_executed: false`** | CI has never run |
| Guideline benchmark | `IMPLEMENTED_NOT_EXECUTED` | Benchmark protocol + plan schema | No — `benchmark_executed: false` | No active release |
| Metrics | `IMPLEMENTED_NOT_EXECUTED` | **15 definitions**, 10 failure paths | No — `computed_metric_value_count: 0`, `threshold_count: 0`, `reference_judgment_count: 0` | No benchmark run |
| Expert blind review | `BLOCKED_BY_HUMAN_REVIEW` | 7 tables, 5 states, 4 Likert dimensions, 18 error codes | No — 0 signatories, 0 named reviewers, `completed_review_count: null` | Five of six preconditions are owned by people |
| Validation report | `IMPLEMENTED_NOT_EXECUTED` | `wp21-validation-report.json` exists with null metric values | Structure yes, content no | No metrics |

### 2.8 Operations

| Capability | Status | Evidence | Actually executed? | Blocking issue |
|---|---|---|---|---|
| Authentication | `IMPLEMENTED_NOT_EXECUTED` | Argon2id, local user lifecycle, server-side sessions | No — `authentication_configured: false`, **`argon2_available: false`** | `argon2-cffi` not installed; no user store |
| RBAC | `IMPLEMENTED_NOT_EXECUTED` | **25 permissions**, explicit registry, digest-pinned | No real principal has exercised one | No database |
| CSRF / session protection | `IMPLEMENTED_NOT_EXECUTED` | Session-bound CSRF | `csrf_operational: false`, `session_store_available: false` | No session store |
| Audit | `IMPLEMENTED_NOT_EXECUTED` | **41 governed actions**, hash-linked chain, 4 tamper shapes detected in tests | No — `governed_audit_event_count: null`, `audit_chain_verified: null` | No audit store |
| Git provenance | `MISSING` | 0 commits, 0 tags | No | Nobody has committed |
| CI | `CONFIGURED_NOT_EXECUTED` | 3 workflows (334 + 230 + 86 lines) | **No — `ci_executed: null`**; `ci_action_pins_resolved: false` | No provider run |
| Docker | `CONFIGURED_NOT_EXECUTED` | Dockerfile + `.dockerignore` + compose topology + 11-file runtime asset allowlist | Image never built — `container_runtime_available: false` | No runtime |
| Staging | `MISSING` | `docs/operations/staging-deployment-runbook.md` | No — `staging_deployed: false` | No host |
| TLS | `MISSING` | Caddyfile with real-cert config | No — `tls_observed: false` | No ingress |
| Backup | `CONFIGURED_NOT_EXECUTED` | Runbook + 4 restore verification conditions | No — `backup_executed: false` | No database |
| Restore | `MISSING` | Same | No — `restore_executed: false`, `restore_verified: false` | No backup |
| Rollback drill | `CONFIGURED_NOT_EXECUTED` | Drill catalogue | No | No two images |
| Performance test | `IMPLEMENTED_NOT_EXECUTED` | `.deploy-out/wp24-performance-result.json` — **a real run was attempted**: `attempted: 0`, `state: BLOCKED`, every latency field `null`, `attempts_required: 1000` | Attempted and correctly refused | No active validated release |
| Final representative demo | `BLOCKED_BY_DATA` | 10-step manifest + preflight | **Preflight ran; stopped at DEMO-02** | 0 approved sources |

### 2.9 Evidence pack (WP-25)

| Capability | Status | Evidence | Actually executed? | Blocking issue |
|---|---|---|---|---|
| Evidence inventory | `IMPLEMENTED_AND_VERIFIED` | 145 artifacts hashed and schema-checked; **17 admissible** | Yes | — |
| Claim registry | `IMPLEMENTED_AND_VERIFIED` | 24 claims, 23 probes, all resolving | Yes — **0 supported, 22 contradicted, 2 unsupported** | — |
| Gate matrix A–F | `IMPLEMENTED_AND_VERIFIED` | 45 conditions read from named artifact fields | Yes — **6 of 6 BLOCKED** | — |
| Pack integrity | `IMPLEMENTED_AND_VERIFIED` | Two-level hashing, no self-hash, 0 path leaks, 0 secret findings | Yes — **PASS** | — |
| THS 6 achievement | `BLOCKED_BY_HUMAN_REVIEW` + `BLOCKED_BY_DATA` + `BLOCKED_BY_EXTERNAL_SYSTEM` | `ths6_achieved: false`, 4 unmet conditions | No | Everything below |

---

## 3. Gate status — all six, with the deciding field

| Gate | Result | Conditions met | Blockers | The single most decisive field |
|---|---|---|---|---|
| **A** Scientific Data | `BLOCKED` | 0 / 5 | 5 | `upstream_state.source_registry_approved = 0` |
| **B** Rules | `BLOCKED` | 0 / 7 | 7 | `upstream_state.curation_protocol_approved = false` |
| **C** Core Safety | `BLOCKED` | 0 / 9 | 9 | `assessment_state.real_completed_assessments = 0` |
| **D** Validation | `BLOCKED` | 0 / 9 | 9 | `real_patient_case_count = 0` against `p0_target_case_count = 50` |
| **E** Operational | `BLOCKED` | 0 / 10 | 10 | `database_available = false` |
| **F** THS 6 | `BLOCKED` | 0 / 5 | 5 | `release_may_proceed = false`; 2 of 19 required release gates satisfied |

Release-validation detail: of 21 gates, 19 are required and **2 are
satisfied** — `image_contents` (every sealed runtime artifact present with a
matching checksum) and `secret_scan` (CLEAN, 0 findings). The 17 unmet
required gates are: lockfile, distributions, image_build, migration,
staging_smoke, tls_termination, safety_gate, holdout_regression,
expert_review, claim_boundary, security_gate, vulnerability_scan, sbom,
backup_restore, rollback_drill, performance, image_contents-adjacent checks.

---

## 4. Why this repository cannot be defended as THS 6 today

Four categories, then the gaps.

### 4.1 Category A — Software / engineering gaps

Closable by implementation or execution alone. **There are very few, and none
of them is on the critical path.**

---

**ID: GAP-A-01 — No ASGI runtime verification has been recorded**
- **Current state:** `asgi_runtime_tests_executed: false`;
  `data/api/wp16-runtime-verification.json` is absent; the served OpenAPI
  document therefore reports itself unverified.
- **Required state:** one recorded run comparing the served document with the
  committed one.
- **Why required:** P0-DOD-001 ("one integrated web prototype runs the
  representative workflow") cannot be evidenced by contract tests alone.
- **Existing infrastructure:** `python -m apps.api.runtime_verification`
  exists and is named in the artifact's own note.
- **Missing artifact:** `data/api/wp16-runtime-verification.json`.
- **Can an AI agent complete it alone?** **YES** (needs the `api` extra
  installed).
- **Human role required:** none.
- **External dependency:** a package index to install FastAPI/uvicorn.
- **Prerequisites:** none.

---

**ID: GAP-A-02 — No dependency lockfile exists**
- **Current state:** `lockfile_present: false`; `uv.lock` absent;
  `package_index_reachable: false`.
- **Required state:** a `uv.lock` produced by a real resolve, verified frozen
  against `pyproject.toml`.
- **Why required:** required release gate `lockfile`; without it no
  reproducible build and no SBOM.
- **Existing infrastructure:** `pyproject.toml` with pinned ranges; build
  provenance module ready to consume a lockfile.
- **Missing artifact:** `uv.lock`.
- **Can an AI agent complete it alone?** **PARTIAL** — trivially yes with
  network; impossible without.
- **Human role required:** none.
- **External dependency:** **PyPI reachability.** This is the blocker.
- **Prerequisites:** none.

---

**ID: GAP-A-03 — CI action pins are unresolved**
- **Current state:** `ci_action_pins_resolved: false`; workflows reference
  actions by a documented all-zero sentinel rather than commit digests.
- **Required state:** every `uses:` pinned to a 40-character commit SHA.
- **Why required:** a floating tag is a supply-chain hole in a pipeline that
  will eventually build a clinical artifact.
- **Existing infrastructure:** `scripts/resolve_action_pins.sh`.
- **Missing artifact:** resolved pins in the two workflow files.
- **Can an AI agent complete it alone?** **PARTIAL** — needs GitHub API
  access.
- **Human role required:** none.
- **External dependency:** network to `api.github.com`.
- **Prerequisites:** none.

---

**ID: GAP-A-04 — WP-17's gate status fails its own published schema**
- **Current state:** `screenshot_evidence_status: "CAPTURED"`; its schema
  (built by `apps/web/artifacts.py`) permits only `NONE` and
  `BROWSER_CAPTURED`. Producer, tests and schema disagree.
- **Required state:** the three agree.
- **Why required:** an artifact that fails its own contract cannot be cited
  as evidence; the WP-25 inventory types it `INVALID` and
  `pgx-ths6 inventory` exits 1 because of it.
- **Existing infrastructure:** all three files.
- **Missing artifact:** none — a one-token decision plus test update.
- **Status: CLOSED in WP-C00 (Execution Wave 1, section A.6).** The state above
  is what the audit measured and is left as written. The producer now emits
  `BROWSER_CAPTURED`; producer, published schema and tests read one constant,
  `apps.web.gate_status.SCREENSHOT_EVIDENCE_STATUSES`; and the committed
  artifact is validated against the committed schema on every test run.
  `pgx-ths6 inventory` exits 0.
- **Can an AI agent complete it alone?** **YES.**
- **Human role required:** none (a maintainer decides which side moves).
- **External dependency:** none.
- **Prerequisites:** none.

---

**ID: GAP-A-05 — WP-19's recorded verification run is stale**
- **Current state:** `run_evidence_status: STALE_EVIDENCE_REJECTED`;
  `discovered_test_count: 6374` against 6,996 test functions now defined.
- **Required state:** a fresh recorded run.
- **Why required:** Gate F condition F5.
- **Existing infrastructure:** `pgx-verify run`.
- **Missing artifact:** a current `wp19-verification-run.json`.
- **Can an AI agent complete it alone?** **YES.**
- **Human role required:** none.
- **External dependency:** none.
- **Prerequisites:** none.

---

**ID: GAP-A-06 — No commit exists**
- **Current state:** `.git` on branch `main` with **0 commits, 0 tracked
  files, 0 tags, 0 remotes**, 1,720 untracked files.
- **Required state:** the tree committed; releases tagged.
- **Why required:** without a commit there is no version identity for
  `software_versions`, no provenance for a build, and no way to say which
  code produced any artifact. Every release manifest would name a software
  version nobody can retrieve.
- **Existing infrastructure:** `.gitignore` deliberately does not exclude
  legacy evidence.
- **Missing artifact:** a commit.
- **Can an AI agent complete it alone?** **PARTIAL** — an agent can stage and
  commit; whether that is desirable is a maintainer's call, and this audit
  did not do it.
- **Human role required:** repository owner decides the commit boundary.
- **External dependency:** none.
- **Prerequisites:** none. **This is the cheapest unblocked item in the
  entire programme.**
- **One thing to fix before committing:** `.gitignore` covers `tmp/`,
  `build/`, `.deploy-out/`, `deploy/secrets/*` and `deploy/tls/*`, but **not
  `output/`**. The authoritative repository currently holds
  `output/pdf/PGx_Platform_V2_WP00-WP25_Degerlendirme.pdf`, which a first
  `git add .` would sweep into history. Either ignore `output/` or move the
  file before the first commit — a generated PDF in the initial commit is
  the kind of thing nobody removes afterwards.

### 4.2 Category B — Scientific content gaps

Require real scientific sources, evidence, curation or rule content.

---

**ID: GAP-B-01 — Zero approved scientific sources**
- **Current state:** 20 registered, all `PENDING_REVIEW`, 0 review records,
  0 interpretations, 0 licence identifiers, 17 of 20 with
  `acquisition_mode: NOT_DETERMINED`, all 17 evidence entries `NOT_OBTAINED`.
- **Required state:** at least the minimum set (see
  `THS6_DATA_REQUIREMENTS.md` §4) approved with a licence decision, an
  acquisition mode and a named reviewer.
- **Why required:** Gate A1; and rule provenance requires
  `source_policy_content_hash`, which does not exist without an approved
  policy.
- **Existing infrastructure:** registry, review checklist, licensing matrix,
  conflict policy, provenance policy — all written.
- **Missing artifact:** a `review` block and an `interpretation` block per
  source.
- **Can an AI agent complete it alone?** **PARTIAL** — an agent can retrieve
  each source's published terms and draft an interpretation. It **cannot**
  make the approval.
- **Human role required:** a named scientific source approver must read the
  terms and record a decision.
- **External dependency:** each publisher's licence terms.
- **Prerequisites:** none. **This is the head of the critical path.**

---

**ID: GAP-B-02 — The only snapshot is permanently quarantined**
- **Current state:** `PGX-DATA-20260830-900`, `QUARANTINED`,
  `LEGACY_IMPORT`, `complete: false`, no acquisition run.
- **Required state:** a `SEALED` snapshot from a real acquisition run.
- **Why required:** Gate A3/A4. `SnapshotState` has **no transition out of
  quarantine** — this cannot be fixed in place.
- **Existing infrastructure:** the whole ingestion package, the request-log
  format, `pgx-ingest-clinpgx`.
- **Missing artifact:** a new dataset identifier and a new snapshot.
- **Can an AI agent complete it alone?** **PARTIAL** — an agent can run the
  acquisition once the source is approved and the network is open.
- **Human role required:** approval of the source and the acquisition mode.
- **External dependency:** live source endpoints.
- **Prerequisites:** GAP-B-01.

---

**ID: GAP-B-03 — Zero curated interpretations**
- **Current state:** 0 interpretations; 1,559 legacy proposals of which
  1,556 are `NOT_REVIEWED`; inter-curator exercise `AWAITING_HUMAN_CURATORS`
  with 0 curators assigned.
- **Required state:** interpretations curated under an approved protocol by
  two named curators with adjudication of disagreements.
- **Why required:** Gate B2; rule provenance requires `interpretation_id`,
  `curation_revision_hash` and `approval_envelope_hash`.
- **Existing infrastructure:** 19 modules, 9 tables, field dictionary, role
  matrix, review checklist, adjudication model.
- **Missing artifact:** curated interpretation records.
- **Can an AI agent complete it alone?** **NO.** An agent may prepare
  *proposed* curation; a proposal is not a curation.
- **Human role required:** curation lead + two named curators + adjudicator.
- **External dependency:** approved evidence build.
- **Prerequisites:** GAP-B-01, GAP-B-02, GAP-C-01 (protocol approval).

---

**ID: GAP-B-04 — Zero validated rules and zero frozen rulesets**
- **Current state:** 0 draft / 0 curated / 0 validated / 0 deprecated rules;
  0 frozen rulesets; 0 executable rulesets. A real build ran and returned
  `REFUSED / NO_VALIDATED_RULES`.
- **Required state:** at least one validated rule per gene-drug-phenotype
  axis in scope, frozen into a registered ruleset.
- **Why required:** Gates B4–B6; everything downstream.
- **Existing infrastructure:** condition language, lifecycle, build, freeze,
  registry, 15-field provenance contract.
- **Missing artifact:** `computable_rules` rows.
- **Can an AI agent complete it alone?** **NO.**
- **Human role required:** curator authoring, reviewer approval.
- **External dependency:** none beyond the above.
- **Prerequisites:** GAP-B-03.

---

**ID: GAP-B-05 — Expected gene scope per drug has never been declared**
- **Current state:** `real_expected_gene_declarations: 0`,
  `real_coverage_manifests: 0`.
- **Required state:** for each in-scope drug, a declaration of which genes a
  complete assessment must consider.
- **Why required:** Gate C2/C3, and P0-DOD-004. The coverage module states
  explicitly that expected scope **cannot** be derived from the chemical
  catalogue, from evidence, from guideline presence, from an existing rule,
  or from a legacy row — *"a scope derived that way would make every drug
  look exactly as covered as its rules make it and no gap would ever be
  visible."*
- **Existing infrastructure:** manifest schema, verifier that checks a
  declared axis against a validated rule.
- **Missing artifact:** the declaration itself.
- **Can an AI agent complete it alone?** **NO.** This is the clearest
  AI-cannot in the repository.
- **Human role required:** a named scientific declaration per drug.
- **External dependency:** guideline coverage statements.
- **Prerequisites:** GAP-B-01.

---

**ID: GAP-B-06 — 33 legacy rule candidates remain unlinked**
- **Current state:** 1,559 candidates, 1,526 linked, **33 unlinked**.
- **Required state:** every candidate linked to a governed work item or
  recorded as not a rule candidate.
- **Why required:** Gate B7.
- **Existing infrastructure:** the inventory and the work-item model.
- **Missing artifact:** 33 decisions.
- **Can an AI agent complete it alone?** **PARTIAL** — an agent can classify
  and propose; a curator records.
- **Human role required:** curation lead.
- **External dependency:** none.
- **Prerequisites:** none. **This is the smallest open scientific item.**

### 4.3 Category C — Human evidence gaps

Require real expert evaluation, approval or review.

---

**ID: GAP-C-01 — The curation protocol is unapproved**
- **Current state:** `AWAITING_EXPERT_REVIEW`; 0 signatories.
- **Required state:** approved by a named expert before any curation begins.
- **Why required:** Gate B1; rule provenance requires
  `protocol_content_hash`.
- **Existing infrastructure:** the protocol document, the approval-gate model.
- **Missing artifact:** a signatory record.
- **Can an AI agent complete it alone?** **NO.**
- **Human role required:** a named domain expert.
- **External dependency:** none.
- **Prerequisites:** none. **Highest leverage single human action in the
  project** — it unblocks the entire curation subsystem.

---

**ID: GAP-C-02 — The claim boundary is a draft**
- **Current state:** `DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW` in five
  separate gate artifacts. 6 prohibited claim surfaces declared; the scanner
  has 4 known gaps.
- **Required state:** approved by a named clinical safety authority.
- **Why required:** Gate C7; required release gate `claim_boundary`; and
  until it is approved **no outward statement about the system's output is
  authorised at all**.
- **Existing infrastructure:** intended-purpose doc, safety contract, claim
  scanner (`claim-scanner/0.1.0`), `SAFETY-INV-010` `COMPLIANT`/`PASS`.
- **Missing artifact:** an approval record; and closure of the 4 scanner
  gaps.
- **Can an AI agent complete it alone?** **NO.**
- **Human role required:** clinical safety authority.
- **External dependency:** none.
- **Prerequisites:** none — **this can start today, in parallel with
  everything.**

---

**ID: GAP-C-03 — No validation cases and no holdout set**
- **Current state:** `real_patient_case_count: 0` against a P0 target of 50
  (`p0_target_shortfall: 50`); 0 internal holdout; 0 expert holdout; 7
  development cases that are contractually excluded from validation evidence.
- **Required state:** ≥50 serious validation cases (100+ preferred) plus an
  independent holdout set never used in rule development.
- **Why required:** Gates D1/D2; P0-DOD-006/007; required release gate
  `holdout_regression`.
- **Existing infrastructure:** case schema (closed roles, closed
  classifications), separation audit, access ledger, `SAFETY-INV-009`
  enforcing non-overlap.
- **Missing artifact:** the cases.
- **Can an AI agent complete it alone?** **PARTIAL** — an agent can generate
  *candidate* cases from published literature (the schema has a
  `PUBLISHED_LITERATURE_DERIVED` classification for exactly this). It cannot
  decide that a case is *serious*, representative, or correctly answered.
- **Human role required:** validation owner authors/approves; the holdout set
  must be built by someone who is not developing the rules.
- **External dependency:** published literature.
- **Prerequisites:** GAP-B-05 (you cannot write a case for an axis nobody has
  declared in scope). **Note the structural constraint:**
  `real_patient_case_count` is *structurally* zero — the case model refuses
  real-patient, genotype and raw-sequencing fields at any depth, so more
  cases in the current model cannot come from patients. P0 validation must be
  synthetic or literature-derived by design.

---

**ID: GAP-C-04 — No expert review has been performed**
- **Current state:** protocol unapproved, 0 signatories, 0 named reviewers,
  `assigned_review_count: null`, `completed_review_count: null`.
- **Required state:** blind-first review completed under an approved protocol
  by a named expert using the interactive workflow.
- **Why required:** Gates D6–D9; P0-DOD-009/010; required release gate
  `expert_review`.
- **Existing infrastructure:** 7 tables, 5 states, 4 Likert dimensions,
  reveal protocol, correction ledger, payload permits, audit chain.
- **Missing artifact:** reviews.
- **Can an AI agent complete it alone?** **NO — and this is the one where
  the boundary must be loudest.** An AI producing "expert review" output
  would be fabricating the single piece of evidence THS 6 exists to require.
- **Human role required:** expert review chair + named reviewers.
- **External dependency:** none.
- **Prerequisites:** GAP-C-01, GAP-B-04, GAP-C-03, an active release,
  restricted storage, production authentication.

---

**ID: GAP-C-05 — No dataset quality decision, and no way to record one**
- **Current state:** DQ report `passed: false`; the module's own note says
  *"this package provides no way to record one."*
- **Required state:** a named human records a quality decision that
  transitions the dataset out of `BUILDING`.
- **Why required:** Gate A2.
- **Existing infrastructure:** the DQ report and the lifecycle enum.
- **Missing artifact:** **the recording mechanism itself does not exist** —
  this is simultaneously a software gap and a human gap.
- **Can an AI agent complete it alone?** **PARTIAL** — an agent can build the
  mechanism; only a human can use it.
- **Human role required:** data owner.
- **External dependency:** none.
- **Prerequisites:** GAP-B-02.

---

**ID: GAP-C-06 — Zero of nine sign-off roles have signed**
- **Current state:** 9 roles, `signed_count: 0`, `signature_mechanism: null`.
- **Required state:** all nine signed.
- **Why required:** one of the four conditions of `ths6_achieved`.
- **Existing infrastructure:** the matrix, with each role's attestation
  written in the first person and the specific artifacts each must review.
- **Missing artifact:** signatures — and deliberately no code path to
  produce one.
- **Can an AI agent complete it alone?** **NO. Never.**
- **Human role required:** all nine.
- **External dependency:** none.
- **Prerequisites:** everything else.

### 4.4 Category D — Operational evidence gaps

Require actual execution in a target or representative environment.

---

**ID: GAP-D-01 — No database has ever been reached**
- **Current state:** `database_available: false`, `session_store_available:
  false`, `audit_store_available: false`, `migration_0011_executed: false`,
  `postgresql_available: false`.
- **Required state:** a PostgreSQL server with all 11 migrations applied.
- **Why required:** Gates E2/E3; blocks 7 of 7 readiness components
  indirectly; blocks the persistence half of `SAFETY-INV-007` and `-012`.
- **Existing infrastructure:** 44 tables, 11 migrations, compose topology,
  `pgx-db-check`, `pgx-db-seed`.
- **Missing artifact:** an executed `alembic upgrade head`.
- **Can an AI agent complete it alone?** **PARTIAL** — yes given a container
  runtime or a reachable server.
- **Human role required:** none.
- **External dependency:** a PostgreSQL server.
- **Prerequisites:** none. **Second-cheapest unblocked item.**

---

**ID: GAP-D-02 — The audit chain has never been verified**
- **Current state:** `audit_chain_verified: null`,
  `governed_audit_event_count: null` — both null, not zero.
- **Required state:** real governed events written and the hash chain
  verified.
- **Why required:** Gate E4; P0-DOD-012.
- **Existing infrastructure:** 41 governed actions, chain structure, 4 tamper
  shapes proven detectable in tests.
- **Missing artifact:** events.
- **Can an AI agent complete it alone?** **PARTIAL.**
- **Human role required:** none.
- **External dependency:** database.
- **Prerequisites:** GAP-D-01.

---

**ID: GAP-D-03 — No backup has been taken and no restore verified**
- **Current state:** `backup_executed: false`, `restore_executed: false`,
  `restore_verified: false`.
- **Required state:** a restore satisfying **all four** runbook conditions —
  `pg_restore` exiting zero satisfies none of them.
- **Why required:** Gate E5; required release gate `backup_restore`.
- **Existing infrastructure:** runbook, execution addendum, 4 declared
  conditions.
- **Can an AI agent complete it alone?** **PARTIAL.**
- **Human role required:** none.
- **External dependency:** database + storage.
- **Prerequisites:** GAP-D-01.

---

**ID: GAP-D-04 — No image, no staging, no TLS**
- **Current state:** `container_runtime_available: false`,
  `staging_deployed: false`, `tls_observed: false`.
- **Required state:** a built image, a deployed staging environment with real
  ingress and a real certificate, health endpoints observed answering.
- **Why required:** Gates E7/E9; P0-DOD-013; required release gates
  `image_build`, `staging_smoke`, `tls_termination`.
- **Existing infrastructure:** Dockerfile, `.dockerignore`, compose topology,
  Caddyfile, an 11-file runtime asset allowlist **already verified present
  and checksummed**.
- **Can an AI agent complete it alone?** **PARTIAL** — build and local
  rehearsal yes; a real staging host and a real certificate are procurement.
- **Human role required:** platform owner provisions the host and DNS.
- **External dependency:** container runtime, host, certificate authority.
- **Prerequisites:** GAP-A-02 (lockfile).
- **Discipline note:** a local rehearsal must carry
  `LOCAL_STAGING_REHEARSAL` and may never be reported as staging — the schema
  enforces this.

---

**ID: GAP-D-05 — CI has never run**
- **Current state:** `ci_executed: null`, `ci_job_executed: false`.
  Three workflows totalling 650 lines exist.
- **Required state:** a provider executes them at least once.
- **Why required:** Gate C6/E8; P0-DOD-008 ("all safety invariants pass in
  CI"); required release gate `safety_gate`.
- **Existing infrastructure:** the workflows.
- **Can an AI agent complete it alone?** **NO** — pushing to a provider is
  outside the agent's authority here, and there is no remote configured
  (0 remotes).
- **Human role required:** repository owner configures a remote and pushes.
- **External dependency:** GitHub (or equivalent).
- **Prerequisites:** GAP-A-06 (a commit must exist), GAP-A-03 (pins).

---

**ID: GAP-D-06 — No performance measurement exists**
- **Current state:** a real run was attempted and refused:
  `attempted: 0`, `state: BLOCKED`, `latency_p50_ms/p95/p99: null`,
  `throughput_rps: null`, `attempts_required: 1000`,
  `environment_kind: LOCAL_REHEARSAL`.
- **Required state:** 1,000 assessments against one eligible release.
- **Why required:** required release gate `performance`.
- **Existing infrastructure:** the harness, declared targets published
  *before* measurement.
- **Can an AI agent complete it alone?** **PARTIAL.**
- **Human role required:** none.
- **External dependency:** none beyond a release.
- **Prerequisites:** an active release — i.e. all of Gates A–C.
- **Timing note for the eventual budget:** targets are declared in
  `pgx.deployment.performance.PERFORMANCE_TARGETS` and the harness records
  p50/p95/p99 plus wall time. When a release finally exists, the first
  measurement to watch is the **per-assessment latency budget**: release
  pinning is a single pointer read, but coverage evaluation is per
  gene-drug axis, so cost scales with declared expected scope rather than
  with the number of rules.

---

**ID: GAP-D-07 — No SBOM and no vulnerability scan**
- **Current state:** `sbom` and `vulnerability_scan` both unmet required
  gates; no scanner available; no advisory database identified.
- **Required state:** an SBOM from real installed contents and a scan naming
  its scanner version and advisory database.
- **Why required:** required release gates.
- **Can an AI agent complete it alone?** **PARTIAL.**
- **Human role required:** none.
- **External dependency:** scanner tooling + advisory feed.
- **Prerequisites:** GAP-A-02, GAP-D-04.

---

## 5. Human / external gates

### AI CAN

- Retrieve public scientific records (CPIC, DPWG, drug labels, PubMed) once
  network and licence permit.
- Draft a **proposed** curation for each interpretation, clearly labelled as
  a proposal.
- Structure evidence, allocate identifiers, compute hashes, build manifests.
- Generate **candidate** validation cases from published literature —
  the schema's `PUBLISHED_LITERATURE_DERIVED` classification exists for this.
- Execute the test suite, the reproducibility check, the safety invariants
  and the secret scan.
- Compute metrics **once reference judgments and thresholds exist**.
- Prepare the review UI, the forms, the blinding structure and the audit
  chain.
- Build and verify the evidence pack.
- Build images, run migrations, take backups, run drills — given the
  infrastructure.

### AI CANNOT CLAIM

- **Expert clinical judgment.** Not a proposal that reads like one, not a
  summary of guidelines, not a consensus of sources.
- **Independent expert approval.** The word *independent* is the whole point.
- **Informed consent** of any kind.
- **Ethical approval.**
- **Real clinical use.**
- **Human curator identity.** Two named curators means two people.
- **Physician validation.**

### Does the codebase blur these boundaries anywhere?

**Audited answer: no — and it is unusually explicit about it.** Five
independent mechanisms were found:

1. **`data/curation/protocol-v1/exercises/status.json`** —
   *"Nothing in this repository can move it out of `AWAITING_HUMAN_CURATORS`,
   because doing so would assert that two scientists reviewed evidence they
   have not seen."*
2. **`data/rulesets/wp11-real-build-attempt.json`** —
   *"No rule, ruleset or approval was created to make this attempt succeed.
   Manufacturing one would be the exact failure the curation and approval
   workflow exists to prevent."*
3. **The legacy hint inventory** — legacy values appear under `raw_*` field
   names *"precisely so that reading them is obviously reading the old
   project's unreviewed opinion, not this project's finding."*
4. **`wp22-real-gate-status.json`** — `expert_review_performed: false` with
   the note *"False, and not a placeholder. Six preconditions are missing and
   five of them are owned by people."*
5. **The sign-off matrix** — `signature_mechanism: null`, with no code path
   that could set it.

One residual risk worth naming, since this is an audit and not a
celebration: **the 1,559 legacy proposals are a standing temptation.** They
contain `demo_risk_level`, `manual_risk_level`, `manual_phenotypes` and
`plain_language_mvp` fields from the prototype. The governance holds today
because nothing may cross; the failure mode to guard against in the next
phase is somebody "seeding" curation from them to hit a case count.

---

## 6. The minimum blocker set

Strip everything that is downstream of something else, and **five things**
prevent THS 6:

| # | Blocker | Category | Owner | Can AI do it? |
|---|---|---|---|---|
| 1 | No approved scientific source | B | scientific source approver | NO |
| 2 | Curation protocol unapproved | C | domain expert | NO |
| 3 | Claim boundary is a draft | C | clinical safety authority | NO |
| 4 | No validation cases, no holdout set | C | validation owner | PARTIAL (candidates only) |
| 5 | No database / no container runtime / no CI provider | D | platform owner | PARTIAL (needs infrastructure) |

Everything else in this document is downstream of one of those five.
Blockers 1–4 are human decisions that no amount of engineering closes.
Blocker 5 is procurement.

**Two items are unblocked today and cost almost nothing:** making the first
Git commit (GAP-A-06) and clearing the 33 unlinked legacy candidates
(GAP-B-06). Neither moves a gate on its own, but both are pure debt.
