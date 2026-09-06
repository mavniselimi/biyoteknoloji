# WP-07 handoff

| Field | Value |
|---|---|
| Document ID | `DOC-HANDOFF-007` |
| Work package | WP-07 - Canonical Resolver, Deduplication and Data Quality |
| Status | **Offline scope complete. No dataset is quality checked, approved or publishable.** |
| Output for WP-08 | one sealed, reproducible canonical build over the quarantined legacy snapshot |

> Read this before WP-08. Two items must not be presented as met: **A11**, the
> documented 1,572 collision figure, which is **FAIL** — the real artifacts
> yield 1,644 and the discrepancy is unresolved; and **A24**, a quality-checked
> dataset, which is **BLOCKED** because the snapshot is quarantined and no
> human has approved the source.

---

## 1. What exists now

| Artefact | What it is |
|---|---|
| `pgx/normalization/normalize.py` | Deterministic value normalisation; `pgx-normalization/1` |
| `pgx/normalization/models.py` | Canonical entities, locators, alias review state, outcomes, duplicate groups |
| `pgx/normalization/artifacts.py` | What each raw artifact is for; `pgx-artifact-roles/2` |
| `pgx/normalization/extract.py` | Reads a snapshot into candidates, references and observations; `pgx-extraction/1` |
| `pgx/normalization/resolver.py` | The strict five-step resolver; `pgx-resolver/1` |
| `pgx/normalization/dedup.py` | Duplicate detection that keeps every locator; `pgx-dedup/1` |
| `pgx/normalization/allocation.py` | Explicit identity allocation; `pgx-identity-allocation/1` |
| `pgx/normalization/build.py` | Build assembly, atomic seal, comparison; `pgx-canonical-build/1` |
| `pgx/normalization/quality.py` | DQ metrics and the fail-closed gate; `pgx-data-quality/1` |
| `pgx/normalization/legacy_diff.py` | What changed against the legacy seed; `pgx-legacy-differences/1` |
| `pgx/normalization/ports.py` | Persistence ports; no implementation exists |
| `pgx/application/normalize_cli.py` | `pgx-normalize`, eight read/build commands |
| `pgx/application/canonical_schema.py` | Loads and applies the two published schemas |
| `pgx/application/canonical_service.py` | The one audited transition: `BUILDING -> QUALITY_CHECKED`, reachable from code and never from the CLI |
| `schemas/canonical-dataset-manifest.schema.json`, `schemas/data-quality-report.schema.json` | The published contracts |
| `config/wp07-legacy-expectations.json` | Documented figures recorded as *claims with citations*, checked on every build |
| `migrations/versions/0005_wp07_canonicalization.py` | Five tables, alias review columns, build-immutability trigger, two constraint replacements |
| `data/canonical/PGX-DATA-20260830-900/` | The sealed canonical build |
| `scripts/normalize.py`, `scripts/render_wp07_schema.py` | Operator and evidence tooling |

Policy documents: [canonicalization-policy](../data/canonicalization-policy.md),
[resolution-policy](../data/resolution-policy.md),
[deduplication-policy](../data/deduplication-policy.md),
[data-quality-contract](../data/data-quality-contract.md). Evidence:
[wp07-dq-validation](../evidence/wp07-dq-validation.md). Legacy comparison:
[wp07-legacy-differences](../migration/wp07-legacy-differences.md).

## 2. What the build contains

| Measure | Value |
|---|---|
| Canonical genes | 5 (`CYP1A2`, `CYP2C19`, `CYP2C9`, `CYP2D6`, `CYP3A4`) |
| Canonical drugs | 11 — the drugs the source itself resolved |
| Identities allocated | 16, all `uuid4`, recorded in `identity-allocation.json` |
| Provenance links | 16 |
| Alias proposals | 0 observed in this snapshot; 0 approved |
| Resolution attempts | 29, all `RESOLVED` at stage two |
| Resolution queue | empty |
| Record observations | 3,466 |
| Distinct records | 1,822 |
| Duplicate groups | 1,644, all `SEMANTIC` (case-variant containers) |
| Blocking duplicate groups | 0 |
| Records with no source identity | 0 |
| Excluded P1 candidate records | 8,182, counted and not imported |

`source_observed_*` counts describe what the snapshot mentions. They are not
validated coverage, clinical coverage, supported treatment, safe alternatives or
executable pharmacogenetic rules.

## 3. What is blocked, and why

### 3.1 A11 — the 1,572 collision figure is FAIL

`architecture.md` records "the 1,572 runtime dedup collisions". That number is
not reproducible from the real artifacts. Every measurement that can be defined
precisely was tried; the closest is **1,644** under the per-pair case-folded
container-family identity, and none yields 1,572. Outside that one sentence and
the expectations file that records it as a claim, the string `1572` appears in
no legacy script, output or data file.

The observed count is reported as observed. The dedup key was **not** distorted
to reach the documented figure, and a test asserts that no module under `pgx/`
contains `1572` as a numeric literal.

**What WP-08 should do:** either correct `architecture.md` to 1,644 with the
measurement stated, or identify the artifact and identity the original figure
was taken over. Do not change the dedup key to make the number appear.

