# WP-20 - Safety invariant evidence

| Field | Value |
|---|---|
| Document ID | `DOC-WP20-004` |
| Work package | WP-20 - Safety Invariant Suite |
| Machine-readable | `data/safety/wp20-real-gate-status.json` |
| Recorded execution | `data/safety/wp20-safety-report.json`, `data/safety/wp20-safety-execution.json` |
| Registry | `data/safety/wp20-invariant-registry.json`, `data/safety/wp20-negative-controls.json` |
| Produced on | Linux, CPython 3.11, `uid 0`, no PostgreSQL, no `coverage.py`, no network |
| Governing document | `docs/risk-management/safety-contract.md` (`DOC-SC-001`) - **frozen**, unmodified by WP-20; see the registry document, section 1.1 |

> **Software detector evidence only.** Everything below describes software
> detectors and software behaviour: which unsafe states this code rejects,
> and which safe states it accepts. It is **not** clinical validation, not
> scientific validation, not expert review, not a holdout result, and not
> evidence that the system is safe for any patient. No human approval is
> asserted, implied, or created by this document.

---

## 1. What was executed

`pgx-safety check` builds the registry, runs the twelve invariant
evaluators, drives 37 negative controls and 12 safe controls through those
same evaluators, runs the 1,088 tests bound to the invariant selectors,
collects blockers, and computes a gate state.

Two environments, kept apart in every claim below.

| | This run | The developer's macOS `.venv` |
|---|---|---|
| Platform | Linux, CPython 3.11.15 | macOS, CPython 3.14.7 |
| Effective user | `uid 0` | ordinary account |
| `psycopg` | absent | 3.3.5, **no server started** |
| `coverage.py` | absent | absent |
| Package index reachable | no | not attempted |
| PostgreSQL server | none | none |

Neither environment reached a PostgreSQL server. No coverage percentage is
reported anywhere in this document, because `coverage.py` is installed in
neither environment and a number that was not measured must not appear.

## 2. Result

| Measure | Value |
|---|---|
| Safety gate status | **`BLOCKED`** |
| Release may proceed | **`false`** |
| Invariants registered | 12 |
| Invariants executed | 12 |
| Execution states | 7 `PASS`, 5 `BLOCKED`, **0 `FAIL`, 0 `ERROR`** |
| Negative controls detected | **37 / 37** |
| Safe controls accepted | **12 / 12** |
| False-reassurance violations | **0** over a corpus of 36 |
| Prohibited-claim surfaces | 6 enforced, 3 release-blocking |
| Claim-scanner known gaps | 4 |
| Stale or missing selectors | 0 |
| Unexplained skips | 0 |
| Tests executed under safety selectors | 1,088 |
| Blockers standing | 11 |

`BLOCKED` with zero failures is the honest reading of this system today:
every detector that could execute did execute and behaved correctly; the
gate is held open by things software cannot close.

## 3. Per-invariant result

Test counts are tests under that invariant's selectors; a module covering
two invariants is counted under both, so the column does not sum to 1,088.

| ID | Execution | Implementation | Tests | Failed | Errored | Unexplained skips | Controls |
|---|---|---|---|---|---|---|---|
| `SAFETY-INV-001` | `PASS` | `COMPLIANT` | 121 | 0 | 0 | 0 | 2/2 |
| `SAFETY-INV-002` | `BLOCKED` | `NOT_PRESENT` | 64 | 0 | 0 | 0 | 3/3 |
| `SAFETY-INV-003` | `PASS` | `COMPLIANT` | 81 | 0 | 0 | 0 | 3/3 |
| `SAFETY-INV-004` | `PASS` | `COMPLIANT` | 69 | 0 | 0 | 0 | 3/3 |
| `SAFETY-INV-005` | `BLOCKED` | `NOT_PRESENT` | 131 | 0 | 0 | 0 | 3/3 |
| `SAFETY-INV-006` | `PASS` | `COMPLIANT` | 60 | 0 | 0 | 0 | 3/3 |
| `SAFETY-INV-007` | `BLOCKED` | `COMPLIANT` | 100 | 0 | 0 | 0 | 4/4 |
| `SAFETY-INV-008` | `PASS` | `COMPLIANT` | 64 | 0 | 0 | 0 | 3/3 |
| `SAFETY-INV-009` | `BLOCKED` | `COMPLIANT` | 54 | 0 | 0 | 0 | 3/3 |
| `SAFETY-INV-010` | `PASS` | `COMPLIANT` | 135 | 0 | 0 | 0 | 3/3 |
| `SAFETY-INV-011` | `PASS` | `COMPLIANT` | 137 | 0 | 0 | 0 | 4/4 |
| `SAFETY-INV-012` | `BLOCKED` | `COMPLIANT` | 72 | 0 | 0 | 0 | 3/3 |

