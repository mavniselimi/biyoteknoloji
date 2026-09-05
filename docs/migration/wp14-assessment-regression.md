# WP-14 — legacy risk versus V2 assessment

| Field | Value |
|---|---|
| Document ID | `DOC-MIG-014` |
| Work package | WP-14 — Deterministic PGx Assessment Engine Migration |
| Report | `data/migration/wp14/assessment-regression-report.json` |
| Allowlist | `data/migration/wp14/assessment-regression-allowlist.json` |
| Report content hash | `sha256:d6fa35bae5a56408c36d3f6c67f040515b49f05b38c8c682e0aaa6efc73e82aa` |
| Harness | `pgx/engine/risk_legacy.py`; tests in `tests/unit/engine/test_risk_legacy_regression.py` |

---

## 1. What is and is not being compared

**No legacy clinical result is promoted here as an approved expected answer.**
This repository has no approved ruleset, so:

| Count | Value |
|---|---|
| Approved comparable real cases | 0 |
| Real V2 assessments executed | 0 |
| Real findings persisted | 0 |

What is compared is *behaviour*: given the situations the legacy artifacts
record, what does V2 emit instead. The synthetic half of the test suite proves
the engine calculates; this half proves it refuses to reassure.

## 2. The legacy artifacts were not edited

The WP-01 snapshots and `risk_engine.py` are unchanged, and tests assert each
defect is still there: codeine `none`, warfarin `none`, the group-normalising
matcher, the run-time seed-file read. The legacy behaviour **is** the defect.
Editing it would delete the evidence that anything needed correcting.

The same tests assert the P2 snapshot still carries its real findings —
clopidogrel `high`, voriconazole `high` — because that is what makes the two
`none` rows a defect rather than an empty run.

## 3. The corrections

### A. `LEGACY-BUG-002` — "none" rendered as low, no warning

The legacy engine uses `overall_risk_level: "none"` for three unrelated
situations: the drug is unknown, no rule matched, and there is nothing to
report. `RISK_LABEL_TR` renders all three as *"Düşük / uyarı yok"*.

V2 separates them. Absence is coverage, and coverage that is not `FULL` yields
`NOT_ASSESSED`. No absence path anywhere in the engine reaches `LOW` or
`NO_ACTIVE_ATTENTION`: `NO_ACTIVE_ATTENTION` is reachable only from `FULL`
coverage, and `NOT_ASSESSED` is excluded from every maximum, so it cannot be
outranked into invisibility either.

Codeine and warfarin are recorded as separate allowlist entries, because a fix
covering one drug would satisfy a single-entry allowlist.

### B. `LEGACY-BUG-001` — broad phenotype matching

The legacy matcher normalises a rule's phenotype group and accepts a profile
value by substring and group membership, so a `RAPID` profile can satisfy a
rule written about `ULTRARAPID`.

V2 uses WP-12's exact matcher: equality with a declared value, or membership in
an explicitly listed `ONE_OF`. `RAPID` reaches an `ULTRARAPID` rule only when
a curator wrote both into the list. No implicit cross-match can create a
finding (`SAFETY-INV-004`).

### C. `LEGACY-BUG-007` — the mutable seed dependency

The legacy engine reads its seed rule table and sibling files from disk at run
time, so the same input can produce a different answer after an unversioned
edit — a result that cannot be reproduced, audited or retracted.

The V2 calculation path consumes only pinned immutable release artifacts. The
harness scans the seven modules a V2 calculation actually executes and reports
how many name a seed file; the current answer is **0 of 7**, and the scan is
what proves it rather than the claim.

### D. Deterministic attention, on synthetic data

The situations with no legacy counterpart — a full axis with a validated
matched rule, a partial multi-axis result preserving a valid finding, a missing
phenotype, an unsupported drug, missing evidence, a source conflict, and
multiple independent findings aggregating to a maximum — are exercised against
the engine itself in `tests/safety/test_assessment_safety.py`,
`tests/unit/engine/test_risk_execution.py` and
`tests/integration/engine/test_assessment_end_to_end.py`.

## 4. The allowlist

Four entries across three legacy bugs. The harness fails if an entry's
difference stops appearing, if a difference appears that no entry covers, or if
the report is not reproducible byte for byte. In the current run all four
entries are hit exactly once, none went unobserved, and there are no unexpected
differences.

A test proves the harness can actually fail: it copies the repository, appends
a seed-file name to `pgx/engine/risk.py`, and asserts the run reports an
unexpected difference and an unobserved entry.

## 5. What this report is not

Migration evidence, not clinical validation. No coverage status and no
attention level in it asserts safety, preference or suitability for any
medicine, and no legacy clinical output is treated as a correct answer that V2
must reproduce.
