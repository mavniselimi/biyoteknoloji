# WP-20 - Executable Safety Invariant Registry

| Field | Value |
|---|---|
| Document ID | `DOC-SIR-020` |
| Document version | `1.0.0` |
| Status | **DESCRIPTIVE - NOT APPROVED** |
| Work package | WP-20 - Safety Invariant Suite |
| Machine-readable counterpart | `pgx/safety/definitions.py`, `pgx/safety/controls.py` |
| Generated artifacts | `data/safety/wp20-invariant-registry.json`, `data/safety/wp20-negative-controls.json` |
| Governing document | `docs/risk-management/safety-contract.md` (`DOC-SC-001`) |
| Architecture source | `architecture.md` sections 3, 12.1, 12.4, 13, 20 |
| Approved by | *(not approved - approval is a human act, see section 8)* |

> **This document describes software.** It records which safety invariants
> are registered, which detectors execute, and which negative controls the
> detectors reject. It is **not** clinical validation, scientific
> validation, expert review, or evidence that the system is safe for any
> patient. Those are produced by people under WP-21 and WP-22 and cannot be
> produced by running tests.

---

## 1. What this registry is for

Before WP-20 the safety requirements of this system lived in three
incompatible places: prose in `docs/risk-management/safety-contract.md`,
comments beside the code that implements them, and assertions scattered
across roughly a hundred test modules. Nothing tied the three together, so
three failure modes were all possible at once:

1. an invariant could be documented and never implemented;
2. an invariant could be implemented and never tested;
3. every ordinary unit test could pass while a safety requirement was
   silently unenforced, because no single thing knew the requirement
   existed.

WP-20 replaces that with one registry that is simultaneously authoritative
(it is the list), machine-readable (`data/safety/wp20-invariant-registry.json`),
executable (`pgx-safety check`), and release-blocking (a non-`PASS` state
exits non-zero and refuses to write evidence).

**Passing the ordinary unit suite does not imply the safety gate passed.**
The gate is a separate execution with its own artifacts, its own exit
codes and its own blockers. `python -m unittest discover -s tests` can be
entirely green while `pgx-safety check` exits `2`. That is the intended
relationship, not a defect.

## 1.1 Why this reference lives here and not in `DOC-SC-001`

The obvious place for the enforcement state below is inside
`docs/risk-management/safety-contract.md` itself, next to each invariant's
`Status:` line. It is not there, on purpose.

`docs/risk-management/safety-contract.md` is one of the 64 frozen
legacy/WP-00 artifacts pinned by SHA-256 in
`data/legacy-baseline/manifest.json`. The repository's own amendment tool,
`scripts/amend_legacy_manifest.py`, **refuses to touch those 64 entries at
all** - not their hashes, not their metadata, not their count - and the
regression suite asserts byte-identity on every one of them.

An edit to that file was written during WP-20 and then reverted, because
carrying it would have required amending the frozen baseline to bless a
change WP-20 made to a document WP-20 does not own. Doing that through the
only available path would have meant defeating a preservation guarantee in
order to obtain a green suite, which is the exact class of act this work
package exists to make impossible. The contract's bytes are unchanged and
its hash still matches the manifest.

So this document is the companion, and it is the one that moves. It carries
no authority the contract does not already grant: it reports what executed,
and it changes nothing about the contract's status, which remains
**DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW** with section 11.2 unsigned.

Whoever eventually folds this material into `DOC-SC-001` needs the WP-00
reviewers plus a baseline re-collection under `architecture.md` section 23 -
a governance act, not an implementation task.

Two consequences worth stating plainly:

- The per-invariant `Status:` lines in `safety-contract.md` section 2 are
  **WP-00's original assessment** and are now older than the measured state
  in section 3 below. Where they disagree, section 3 is what executed and
  the contract is what was reviewed. Neither supersedes the other; the
  disagreement belongs in review.
- Section 3.1 of the contract states the claim scanner's limits in prose.
  Section 7.1 below **quantifies** four of them. The prose was already
  correct; it is now measured.

## 2. Registry structure