The five `BLOCKED` states and their owners are set out in
`docs/risk-management/wp20-invariant-registry.md` section 3.1. In summary:
`SAFETY-INV-002` and `SAFETY-INV-005` guard surfaces P0 does not ship
(P1-06, P1-02); `SAFETY-INV-007` and `SAFETY-INV-012` need WP-23's audit
record; `SAFETY-INV-009` has zero holdout cases to separate.

## 4. Negative controls - what this does and does not prove

### 4.1 Method

Each evaluator in `pgx/safety/evaluators.py` takes its subject as an
argument. The shipped implementation and the mutant are therefore passed to
the **same function**; there is no separate "mutant checker" whose success
could be claimed as the real detector's success.

A negative control counts as **detected** only when both hold:

1. the evaluator refuses the mutant, and
2. the refusal code it emits equals the code the catalogue declared in
   advance.

A control that is refused for the wrong reason is not satisfied. This is
enforced by `ControlOutcome.satisfied` in `pgx/safety/execution.py`, not by
inspection.

No production source file is modified during mutation testing. The mutants
live in `tests/fixtures/wp20/` as separate modules; nothing writes into
`pgx/` at test time. `tests/unit/safety/test_boundaries.py` additionally
asserts that the shipped `pgx.safety` package never imports `tests.*`, so a
wheel built without the test tree reports `NOT_EXECUTED` rather than
silently passing.

### 4.2 Result

| Invariant | Negative controls | Detected | Safe control | Safe subject |
|---|---|---|---|---|
| `SAFETY-INV-001` | 2 | 2 | accepted | production (`aggregate_attention`) |
| `SAFETY-INV-002` | 3 | 3 | accepted | reference |
| `SAFETY-INV-003` | 3 | 3 | accepted | production (`RuleStatus.VALIDATED` selection) |
| `SAFETY-INV-004` | 3 | 3 | accepted | production (exact membership) |
| `SAFETY-INV-005` | 3 | 3 | accepted | reference |
| `SAFETY-INV-006` | 3 | 3 | accepted | reference |
| `SAFETY-INV-007` | 4 | 4 | accepted | reference |
| `SAFETY-INV-008` | 3 | 3 | accepted | reference |
| `SAFETY-INV-009` | 3 | 3 | accepted | production (`audit_partition`) |
| `SAFETY-INV-010` | 3 | 3 | accepted | production (`scan_claim_text`) |
| `SAFETY-INV-011` | 4 | 4 | accepted | production (`find_prohibited_fields`) |
| `SAFETY-INV-012` | 3 | 3 | accepted | production (`sha256_digest`) |
| **Total** | **37** | **37** | **12/12** | 7 production, 5 reference |

The production/reference split is recorded per invariant in
`tests/unit/safety/_support.py` (`SUBJECT_KIND`) rather than left implicit.
Where the safe subject is a reference implementation, the acceptance result
demonstrates that the detector does not refuse a correct subject - it does
**not** demonstrate that shipped production code occupies that surface,
because for those five invariants no shipped code does.

### 4.3 What 37/37 means and does not mean

It means: these 37 unsafe states, passed through these detectors, are
rejected with the expected refusal code.

It does not mean: the system is safe; the detectors are complete; every
unsafe state is covered; any clinical property has been validated; any
patient-facing risk has been assessed. Detector coverage is bounded by the
imagination of whoever wrote the controls. Section 6 below documents four
unsafe phrasings this control set *found* that the shipped scanner does not
catch, which is direct evidence that the bound is real.

## 5. False reassurance sweep

`SAFETY-INV-001` is the highest-consequence invariant in the system: a
clinician reading "no risk" where the correct reading is "we did not look".

Every combination of coverage status and calculated attention level the
aggregator can be handed was swept exhaustively - 36 combinations.

| Measure | Value |
|---|---|
| Corpus size | 36 |
| Target | exactly 0 |
| Violations | **0** |
| Meets target | yes |

