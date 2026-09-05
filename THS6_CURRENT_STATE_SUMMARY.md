# THS 6 — Current State Summary

**Audit date:** 2026-09-05 (UTC) · read-only · nothing was modified
**Full suite:** 7,247 tests, 0 failures, 0 errors, 33 classified skips,
exit 0 (471.3 s)

---

## The one-sentence answer

**The machine is built and has never been fed.** A 110,000-line governed
platform with 7,247 passing tests is refusing, correctly and at every stage,
to produce results from content nobody has approved.

---

## 1. What genuinely works today

Verified by execution, not by inspection:

- **The refusal machinery.** It is the only path currently exercised end to
  end, and it works. A real ruleset build was attempted and returned
  `REFUSED / NO_VALIDATED_RULES`. A real performance run was attempted and
  returned `state: BLOCKED, attempted: 0` with every latency field `null`
  rather than zero. The data-quality gate ran and returned `passed: false`
  with three blocking findings.
- **Canonicalisation and evidence extraction.** 1,822 records → 16 canonical
  entities (11 drugs, 5 genes) with 29 resolutions, 0 ambiguous, 0
  unresolved; 1,644 semantic duplicate groups identified; 1,794 evidence
  records with 4,051 locators, 3,432 text fragments and 1,952 publication
  references.
- **The phenotype engine.** Exact matching on a closed 6-value enum, with
  RAPID and ULTRARAPID kept separate — `SAFETY-INV-004` `COMPLIANT`/`PASS`
  with 3 negative controls.
- **The safety layer.** 12 invariants registered and executed, 37 negative
  controls all detected, 0 unexplained skips, 0 false-reassurance violations
  across a 36-item corpus.
- **The secret scanner.** CLEAN over 1,295 files, 0 findings, 31 classified.
- **Determinism and reproducibility.** 8 generators, all `REPRODUCIBLE`,
  0 unstable.
- **The evidence pack.** 145 artifacts hashed and schema-validated, 24 claims
  with 23 resolving refutation probes, 6 gates rebuilt from named artifact
  fields, integrity **PASS**.

## 2. What exists only as code or configuration

Complete, tested, never run against the real thing:

| Thing | Reality |
|---|---|
| PostgreSQL schema | 44 tables, 11 migrations — **migration 0011 not executed**, no server ever reached |
| API | 14 routes, 45 error codes, 0 stubs — **0 real assessments served**, no ASGI runtime run recorded |
| Web UI | 15 routes, 14 templates — renders, but `validation_dashboard_status: EMPTY_STATE_ONLY` |
| Authentication / RBAC / CSRF / audit | 25 permissions, 41 governed audit actions, hash-linked chain — **`argon2-cffi` not installed, audit chain never verified, `governed_audit_event_count: null`** |
| CI | 3 workflows, 650 lines — **`ci_executed: null`**, action pins unresolved |
| Docker / staging / TLS | Dockerfile, compose, Caddyfile — **image never built, nothing deployed, TLS never observed** |
| Backup / restore / rollback | Runbooks + 4 restore conditions — **never executed** |
| Expert review | 7 tables, 8 steps, 5 states, 4 Likert dimensions — **0 reviewers, 0 reviews** |
| Benchmark + metrics | 15 metric definitions, 10 failure paths — **0 computed values, 0 thresholds** |

## 3. What is completely missing

- **Any commit.** `.git` exists on branch `main` with **0 commits, 0 tracked
  files, 0 tags, 0 remotes** and 1,720 untracked files. There is no software
  version identity for any release to name.
- **Any approved scientific source.** 20 registered, all `PENDING_REVIEW`,
  0 review records, 0 licence identifiers.
- **Any curated interpretation, validated rule, frozen ruleset, executable
  ruleset, or active release.** All zero.
- **Any validation case or holdout case.** 0 against a P0 target of 50.
- **Any declaration of expected gene scope per drug** — and this one has no
  external source; it is a human judgement with no upstream input.
- **A mechanism to record a dataset quality decision.** The DQ module states
  it *"provides no way to record one"* — a rare case where a human gap and a
  software gap are the same gap.

## 4. What is blocked by human review

Nine roles; **zero have acted**. The three that block the most, and are
available today with no prerequisites:

1. **Scientific source approver** — 0 of 20 sources approved. Blocks the
   entire scientific chain.
2. **Domain expert** — the curation protocol is `AWAITING_EXPERT_REVIEW`.
   Blocks curation, and every rule's `protocol_content_hash`.
3. **Clinical safety authority** — the claim boundary is `DRAFT`. Until it is
   approved, **no outward statement about the system's output is authorised
   at all.**

Then: curation lead (0 curators assigned), validation owner (0 cases),
expert review chair (0 reviewers), data owner (no quality decision),
security owner, platform owner, release approver.

## 5. What can be collected from public / internet sources

An AI agent can do all of this, given network access:

- Published terms, licences and reuse conditions for all 20 registered
  sources — the input a human needs to make an approval decision.
- CPIC, DPWG/KNMP, CPNDS, RNPGx and AusNZ guideline content; FDA, EMA, TITCK,
  PMDA, Swissmedic and Health Canada label statements; ClinPGx annotations;
  PubMed citations.