Each invariant is an `InvariantDefinition` in `pgx/safety/definitions.py`
with the following fields. The registry validator
(`pgx/safety/registry.py`) refuses to build if any of them is inconsistent.

| Field | Meaning | Failure if wrong |
|---|---|---|
| `invariant_id` | `SAFETY-INV-001` .. `SAFETY-INV-012` | `DuplicateInvariant`, `UnknownInvariant` |
| `title` | one-line statement of the requirement | - |
| `requirement_reference` | the section of `safety-contract.md` this comes from | - |
| `severity` | `CRITICAL_PATIENT_FACING`, `CRITICAL_EVIDENTIAL`, `CRITICAL_SCOPE` | - |
| `required_surfaces` | the enforcement surfaces the contract demands | reported as `surface_gap` |
| `current_surfaces` | the surfaces that actually enforce it today | reported as `surface_gap` |
| `owning_work_packages` | who implements the enforcement | - |
| `test_selectors` | test modules that must exist and must run | `SelectorError` |
| `negative_controls` | control IDs that must exist in the catalogue | `NegativeControlMissing` |
| `legacy_bugs` | `LEGACY-BUG-*` IDs this invariant closes | - |
| `refusal_code` | the code the system must emit when it refuses | control mismatch |
| `implementation_state` | `COMPLIANT`, `NOT_PRESENT`, `DEFERRED_TO_LATER_WP` | - |
| `blockers` | why this invariant cannot reach `PASS` yet | forces `BLOCKED` |
| `absence_markers` | strings whose appearance would contradict `NOT_PRESENT` | registry refuses |
| `note` | the honest qualification a reader needs | - |

Two of these deserve explanation.

**`absence_markers`.** Two invariants (`SAFETY-INV-002`, `SAFETY-INV-005`)
are recorded as `NOT_PRESENT`: the surface they constrain does not exist in
P0 at all. That claim can rot. If someone later adds an LLM renderer or a
candidate-suitability score, the registry's assertion that "P0 ships none"
becomes false and the invariant would silently continue reporting a state
that no longer matches the code. Each `NOT_PRESENT` invariant therefore
carries markers - identifiers whose appearance in the shipped package means
the surface has arrived. The registry **refuses to build** when a marker is
found, rather than quietly downgrading. Absence is asserted, not assumed.

**`current_surfaces` vs `required_surfaces`.** Where they differ the
difference is published as `surface_gap` rather than hidden. Exactly one
invariant has a gap today: `SAFETY-INV-012` requires
`PERSISTENCE_BOUNDARY`, which is WP-23's append-only audit record. WP-20
enforces determinism of the calculated result; it does not enforce audit
completeness, and reporting the invariant as fully satisfied would be
false.

## 3. The twelve invariants

Severity abbreviations: `PATIENT_FACING` = `CRITICAL_PATIENT_FACING`,
`EVIDENTIAL` = `CRITICAL_EVIDENTIAL`, `SCOPE` = `CRITICAL_SCOPE`.

Test counts are tests executed under that invariant's selectors, so a module
covering two invariants is counted under both; the totals are not disjoint.

