# WP-20 — Safety Invariant Suite

| Field | Value |
|---|---|
| Document ID | `DOC-WP20-001` |
| Work package | WP-20 — Safety Invariant Suite |
| Owns | `pgx/safety/`, `pgx/application/safety_{cli,schema}.py`, `tests/unit/safety/`, `tests/fixtures/wp20/`, `schemas/wp20/`, `data/safety/`, `.github/workflows/safety-gate.yml` |
| Command | `pgx-safety` (`python -m pgx.application.safety_cli`) |
| Normative source | `docs/risk-management/safety-contract.md` section 2 |
| Does **not** own | validation metrics (WP-21), expert review (WP-22), auth/audit (WP-23), the build pipeline (WP-24) |

> **This is a software safety gate.** Detecting an unsafe negative control
> proves that a software detector rejects that state. It is not clinical
> validation, scientific validation, expert review, or evidence that the system
> is safe for any patient.

---

## 1. The question WP-19 could not answer

WP-19 answers *"did the tests run and pass?"* — 5,964 discovered, zero
failures. WP-20 answers a different one: **"is each named invariant actually
enforced, and can its detector prove it would catch the unsafe case?"**

Those come apart, and the gap is not academic. A suite can be entirely green
while an invariant has no detector at all, because nothing fails when nothing
looks. Every one of the twelve invariants in the safety contract was, before
this work package, a paragraph in a document plus some tests that happened to
be related to it.

So each invariant now carries two executions that must **both** happen:

- a **safe control** — the conforming case, through the real evaluator;
- a **negative control** — a deliberately unsafe case that the same evaluator
  must reject with a named code.

Asserting that a mutant fixture *contains* the string `safety_score` proves
something about the fixture. It proves nothing about the detector. The mutant
goes through the gate whose success is being claimed, or the claim is not made.

## 2. Twelve, not ten

`architecture.md` asks for "`SAFETY-INV-001` through at least `010`". The safety
contract defines **twelve**. A registry that stopped at ten would drop
`SAFETY-INV-011` (real patient data must not enter P0) and `SAFETY-INV-012`
(determinism and auditability) — two of the three invariants with the widest
blast radius.

The identifier pattern in the published schema admits `001` through `012` and
nothing else, so a thirteenth invariant requires a schema change somebody has
to review.

## 3. Architecture

```
pgx/safety/
  vocabulary.py     the six execution states, five compliance states,
                    sixteen enforcement surfaces — none of them ordered
  definitions.py    the twelve, as immutable data
  controls.py       the 37 negative controls, as data separate from fixtures
  evaluators.py     the twelve detectors, written against injected subjects
  registry.py       the fail-closed validator
  execution.py      per-invariant state from controls + test results
  freshness.py      binding evidence to the code it verified
  report.py         controls, tests, and the false-reassurance corpus
  gate_status.py    every component, reported separately
  artifacts.py      writes — and refuses to write the wrong thing
  errors.py         faults in the gate, distinct from unsafe behaviour
```

### 3.1 The evaluators take their subject as an argument

This is the single decision the package is built around. Written the other way
— each evaluator importing the module it checks — a mutant could only ever be
*inspected*, never *evaluated*.

```python
def evaluate_phenotype_matching_is_exact(matcher, phenotypes) -> Verdict:
    ...
```

The shipped matcher and the prefix-matching mutant go through the same
function. The function's answer is the evidence.

### 3.2 Seven of twelve safe controls are the shipped code

Where the production implementation is directly callable, that is the subject —
so a regression in shipped code fails the safety gate, not only a mutant test.

| Invariant | Safe control subject |
|---|---|
| 001 | `pgx.engine.risk_models.aggregate_attention` |
| 003 | `RuleStatus.VALIDATED` from the shipped domain enum |
| 004 | exact membership, as the engine matches |
| 009 | `pgx.validation.separation.audit_partition` |
| 010 | `pgx.domain.claims.scan_claim_text` |
| 011 | `apps.api.contracts.validate.find_prohibited_fields` |
| 012 | `pgx.domain.hashing.sha256_digest` |

The other five use reference implementations, and `subject_kind` records which
is which. "The detector accepts correct behaviour" and "the shipped code
behaves correctly" are different claims, and only the second is worth a release
gate on its own. For 002 and 005 a reference subject is the *only* possible one
— P0 ships neither an LLM renderer nor candidate exploration.

### 3.3 The fixtures are test-only, and the gate says so

`pgx/safety` never imports `tests.fixtures.wp20` — not even inside a function;
`test_boundaries.py` reads syntax trees to enforce it. The control driver is
loaded lazily by name.

A shipped wheel has no `tests`, so a deployed copy genuinely cannot run the
negative controls. The gate reports `NOT_EXECUTED` there rather than inheriting
a result from a machine that could.

## 4. The states

| State | Means | Never means |
|---|---|---|
| `PASS` | ran, held, every control satisfied | — |
| `FAIL` | ran and did not hold, or a detector accepted its mutant | that the test is broken |
| `ERROR` | raised before deciding | that the code is wrong |
| `BLOCKED` | a later WP or absent dependency owns part of it | a pass, or a failure |
| `NOT_EXECUTED` | nothing ran | a pass |
| `STALE` | passed, about code that has since changed | current |

Compliance is separate again: `COMPLIANT`, `VIOLATED`, `NOT_PRESENT`,
`DEFERRED_TO_LATER_WP`, `UNKNOWN`. Every enum has ordering **disabled** — the
moment `BLOCKED < PASS` type-checks, somebody writes `max(states)`.