- **Guideline version identifiers** — currently `null` for all 20 sources and
  required by rule provenance as `source_policy_version`. The most commonly
  forgotten field in the whole chain.
- Draft (clearly labelled) proposed curations for each interpretation.
- **Candidate** validation cases derived from published literature — the case
  schema has a `PUBLISHED_LITERATURE_DERIVED` classification for exactly this.

## 6. What only a real expert can do

- Approve a source for scientific use.
- Approve the curation protocol.
- Curate an interpretation — two *named people*, with adjudication of
  disagreement.
- Declare which genes a complete assessment of a given drug must consider.
- Approve the claim boundary.
- Decide that a validation case is serious, representative and correctly
  answered.
- Perform a blind-first expert review.
- Sign any of the nine attestations.

**An AI producing anything that reads as expert review would be fabricating
the single piece of evidence THS 6 exists to require.** The repository is
unusually careful about this — the inter-curator exercise file states that
nothing in the repository can move it out of `AWAITING_HUMAN_CURATORS`
*"because doing so would assert that two scientists reviewed evidence they
have not seen"* — and that discipline must survive the next phase.

## 7. What is required for the first validated release

Recommended minimum scope (full justification in `THS6_DATA_REQUIREMENTS.md`
§4). The goal is the smallest scope that exercises every governed mechanism
once, not maximum coverage:

| Element | Minimum |
|---|---|
| Genes | **2** — CYP2C19, CYP2D6 |
| Drugs | **4** — clopidogrel, codeine, omeprazole, amitriptyline |
| Gene–drug pairs | **5** (amitriptyline spans both genes — that is what makes `PARTIAL` coverage visible) |
| Phenotypes | **5** — POOR, INTERMEDIATE, NORMAL, RAPID, ULTRARAPID |
| Validated rules | **~20–25** |
| Validation cases | **50** beyond the existing 7 development cases |
| Holdout | **≥20 internal + ≥10 expert** |
| Sources | **3 minimum** (CPIC + DPWG + ClinPGx); **5 to be defensible** (add FDA + TITCK, so at least one axis has two independent primary sources) |

Excluded on purpose: CYP2C9/warfarin (invites dose expectations the
`AttentionLevel` model deliberately cannot represent), tamoxifen (a genuinely
contested evidence base — an excellent second-release `SOURCE_CONFLICT` case
and a poor first-release one), and all candidate/alternative features (P1).

## 8. The minimum blocker set preventing THS 6 today

Strip everything downstream, and **five things** remain:

| # | Blocker | Kind | Can an AI close it? |
|---|---|---|---|
| 1 | No approved scientific source | Scientific + human | **NO** |
| 2 | Curation protocol unapproved | Human | **NO** |
| 3 | Claim boundary is a draft | Human | **NO** |
| 4 | No validation cases, no holdout set | Human | PARTIAL — candidates only |
| 5 | No database / container runtime / CI provider | Operational | PARTIAL — needs infrastructure |

Blockers 1–4 are decisions by named people. No amount of engineering closes
them. Blocker 5 is procurement.

**Two items are unblocked today and cost almost nothing:** making the first
Git commit, and clearing the 33 unlinked legacy rule candidates. Neither
moves a gate alone, but the commit is currently sitting on the critical path
for no reason — a release cannot name a software version that does not exist.

---

## 9. The honest assessment

Three things a reader should take away.

**The engineering is not the problem.** 7,247 tests pass; the architecture
refuses to compute from unapproved content structurally rather than by
policy; missing data has its own value (`NOT_ASSESSED`) so it can never read
as low risk; `null` and `0` are kept apart across every artifact. The single
best decision in the repository is that expected gene scope cannot be derived
from the rules that happen to exist — because deriving it would make every
drug look exactly as covered as its rules make it, and no gap would ever be
visible.

**The scientific content is entirely absent, and its inheritance is
awkward.** Every scientific byte in the repository descends from a
quarantined legacy prototype: one `LEGACY_IMPORT` snapshot, an evidence build
labelled `NOT_CURATED` / `NOT_PUBLICATION_ELIGIBLE`, and 1,559 unreviewed
prototype interpretations sitting in a queue. The governance holds today —
nothing may cross into a rule — but the first sealed dataset must come from a
**new acquisition run under a new dataset identifier**, because the snapshot
lifecycle has no transition out of quarantine. Any plan that assumes the
current dataset can be promoted is wrong.

**The main risk in the next phase is not technical.** It is the temptation to
close a count. The 1,559 legacy proposals contain `demo_risk_level`,
`manual_risk_level` and `manual_phenotypes` fields; the 7 development cases
look like validation cases; a green test suite looks like validation. Each of
those substitutions would produce a number that satisfies a gate and means
nothing. The repository currently resists all three by construction. Keeping
that resistance intact while the counts finally start moving is the real
engineering problem of the next phase.

`ths6_achieved: false` · `release_may_proceed: false` · 6 of 6 gates BLOCKED
· 1 of 15 Definition of Done items satisfied · 0 of 9 signatures.

That is the correct and defensible state of this repository today.