| ID | Requirement | Severity | Execution | Implementation | Tests | Neg. controls | Legacy bugs closed |
|---|---|---|---|---|---|---|---|
| `SAFETY-INV-001` | Missing data must never produce LOW or NO_ACTIVE_ATTENTION | PATIENT_FACING | `PASS` | `COMPLIANT` | 121 | 2/2 | LEGACY-BUG-002 |
| `SAFETY-INV-002` | An optional LLM must never alter calculated facts | PATIENT_FACING | `BLOCKED` | `NOT_PRESENT` | 64 | 3/3 | - |
| `SAFETY-INV-003` | Only VALIDATED rules from the pinned ruleset may execute | EVIDENTIAL | `PASS` | `COMPLIANT` | 81 | 3/3 | LEGACY-BUG-006 |
| `SAFETY-INV-004` | RAPID must not implicitly match ULTRARAPID | PATIENT_FACING | `PASS` | `COMPLIANT` | 69 | 3/3 | LEGACY-BUG-001 |
| `SAFETY-INV-005` | A candidate must not be labelled safer, preferred or scored | PATIENT_FACING | `BLOCKED` | `NOT_PRESENT` | 131 | 3/3 | LEGACY-BUG-009 |
| `SAFETY-INV-006` | Every calculated finding must carry resolvable, pinned evidence | EVIDENTIAL | `PASS` | `COMPLIANT` | 60 | 3/3 | LEGACY-BUG-005 |
| `SAFETY-INV-007` | Persistence requires the complete release bundle plus both hashes | EVIDENTIAL | `BLOCKED` | `COMPLIANT` | 100 | 4/4 | LEGACY-BUG-007 |
| `SAFETY-INV-008` | A source or rule conflict must not collapse into a reassuring result | PATIENT_FACING | `PASS` | `COMPLIANT` | 64 | 3/3 | - |
| `SAFETY-INV-009` | DEVELOPMENT, INTERNAL_HOLDOUT and EXPERT_HOLDOUT must not overlap | EVIDENTIAL | `BLOCKED` | `COMPLIANT` | 54 | 3/3 | - |
| `SAFETY-INV-010` | Prohibited claim text must block release of user-facing output | PATIENT_FACING | `PASS` | `COMPLIANT` | 135 | 3/3 | LEGACY-BUG-012 |
| `SAFETY-INV-011` | Real patient or genomic data must not enter P0 | SCOPE | `PASS` | `COMPLIANT` | 137 | 4/4 | - |
| `SAFETY-INV-012` | Released results must be deterministic and auditable | EVIDENTIAL | `BLOCKED` | `COMPLIANT` | 72 | 3/3 | LEGACY-BUG-007 |

`architecture.md` names ten safety invariants. This registry implements
**twelve**. The two additions are not inventions; they are requirements
already stated in `safety-contract.md` sections 3 and 8 that had no
invariant identifier of their own:

- `SAFETY-INV-010` - prohibited claim text blocks release. The claim
  registry existed since WP-00 and was tested, but nothing made a claim
  violation a *gate* failure.
- `SAFETY-INV-011` - real patient, genotype, VCF, EHR or laboratory data
  must not enter P0. This is the scope boundary the whole programme rests
  on; leaving it unenforced would mean the one boundary nobody may cross is
  the one boundary with no detector.

### 3.1 Why five invariants are `BLOCKED` rather than `PASS`

`BLOCKED` is not `FAIL`. In every one of the five cases below, every
executable check passed and every negative control was detected. `BLOCKED`
records that something outside the software's reach prevents the invariant
from being claimed as satisfied.

| ID | Every check passed? | Why not `PASS` | Owner |
|---|---|---|---|
| `SAFETY-INV-002` | yes, 3/3 | P1-06 owns the optional narration renderer. P0 ships none; the default is disabled; the deterministic report needs no model. The adversarial fixtures are test-only doubles, so a passing result describes doubles, not a shipped renderer. | P1-06 |
| `SAFETY-INV-005` | yes, 3/3 | P1-02 owns candidate exploration. P0 ships none. The legacy 0-100 suitability score is removed and must not return. | P1-02 |
| `SAFETY-INV-007` | yes, 4/4 | The release bundle and both hashes are enforced now. Actor, role, session and correlation identity on the audit record are WP-23's. | WP-23 |
| `SAFETY-INV-009` | yes, 3/3 | The separation mechanism is enforced and proven. There are **zero holdout cases to separate** - a scientific blocker no code can close. Whether a metric pools roles or hides a zero denominator is checkable once WP-21 metrics exist. | scientific curators, WP-21 |
| `SAFETY-INV-012` | yes, 3/3 | Determinism of the calculated result is enforced now. Audit completeness is not (WP-23), and repeat-run determinism across deployments and over time is a CI property (WP-24). WP-20 proves determinism within one process on one machine. | WP-23, WP-24 |

A reader who wants the shortest honest summary of the five: *the detector
works; the thing it is meant to guard does not exist yet, or the claim
needs a person.*

## 4. Legacy bug mappings

`architecture.md` requires each of the following legacy defects to be closed
by a named invariant. All seven mappings are asserted in
`tests/unit/safety/test_registry.py` against `pgx/legacy/legacy_bug_registry.py`,
so a renamed or dropped legacy bug fails the suite rather than silently
losing its mapping.

