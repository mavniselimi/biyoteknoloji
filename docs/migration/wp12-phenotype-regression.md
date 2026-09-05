# WP-12 phenotype regression against the legacy engine

| Field | Value |
|---|---|
| Document ID | `DOC-MIG-006` |
| Work package | WP-12 — Exact Phenotype Engine Migration |
| Artifacts | `data/migration/wp12/phenotype-regression-report.json`, `phenotype-regression-allowlist.json` |
| Schema | `schemas/phenotype-regression-report.schema.json` |
| Scope | normalisation verdicts and matcher semantics only |

---

## 1. What is compared, and what is not

The six legacy demo profiles are normalised under `pgx-phenotype-input/1`, and
every value is compared with every `EXACT` rule phenotype plus the
`ONE_OF [RAPID, ULTRARAPID]` case, with the legacy answer beside the V2 answer.

No clinical output is compared. There is no approved ruleset, so there is
nothing to produce one from, and the report carries no field in which an
attention level, a coverage status or a medication could appear.

`risk_engine.py` is read as evidence and was not modified. `pgx/engine` may not
import it — a boundary test says so — so the legacy behaviour is transcribed in
`phenotype_legacy.py`, and a test imports the real module and asserts the
transcription still agrees over every value and pair the report uses. If
somebody edits the legacy table, that test fails rather than this comparison
quietly describing behaviour legacy no longer has.

## 2. P1–P6

| Profile | Observation |
|---|---|
| `P1_normal` | five genes, all `NORMAL`, all `NORMALIZED` |
| `P2_cyp2c19_poor` | `CYP2C19` → `POOR` exactly; the rest `NORMAL` |
| `P3_cyp2d6_poor` | `CYP2D6` → `POOR` exactly |
| `P4_cyp2d6_ultrarapid` | `CYP2D6` → `ULTRARAPID` exactly |
| `P5_cyp2c9_decreased` | `CYP2C9` → `INTERMEDIATE` exactly (the file's value is `intermediate`; the profile is *named* "decreased" and the value is not) |
| `P6_mixed_high_attention` | five genes normalising independently: `POOR`, `POOR`, `INTERMEDIATE`, `NORMAL`, `NORMAL` |

Every profile carries its own content hash, and the source file's digest is
asserted unchanged after the harness runs.

## 3. `LEGACY-BUG-001`

The demo profiles contain **no** `RAPID` value, which is precisely why WP-01
registered the bug with `disposition: registered_not_allowlisted` and no
selector rather than fabricating a case. The report supplies the missing
direction as a clearly-labelled *constructed* case instead.

| Case | Legacy | V2 |
|---|---|---|
| `RAPID` vs `EXACT ULTRARAPID` | matches | `NO_MATCH` |
| `ULTRARAPID` vs `EXACT RAPID` | matches | `NO_MATCH` |
| `RAPID` vs `ONE_OF [RAPID, ULTRARAPID]` | matches | `MATCH` — both are declared |

The second direction is also observable from the real data: `P4`'s
`ULTRARAPID` value satisfies a legacy rule group written for `rapid`, and does
not satisfy a V2 `EXACT RAPID` condition.

## 4. The four allowlisted differences

| ID | Legacy behaviour | V2 |
|---|---|---|
| `LEGACY-BUG-001-RAPID-TO-ULTRARAPID` | `PROFILE_MATCH_GROUPS['rapid']` contains `ultrarapid` | `NO_MATCH` |
| `LEGACY-BUG-001-ULTRARAPID-TO-RAPID` | `PROFILE_MATCH_GROUPS['ultrarapid']` contains `rapid` | `NO_MATCH` |
| `LEGACY-NORMAL-PHENOTYPE-SUPPRESSED` | `PROFILE_MATCH_GROUPS['normal']` is empty, so `NORMAL` satisfies *nothing* | `MATCH` against a `NORMAL` rule |
| `LEGACY-BROAD-DECREASED-FUNCTION-GROUPING` | `POOR` and `INTERMEDIATE` satisfy the invented group `decreased_function` | the group is an `UNSUPPORTED` input and no condition can declare it |

The third was not anticipated when the harness was written; it appeared the
first time the comparison ran, and it is a real and intentional divergence.
Legacy answers "should this raise a flag?" inside a function asked "is this the
same phenotype?", and suppressing the match makes an evaluated rule
indistinguishable from an axis no rule covered — the false-reassurance failure
`SAFETY-INV-001` exists to prevent. V2 separates the two: equality here,
attention in WP-14, carried by the rule's own outcome, which may be
`NO_ACTIVE_ATTENTION`.

Every entry carries a stable id, the observed legacy behaviour, the required V2
behaviour, a safety rationale, an architecture or safety-contract reference, a
comparison selector and an expected status. The schema requires all of them,
and requires the rationale to be substantive: a difference nobody justified is
a difference nobody decided.

## 5. How the harness fails

- an unexpected difference lands in `unexpected_differences`, which the schema
  requires to be present so it cannot be omitted when non-empty;
- an allowlisted difference that stops occurring lands in
  `expected_differences_not_observed`, because an intended difference that
  quietly disappears is as much a change as one that appears;
- either makes the CLI exit non-zero;
- the report is regenerated and compared byte for byte, so a non-deterministic
  row fails too.

Current result: **0 unexpected differences, 0 unobserved allowlist entries**,
with hits of 1, 2, 23 and 1 across the four entries.

## 6. Reproducing it

```
python3 -m pgx.application.phenotype_cli legacy-regression \
    --out data/migration/wp12/phenotype-regression-report.json
python3 -m pgx.application.phenotype_cli verify-regression
```

The report carries no timestamp, hostname, path, duration or process id, so two
runs on two machines produce identical bytes.