### 4.1 `NOT_PRESENT` and the obligation that comes with it

Two invariants are enforced by proving the feature is absent: the LLM renderer
(002) and candidate exploration (005). That is a legitimate P0 answer and a
dangerous one the moment the feature ships, so each carries `absence_markers` —
paths whose *appearance* makes the registry refuse to load.

`NOT_PRESENT` may never excuse an unsafe feature that exists, and
`test_registry.py` proves the refusal by pointing a marker at a file that does.

## 5. Failing closed

The registry refuses to load when an invariant is missing, an identifier is
duplicated, an unknown one appears, a selector matches no test, a negative
control is missing or names a fixture nobody wrote, a control is claimed by the
wrong invariant, or a `NOT_PRESENT` feature has appeared.

Each has a plausible alternative that lets a build succeed. Checking the eleven
that remain would turn *deleting* a safety requirement into a way of satisfying
it.

## 6. Negative controls

37 across the twelve, each an in-memory double or injected unsafe
implementation under `tests/fixtures/wp20/`. **Nothing modifies production
source on disk** — a mutation test that edited a real module would leave the
repository broken if interrupted, and would make the suite's result depend on
the order it ran in.

Seven reproduce legacy defects:

| Legacy defect | Invariant | The mutant |
|---|---|---|
| `LEGACY-BUG-001` | 004 | `"RAPID" in "ULTRARAPID"` prefix matching |
| `LEGACY-BUG-002` | 001 | absence mapped to `LOW` — *"Düşük / uyarı yok"* |
| `LEGACY-BUG-005` | 006 | a finding with a dangling evidence reference |
| `LEGACY-BUG-006` | 003 | a `DRAFT` rule that fires |
| `LEGACY-BUG-007` | 007, 012 | persistence with no version metadata; order-dependent output |
| `LEGACY-BUG-009` | 005 | a 0–100 clinical suitability score |
| `LEGACY-BUG-012` | 010 | dosing language reaching a release surface |

## 7. Evidence freshness

Evidence is fingerprinted over ten trees — the registry, the evaluators, the
controls, the fixtures, and the domain, engine, reporting and validation
surfaces the invariants govern. Change any, and a recorded `PASS` becomes
`STALE`.

Named individually rather than as one digest, so a stale result says *which*
input moved. "The engine changed" is actionable; "something changed" is not.

Never fingerprinted: absolute paths, usernames, hostnames.

## 8. What a run may not leave behind

`check --write` writes the **report** whatever the outcome — a blocked gate
still produced 37 control results somebody needs to read. It writes the
**execution evidence** only on `PASS`, and replaces it with an explicit
invalidation otherwise.

Leaving an earlier success in place would let a failing build inherit a passing
gate, which is the single most dangerous thing this package could do.

## 9. Integration with WP-19

WP-19 said its safety map was mapping-only and that WP-20 owned the gate. Both
statements needed updating, and each was changed in the open:

- `safety_invariant_map_only` moved from `const: true` to a boolean, **together
  with its published schema and its tests**;
- `VERIFICATION_SAFETY_GATE_OWNED_BY_WP20` — a standing blocker — was replaced
  by `VERIFICATION_SAFETY_GATE_NOT_PASSING`, which reports WP-20's *measured*
  state and is `ABSENT` when no WP-20 status is committed. WP-19 does not run
  the gate on WP-20's behalf;
- `SAFETY-INV-011` and `012` were added to the map;
- a real `safety` profile was added, deriving its modules from the map;
- the WP-20 tests were classified in the deterministic inventory.

**Two defects in WP-19's map were found and corrected.** `SAFETY-INV-008` was
mapped to the report-injection and claim tests, which are `010`'s subject;
`SAFETY-INV-010` was mapped to the snapshot and hashing tests, which belong to
determinism. Both rows read plausibly and were about the wrong requirements —
exactly the failure a map nobody resolves against the contract will have.

## 10. A finding about the claim scanner

Four unambiguously prohibited phrasings pass `scan_claim_text` clean:

- `"Bu hasta icin X kullanmanizi oneririz."`
- `"We recommend X for this patient."`
- `"Start X for this patient."`
- `"Dozu 25 mg gunluk olarak azaltin."`

Two of them are not paraphrase — "We recommend X for this patient" is the most
direct English form of a recommendation there is.

**WP-20 does not fix this.** The pattern registry in `pgx/domain/claims.py` is a
reviewed governance artifact, and adding clinical phrasings to it on an
implementer's judgement would be exactly the unreviewed claim the system exists
to prevent. What WP-20 does is measure the gap, count it in the gate status,
hold it in `KNOWN_SCANNER_GAPS` so closing one is visible, and raise
`SAFETY_CLAIM_SCANNER_KNOWN_GAPS` as a blocker owned by the claim-registry
reviewers.

## 11. What WP-20 did not do

- No application, engine, rules, reporting, API or web logic was changed.
- No assertion was weakened, no blanket skip added, no verification floor
  lowered.
- No clinical validation, expert review, human approval or metric was produced
  or implied.
- No authentication or audit writer was invented; the audit half of
  `SAFETY-INV-012` stays explicitly blocked on WP-23.
- The CI job is reported **CONFIGURED, not EXECUTED**. A workflow file proves
  somebody wrote a job; only an observed provider run could set the other field.
- WP-21 and later were not started.