| Legacy bug | Required invariant | Registered | What the legacy code did |
|---|---|---|---|
| `LEGACY-BUG-001` | `SAFETY-INV-004` | yes | `RAPID` matched an `ULTRARAPID` rule |
| `LEGACY-BUG-002` | `SAFETY-INV-001` | yes | unsupported drug rendered as `Düşük / uyarı yok` |
| `LEGACY-BUG-005` | `SAFETY-INV-006` | yes | findings emitted without a resolvable evidence reference |
| `LEGACY-BUG-006` | `SAFETY-INV-003` | yes | non-validated rules participated in calculation |
| `LEGACY-BUG-007` | `SAFETY-INV-007` **and** `SAFETY-INV-012` | yes | results persisted without release identity or hashes |
| `LEGACY-BUG-009` | `SAFETY-INV-005` | yes | 0-100 "suitability" score read as a safety preference |
| `LEGACY-BUG-012` | `SAFETY-INV-010` | yes | prohibited claim text reachable in user-facing output |

`LEGACY-BUG-007` maps to two invariants deliberately: persistence
completeness and determinism/auditability are different failure modes of
the same legacy omission, and closing only one would leave the other open.

## 5. Negative controls

37 negative controls are catalogued in `pgx/safety/controls.py`
(`CONTROL_CATALOGUE_VERSION = "pgx-wp20-negative-controls/1"`), between two
and four per invariant. Each control is an unsafe *subject* - a mutant
engine, renderer, matcher, persister or payload - defined in
`tests/fixtures/wp20/`.

**The control must pass through the same evaluator whose success is being
claimed.** Every evaluator in `pgx/safety/evaluators.py` takes its subject
as an argument:

```python
evaluate_absence_never_reassures(aggregator, coverage_values, level_values, full_status)
evaluate_only_validated_rules_execute(selector, rules, pinned_ruleset_id)
evaluate_no_prohibited_claim(scanner, surfaces)
```

The shipped implementation and the mutant are passed to the *same function*.
A control counts as detected only when that function refuses **and** the
refusal code it emits equals the code the catalogue expects. A test that
merely asserts "the mutant fixture contains unsafe text" would prove
nothing about the detector, and no such test is counted here.

**No production source file is modified during mutation testing.** The
mutants are separate modules under `tests/fixtures/wp20/`; nothing writes to
`pgx/` at test time, and `tests/unit/safety/test_boundaries.py` asserts that
the shipped package never imports `tests.*`.

Alongside the 37 negative controls, 12 **safe controls** (one per invariant)
are run through the same evaluators and must be *accepted*. A detector that
refuses everything is not a detector. Seven of the twelve safe subjects are
the real production callables (`aggregate_attention`, `RuleStatus.VALIDATED`
selection, exact phenotype membership, `audit_partition`, `scan_claim_text`,
`find_prohibited_fields`, `sha256_digest`); five are reference
implementations, recorded as such in `tests/unit/safety/_support.py` rather
than blurred into the production claim.

Current result: **37/37 negative controls detected, 12/12 safe controls
accepted.**

> A 12/12 or 37/37 detection result is **software detector evidence**. It
> demonstrates that these detectors reject these unsafe states. It is not
> clinical validation and does not establish that the system is safe for any
> patient.

## 6. Enforcement and blocking behaviour

`pgx-safety check` exits:

| Exit | Meaning |
|---|---|
| `0` | every invariant `PASS`; no blocker; evidence written |
| `1` | at least one invariant `FAIL` or `ERROR` |
| `2` | `BLOCKED` - checks passed but a blocker stands |
| `3` | usage error |

`pgx-safety check --write` writes the report **always** and the execution
evidence **only on `PASS`**. On any other state it replaces the evidence
with an explicit invalidation record. A build that fails cannot inherit a
previous build's passing gate.

Evidence is fingerprinted over ten source trees
(`pgx/safety/freshness.py`). Editing safety code, the safety tests, the
negative fixtures, the domain, the engine, the reporting layer or the
schemas invalidates the evidence, so a stale `PASS` cannot be presented as
current. The environment fingerprint deliberately excludes hostname,
username and absolute paths.

