# WP-13 handoff

| Field | Value |
|---|---|
| Document ID | `DOC-HANDOFF-013` |
| Work package | WP-13 — Coverage Engine |
| Status | **Offline scope complete. No attention level was calculated, no assessment was executed, and no real coverage claim exists.** |
| Output for WP-14 | a coverage result that says what could be evaluated and why the rest could not, with a stable reason code at every level |

> Read this before WP-14. One item must not be presented as met.
> **A38**, "coverage semantics match the approved curation/rule protocol", is
> **BLOCKED** — the protocol is `AWAITING_EXPERT_REVIEW` and no scientist has
> read it. The semantics implemented here match `architecture.md` 9.2 and the
> safety contract; whether those are the right semantics is a question for a
> reviewer, not for this work package.
> WP-12's **A33**, WP-11's **A30** and **A26**, WP-10's **A24**–**A26** and
> WP-09's **A21**–**A23** remain blocked and were not touched.

---

## 1. What exists now

| Artefact | What it is |
|---|---|
| `pgx/engine/coverage_manifest.py` | `pgx-ruleset-coverage-manifest/1`; declared scope, verified never derived |
| `pgx/engine/coverage_models.py` | axis, medication and overall results; no field an attention level fits in |
| `pgx/engine/coverage.py` | `pgx-coverage-engine/1`; three decision tables, published as data |
| `pgx/engine/coverage_validator.py` | eighteen issue codes; fails closed on an unperformed check |
| `pgx/engine/coverage_legacy.py` | the legacy comparison and its four-entry allowlist |
| `pgx/engine/coverage_errors.py` | four failure types, each with a stable code |
| `pgx/application/coverage_cli.py` | ten read-only commands, nine refused flags |
| `pgx/application/coverage_schema.py` | six published JSON Schemas |
| `pgx/application/coverage_gate_status.py` | eight blockers, each with an owner |
| `schemas/*.schema.json` | the downstream contract, closed at every level |
| `data/coverage/wp13-real-gate-status.json` | why no real coverage claim can exist |
| `data/migration/wp13/` | the regression report and its allowlist |

No database migration. Evaluating coverage transitions no state, so there is
nothing for one to hold — and no coverage *service* either, for the same
reason.

## 2. What WP-14 receives

A `CoverageResult` carrying, for each requested medication and each expected
axis, a `CoverageStatus` and the reason codes for anything short of `FULL`. It
pins the profile, coverage manifest, ruleset, dataset and evidence build it was
computed against, each by identity and hash, so a stored result can be checked
against the artifacts that produced it rather than against whatever is on disk
later.

What WP-14 must not do with it:

- **Do not treat `INSUFFICIENT` as `NO_ACTIVE_ATTENTION`.** They are opposite
  claims. `INSUFFICIENT` says nothing was evaluated; `NO_ACTIVE_ATTENTION` says
  something was evaluated and found unremarkable. Collapsing them reproduces
  `LEGACY-BUG-002` one layer higher, where the reason codes that would have
  explained it are no longer in scope.
- **Do not treat `UNSUPPORTED_DRUG` as an absence of concern.** The dataset
  does not contain the chemical. Nothing was looked at.
- **Do not resolve a `SOURCE_CONFLICT`.** WP-13 preserves every side because
  choosing one is an adjudication, and nothing downstream has more information
  with which to make it than the layer that refused to.
- **Do not infer coverage where none is reported.** An axis outside the declared
  expected scope is not covered, and an axis nobody declared is not covered
  either.
- **Do not read `PARTIAL` as "mostly fine".** It means some of what a complete
  assessment required was evaluable and some was not, and the axes say which.

## 3. Where the real state stands

Unchanged by this work package, and reported rather than asserted:

| Count | Value |
|---|---|
| Real approved coverage manifests | 0 |
| Real declared drugs | 0 |
| Real expected gene declarations | 0 |
| Real supported axes | 0 |
| Real evaluable axes | 0 |
| Real full-coverage axes | 0 |
| Real coverage executions | 0 |

Eight blockers, none clearable by writing code: the curation protocol is
`AWAITING_EXPERT_REVIEW`; the canonical dataset is `BUILDING`; the evidence
build is quarantined and not publication-eligible; there is no frozen ruleset
and the default registry is empty; no drug has an approved expected gene scope;
and no identity holds a scientific role.

`data/coverage/wp13-real-gate-status.json` names each blocker, who owns it, and
what clearing it would unblock.

## 4. The load-bearing thing to preserve

`expected_gene_keys` is declared by named humans and derived from nothing. The
temptation, when a manifest is tedious to write, is to generate it from the
rules that exist — or from WP-11's `structural_axes`, which is exactly the same
mistake with a more official-looking source.

A scope derived that way makes every drug look precisely as covered as its
rules happen to make it, `PARTIAL` becomes unreachable, and the system loses
the only mechanism it has for noticing that something was never considered.
There is no `--infer-scope` flag and no `--from-structural-axes` flag; both are
refused by name. A manifest with that shape is reported as
`COVERAGE_STRUCTURAL_AXES_COPIED` and needs a reviewer to say whether the scope
was chosen or copied.

## 5. Open items

| Item | Owner | Blocks |
|---|---|---|
| A38 — semantics reviewed against an approved protocol | a named scientific expert | the claim that coverage means what a clinician would expect |
| An approved coverage manifest for any ruleset | curator, reviewer, approver, acting separately | every real coverage answer |
| Expected gene scope per drug | scientific curators | a gap ever being visible |
| Role assignment for real identities | WP-23, then whoever assigns roles | any of the three separated acts |
| Dataset publication and evidence de-quarantine | WP-07 and source-policy review | a manifest pinning something stable and citable |

## 6. What was verified, and how

The full suite passes across WP-00–WP-13, with 16 skipped (they require
PostgreSQL, which is unavailable in this environment). WP-13 contributes 382 of
them, and a test asserts that figure against the files that make it up so it
cannot quietly become aspirational:

| Tests | File |
|---|---|
| 63 | `tests/unit/engine/test_coverage_manifest.py` |
| 43 | `tests/unit/engine/test_coverage_axis.py` |
| 43 | `tests/unit/engine/test_coverage_aggregation.py` |
| 36 | `tests/unit/engine/test_coverage_legacy_regression.py` |
| 46 | `tests/unit/engine/test_wp13_boundaries.py` |
| 28 | `tests/unit/engine/test_wp13_documentation.py` |
| 39 | `tests/unit/application/test_coverage_cli.py` |
| 32 | `tests/contract/test_wp13_schemas.py` |
| 31 | `tests/safety/test_coverage_safety.py` |
| 21 | `tests/integration/engine/test_coverage_end_to_end.py` |

Everything WP-13 was verified against is synthetic. The one place real names
appear is the legacy comparison, which reads the real pinned catalogue in order
to report honestly what it does and does not contain.

Nothing here is clinical validation, and no coverage status produced by this
work package asserts safety, preference or suitability for any medicine.