### 3.2 A24 — no dataset is quality checked

The gate is BLOCKED on three findings, all correct:

- `SNAPSHOT_QUARANTINED` — `PGX-DATA-20260830-900` is a quarantined legacy import.
- `SNAPSHOT_NOT_ACQUIRED` — no WP-04 acquisition run backs it, so completeness
  relative to the upstream source is unknown.
- `SOURCE_POLICY_MISSING` — no human has approved the ClinPGx source (WP-05
  A19/A20, still open).

The dataset is `BUILDING` and stays there. There is no function, CLI command or
repository method in this repository that marks a dataset `QUALITY_CHECKED`,
publishes one, or activates a release. Migration `0005` adds the
`DATASET_QUALITY_CHECKED` audit action and narrows the dataset approval
constraint so a real decision *has somewhere to go* and cannot be recorded
without a named approver — WP-07 emits none.

Unblocking A24 requires a named human completing
`docs/scientific/source-review-checklist.md`, and a fresh acquisition-backed
snapshot. Neither is a code change here.

### 3.3 Alembic and persistence remain BLOCKED

Alembic and SQLAlchemy cannot be installed in this environment. Migration `0005`
was verified by rendering its AST to DDL and executing it on real PostgreSQL
16.13, together with `0001`–`0004`, plus an up/down/up cycle. That proves the
schema and its constraints; it proves nothing about Alembic's runner or
`alembic_version`.

`pgx/normalization/ports.py` defines the persistence ports, including
`DatasetLifecycleRepository`, whose `record_quality_check` an implementation
must apply as a guarded `UPDATE ... WHERE status = ...` rather than a read
followed by an unconditional write. **No implementation exists.** WP-08 or a
later package must write the ORM models, repositories and unit of work against
those ports. The transition service itself is written and tested against a fake
unit of work, so the behaviour it requires is pinned before any adapter exists.

## 4. Decisions WP-08 inherits

**Ambiguity is data, not a problem to be solved by code.** An ambiguous
resolution stops the search, carries every candidate, and produces an undecided
queue item. Nothing narrows it later. If WP-08 needs a resolved entity where the
queue has an open item, the answer is a human decision, not a fallback.

**Only an APPROVED alias resolves.** Migration `0005` backfilled every existing
alias to `PENDING_REVIEW`. Any code that previously relied on an observed alias
resolving will now find it does not, and that is the intended correction.

**Identity is allocated, never derived.** `GeneId` and `DrugId` still have no
`derive()`. Reproducing a build means passing `--allocation`; minting requires
`--allocate-new-identities`. Do not add UUID5 derivation to a scientific
identifier.

**Nothing is discarded in deduplication.** Every member locator survives. A
`CONFLICTING_IDENTITY` group is always blocking and never merged. If WP-08 finds
one, it needs a human reading both records, not a merge rule.

**No interpretation crosses this boundary.** A canonical record carries no
significance, polarity, score, severity, risk, phenotype effect, recommendation
or plain-language conclusion. Those fields are WP-08's to *create*, from source
facts plus a curator's judgement — not to copy from the legacy CSVs, which mix
them in with source facts. `MANUAL_EFFECT_HINTS`, `demo_risk_level` and
`plain_language_mvp` remain unimported.

**Candidate-onboarding data is out of P0.** The four drugs and four pairs
`candidate_onboarding.py` added to the mutable seed are excluded, counted and
named. Bringing them in is a P1 decision with a reviewer attached, not a
migration step.

## 5. Open items for WP-08

| # | Item | Owner |
|---|---|---|
| 1 | Correct or explain the 1,572 figure in `architecture.md` | project |
| 2 | ORM models, repositories and unit of work for the five WP-07 tables | WP-08 |
| 3 | Alembic verification once the toolchain is installable | infrastructure |
| 4 | A named human review of the ClinPGx source policy | project |
| 5 | An acquisition-backed snapshot to replace the quarantined legacy import | WP-04 rerun |
| 6 | Review the 29 `label` / `DrugLabel` container-synonym records | curation |
| 7 | Decide whether any observed alias should be approved | curation |

## 6. How to reproduce everything in this handoff

```
python3 scripts/normalize.py build \
  --snapshot data/raw/clinpgx-legacy-v2/PGX-DATA-20260830-900 \
  --allocate-new-identities --text
python3 scripts/normalize.py verify  --build data/canonical/PGX-DATA-20260830-900 --text
python3 scripts/normalize.py dq      --build data/canonical/PGX-DATA-20260830-900 --text
python3 scripts/normalize.py queue   --build data/canonical/PGX-DATA-20260830-900 --text
python3 scripts/normalize.py compare-legacy --build data/canonical/PGX-DATA-20260830-900 --text
python3 scripts/normalize.py quality-check  --build data/canonical/PGX-DATA-20260830-900 --text
PYTHONDONTWRITEBYTECODE=1 python3 -W error::ResourceWarning \
  -m unittest discover -s tests -p 'test_*.py' -t .
```

No command above reaches the network, writes to `data/raw/`, or changes a
dataset's lifecycle state.