One subtlety is recorded rather than hidden. For inputs containing
`NOT_ASSESSED`, `aggregate_attention` does not return a safe value - it
**raises** `AssessmentEngineError` ("NOT_ASSESSED is not a calculated level
and may not enter an aggregation"). The sweep counts that refusal toward the
corpus and *not* toward the violations, because a refusal is the invariant
holding in its strongest available form: the engine declines to produce any
attention level rather than producing a reassuring one.

> This is a count over a software corpus. It is **not** a clinical
> false-negative rate and says nothing about how often a real case would be
> mishandled.

## 6. A finding recorded rather than patched

Building the `SAFETY-INV-010` controls surfaced four prohibited phrasings
that `scan_claim_text()` does not match:

| Gap ID | Phrasing |
|---|---|
| `tr/first-person-recommendation` | `Bu hasta icin SYNTHDRUG-2 kullanmanizi oneririz.` |
| `en/first-person-recommendation` | `We recommend SYNTHDRUG-2 for this patient.` |
| `en/imperative-medication-change` | `Start SYNTHDRUG-2 for this patient.` |
| `tr/dosing-imperative` | `Dozu 25 mg gunluk olarak azaltin.` |

They are recorded as `KNOWN_SCANNER_GAPS` in
`tests/fixtures/wp20/unsafe_text.py`, asserted by
`TestTheScannerHasKnownGaps` (so silently "fixing" one without updating the
record fails the suite), published as `claim_scanner_known_gap_count = 4` in
the gate status, and raised as the blocker
`SAFETY_CLAIM_SCANNER_KNOWN_GAPS`.

They were not patched. The claim registry is a reviewed governance artifact
whose scope and stated limits are themselves a reviewed position
(`safety-contract.md` section 3.1). Extending it with clinical phrasings on
an implementer's judgement would be precisely the unreviewed clinical claim
this system exists to prevent. Measuring the gap, publishing it, and
blocking the gate on it is the action that respects the review boundary.

This also quantifies a limitation the contract already stated in prose:
paraphrase evasion is not hypothetical. The count is four *under this
control set*, and will change as the control set grows. It is a lower bound
on the scanner's blind spots, never an upper bound.

## 7. Blockers standing

Eleven blockers. None of them can be closed by writing code in WP-20.

| Code | Owner | Why it stands |
|---|---|---|
| `SAFETY_CLAIM_BOUNDARY_NOT_APPROVED` | named human and scientific reviewers | claim boundary reads `DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW` |
| `SAFETY_CLAIM_SCANNER_KNOWN_GAPS` | WP-00 claim registry reviewers | 4 prohibited phrasings unmatched (section 6) |
| `SAFETY_NO_ACTIVE_RELEASE` | WP-03 operation | no release registered or active |
| `SAFETY_NO_HOLDOUT_CASES` | scientific curators | zero holdout cases exist to separate |
| `SAFETY_POSTGRESQL_NOT_EXERCISED` | deployment | no server reached; database half of persistence and separation did not execute |
| `SAFETY_CI_JOB_NOT_EXECUTED` | WP-24 / a CI provider | workflow **configured, not executed** |
| `SAFETY_INVARIANT_BLOCKED_BY_LATER_WP` ×5 | P1-06, P1-02, WP-23, WP-21, WP-24 | the five invariants in section 3 |

The execution evidence at `data/safety/wp20-safety-execution.json` reads
`INVALIDATED`, not `ABSENT` and not a stale `PASS`: `check --write` ran, the
gate reported `BLOCKED`, and the writer replaced the evidence with an explicit
invalidation record rather than leaving a previous result standing.

`validation_metrics_implemented`, `clinical_validation_performed` and
`expert_review_performed` are all `false` and are **pinned** to `false` in
`schemas/wp20/wp20-gate-status.schema.json` with `{"const": false}`. A gate
status claiming otherwise fails schema validation rather than being
believed.

## 8. Reproducing this

```
python -m pgx.application.safety_cli registry
python -m pgx.application.safety_cli negative-controls
python -m pgx.application.safety_cli check
python -m pgx.application.safety_cli check --write
python -m pgx.application.safety_cli gate-status
python -m pgx.application.safety_cli artifacts
python -m unittest discover -s tests/unit/safety -p 'test_*.py' -t .
```

`check` exits `2` in the current state. That is the correct outcome, not a
tooling failure: exit `0` would mean the gate passed, and it has not.

Evidence is fingerprinted over ten source trees; editing safety code, the
tests, the negative fixtures, the domain, the engine, the reporting layer or
the schemas invalidates it. A stale `PASS` cannot be presented as current.
The environment fingerprint excludes hostname, username and absolute paths,
so this evidence is not bound to any machine.

## 9. Explicit non-claims

- No clinical validation was performed.
- No scientific validation was performed.
- No expert review was performed or obtained.
- No human approval exists; this document does not create one.
- No holdout case exists; no holdout result is reported.
- No validation metric is implemented or reported (WP-21).
- No PostgreSQL execution occurred.
- No CI provider run occurred; the workflow is configured only.
- No coverage percentage is claimed; `coverage.py` is absent.
- No real patient, genotype, VCF, EHR or laboratory data was used,
  introduced, or is present in any fixture. `SAFETY-INV-011` is itself the
  detector for that claim, and it passes 4/4.

**WP-20's code is complete. The release safety gate is `BLOCKED`. Both
statements are true at the same time, and the second is the one that governs
release.**