## 7. Current gate state

| Measure | Value |
|---|---|
| Safety gate status | **`BLOCKED`** |
| Release may proceed | **`false`** |
| Invariants registered / executed | 12 / 12 |
| Execution states | 7 `PASS`, 5 `BLOCKED`, 0 `FAIL`, 0 `ERROR` |
| Negative controls detected | 37 / 37 |
| Safe controls accepted | 12 / 12 |
| False-reassurance violations | 0 over a corpus of 36 |
| Prohibited-claim surfaces enforced | 6 |
| Claim-scanner known gaps | 4 (see section 7.1) |
| Stale or missing test selectors | 0 |
| Unexplained skips | 0 |
| Tests executed under safety selectors | 1088 |
| Blockers | 11 |

### 7.1 A finding recorded rather than patched

While building the `SAFETY-INV-010` controls, four prohibited phrasings were
found that `scan_claim_text()` does **not** match:

| Language | Phrasing |
|---|---|
| tr | `Bu hasta icin SYNTHDRUG-2 kullanmanizi oneririz.` |
| en | `We recommend SYNTHDRUG-2 for this patient.` |
| en | `Start SYNTHDRUG-2 for this patient.` |
| tr | `Dozu 25 mg gunluk olarak azaltin.` |

These are recorded as `KNOWN_SCANNER_GAPS` in
`tests/fixtures/wp20/unsafe_text.py`, asserted by
`TestTheScannerHasKnownGaps`, published as `claim_scanner_known_gap_count`
in the gate status, and raised as the blocker
`SAFETY_CLAIM_SCANNER_KNOWN_GAPS` owned by the WP-00 claim registry
reviewers.

They were deliberately **not** patched. The claim registry is a reviewed
governance artifact; section 3.1 of `safety-contract.md` states that its
scope and limits are a documented, reviewed position. Adding clinical
phrasings to it on an implementer's judgement would be exactly the
unreviewed clinical claim the system exists to prevent. The honest action
was to measure the gap, publish it, and block the gate on it.

Note also what this shows about the scanner's own honest limits: the
paraphrase-evasion limitation already stated in section 3.1 of the contract
is not hypothetical. It is now quantified at four phrasings under this
control set, and the count will change as the control set grows.

## 8. What this registry does not establish

This is the section a reader should not skip.

- **No clinical validation.** `clinical_validation_performed` is `false` and
  is pinned to `false` in the gate schema.
- **No expert review.** `expert_review_performed` is `false` and pinned.
- **No validation metrics.** `validation_metrics_implemented` is `false` and
  pinned. WP-21 owns them; WP-21 has not started.
- **No human or scientific approval.** The claim boundary reads
  `DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW`.
  `P0_CLAIM_BOUNDARY.is_approved` remains `False`. Automated enforcement is
  not approval, and this document does not create any.
- **No holdout result.** There are zero holdout cases.
- **No PostgreSQL execution.** No server was reached, so the database half
  of the persistence and separation invariants did not execute.
- **No CI execution.** `.github/workflows/safety-gate.yml` is **configured,
  not executed**. No CI provider run has been observed by this repository.
- **No coverage measurement.** `coverage.py` is not installed in either
  environment; no coverage percentage is claimed anywhere.

**WP-20's code can be complete while the release safety gate remains
`BLOCKED`.** That is the present state, and it is the correct one.

## 9. Change control

Adding, removing or restating an invariant changes the safety contract, not
just this file. Any such change requires:

1. an update to `docs/risk-management/safety-contract.md` section 2;
2. an Architecture Decision Record under `docs/architecture/decisions/`
   (`architecture.md` section 23);
3. re-approval of `safety-contract.md` section 11.2 by the named reviewers;
4. a corresponding change to `pgx/safety/definitions.py`, its negative
   controls, and its tests - the registry validator will refuse a definition
   whose selectors or controls do not exist.

Lowering a verification floor, weakening an assertion, adding a blanket
skip, or converting a `BLOCKED` state into `PASS` without closing its
blocker is a safety defect in itself and is out of scope for any work
package.
