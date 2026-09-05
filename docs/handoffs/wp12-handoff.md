# WP-12 handoff

| Field | Value |
|---|---|
| Document ID | `DOC-HANDOFF-012` |
| Work package | WP-12 — Exact Phenotype Engine Migration |
| Status | **Offline scope complete. No assessment was executed, no attention or coverage was calculated, and the real rule registry is still empty.** |
| Output for WP-13/WP-14 | a versioned input boundary, an immutable canonical profile with a deterministic hash, and an exact matcher whose failures stay distinguishable |

> Read this before WP-13. One item must not be presented as met.
> **A33**, "exact semantics match the approved curation/rule protocol", is
> **BLOCKED** — the protocol is `AWAITING_EXPERT_REVIEW` and no scientist has
> read it. The semantics implemented here match `architecture.md` 9.1 and
> `SAFETY-INV-004`; whether those are the right semantics is a question for a
> reviewer, not for this work package.
> WP-11's **A30** and **A26**, WP-10's **A24**–**A26** and WP-09's **A21**–**A23**
> remain blocked and were not touched.

---

## 1. What exists now

| Artefact | What it is |
|---|---|
| `pgx/engine/phenotype_normalization.py` | `pgx-phenotype-input/1`; canonical tokens only |
| `pgx/engine/phenotype_models.py` | observation, profile, decision; four and five status vocabularies |
| `pgx/engine/phenotype.py` | `pgx-phenotype-matcher/1`; `EXACT` and `ONE_OF`, nothing else |
| `pgx/engine/phenotype_legacy.py` | the P1–P6 comparison and the difference allowlist |
| `pgx/engine/phenotype_errors.py` | three failure types, each with a stable code |
| `pgx/application/phenotype_cli.py` | seven read-only commands, eight refused flags |
| `pgx/application/phenotype_schema.py` | the four published schema loaders |
| `schemas/phenotype-*.schema.json` | profile, normalisation result, match result, regression report |
| `data/migration/wp12/` | the regression report and the allowlist |

No migration was added. Phenotype matching is a pure operation over values, and
a migration would mean something here had acquired state.

## 2. What WP-13 and WP-14 may rely on

- A phenotype is normalised **once**, at a named contract version, and the
  verdict records which contract produced it.
- Four normalisation outcomes and five match statuses, all closed vocabularies.
- `MISSING`, `INDETERMINATE` and `UNSUPPORTED` are distinguishable at the point
  of use — `NO_MATCH` means a phenotype *was* observed and the rule does not
  cover it.
- `EXACT` and `ONE_OF` are exact. Nothing widens, defaults or falls through.
- A profile's `content_hash` is stable across machines and insertion orders, so
  an assessment can be pinned to the input it was computed from.
- Every decision carries the `condition_hash` of the exact condition evaluated.

## 3. What WP-13 and WP-14 must not assume

- **That a `NO_MATCH` means the axis is covered.** It means this rule's
  phenotype condition was not satisfied. Coverage is WP-13's question.
- **That an input failure is a low-risk result.** `INPUT_MISSING`,
  `INPUT_INDETERMINATE` and `INPUT_UNSUPPORTED` must become an absence of
  coverage and `NOT_ASSESSED`, never `LOW` or `NO_ACTIVE_ATTENTION`
  (`SAFETY-INV-001`).
- **That a `MATCH` is a finding.** It is phenotype equality for one gene. The
  drug half of the axis, the rule's outcome, and whether anything should be
  reported are all WP-14's.
- **That `NORMAL` matching a `NORMAL` rule implies attention.** It implies
  equality. The rule's own outcome carries what it warrants, and may be
  `NO_ACTIVE_ATTENTION`. Legacy suppressed the match instead, which is
  allowlisted difference `LEGACY-NORMAL-PHENOTYPE-SUPPRESSED`.
- **That any of this is scientifically validated.** Nothing here has been
  reviewed by a scientist.

## 4. Verification summary

| Check | Result |
|---|---|
| Pre-edit baseline | 3,151 passed / 0 failed / 16 skipped |
| Full suite after WP-12 | 3,407 passed / 0 failed / 16 skipped |
| WP-12 tests added | 256 (211 unit, 15 integration, 27 contract, 3 dependency-direction) |
| Exact truth matrix | 30 pairs, 5 matches, 0 cross-matches |
| Every `ONE_OF` subset | 31 sets × 5 inputs, exact membership only |
| Regression report | 6 profiles, 0 unexpected differences, 0 unobserved allowlist entries |
| Two independent generations | byte-identical (`md5 368512b9…`) |
| Published schemas | all four validate real output and refuse the forbidden fields |
| Attention levels calculated | **0** |
| Coverage statuses calculated | **0** |
| Assessments executed or persisted | **0** |
| Database migrations added | **0** |
| Executable rulesets in the default registry | **0** |

## 5. The first thing WP-13 should read

`docs/evidence/wp12-phenotype-safety-invariants.md`, and specifically section
2. WP-12 keeps three input failures distinguishable at some cost in
convenience; WP-13's whole job is to turn that distinction into coverage
statuses and reason codes. If it collapses them back into a single "did not
match", the invariant is lost between the two packages rather than inside
either.
