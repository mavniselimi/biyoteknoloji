# WP-20 handoff

## State

The safety invariant suite is implemented.

`pgx/safety/` (11 modules plus `__init__`, framework-free), `pgx-safety`,
5 published schemas, 5 data artifacts, 4 documents, 37 negative controls,
12 safe controls, 211 new tests. For the first time the repository has one
authoritative, machine-readable, executable, release-blocking answer to the
question *which safety requirements exist and does the software enforce
them.*

```
pgx-safety registry            # the twelve invariants, as data
pgx-safety negative-controls   # the 37 mutants and their expected refusals
pgx-safety check               # execute; exit 0 / 1 / 2
pgx-safety check --write       # execute and record evidence, only if PASS
pgx-safety gate-status         # the blocking picture
pgx-safety artifacts           # regenerate the deterministic artifacts
```

Current result: **gate `BLOCKED`, release may not proceed, 7 `PASS`, 5
`BLOCKED`, 0 `FAIL`, 0 `ERROR`, 37/37 negative controls detected, 12/12 safe
controls accepted, 0 false-reassurance violations over a corpus of 36.**

## What the next work package inherits

### A green unit suite does not mean the safety gate passed

This is the single most important thing to carry forward. `python -m
unittest discover -s tests` can report zero failures while `pgx-safety
check` exits `2`. The gate is a separate execution with its own evidence,
its own exit codes and its own blockers, and it is designed so that ordinary
test success cannot be mistaken for safety.

If a future package wires the suite into a release pipeline, the suite is
not the gate. `pgx-safety check` is the gate.

### `BLOCKED` is not `FAIL`, and neither is `PASS`

Three distinct states, deliberately not collapsed:

- `PASS` - every check executed and succeeded, and nothing stands in the way.
- `FAIL` / `ERROR` - a detector broke, a mutant was missed, or a safe subject
  was wrongly refused. This is a software defect.
- `BLOCKED` - every check that could execute did, and succeeded, but
  something outside software's reach prevents the claim. A missing human
  approval, a missing holdout case, a database nobody started.

Five invariants are `BLOCKED` today with zero failed checks. Do not
"resolve" them by editing the definition. Each carries the owner who can
actually close it.

### Absence is asserted, not assumed

`SAFETY-INV-002` (LLM alters facts) and `SAFETY-INV-005` (candidate
preference) are recorded `NOT_PRESENT`: P0 ships no LLM renderer and no
candidate exploration, so there is nothing to constrain.

That claim can rot. Each carries `absence_markers` - identifiers whose
appearance in the shipped package means the surface has arrived. **The
registry refuses to build when a marker is found.** It does not quietly
downgrade the invariant to `UNKNOWN`.

So: the day P1-06 adds a narration renderer, or P1-02 adds candidate
exploration, `pgx-safety registry` will start failing. That failure is the
system working. The correct response is to move the invariant to
`COMPLIANT` (or `VIOLATED`) with real enforcement behind it, not to delete
the marker.

### The mutant goes through the real detector

Every evaluator in `pgx/safety/evaluators.py` takes its subject as an
argument, so the shipped implementation and the mutant are passed to the
same function. If a future package adds a negative control, it must follow
this shape. A test that asserts "the unsafe fixture contains unsafe text"
proves nothing about the detector and must not be counted as a control.

A control is satisfied only when the evaluator refuses **and** the refusal
code matches the one the catalogue declared in advance. Refused for the
wrong reason is not satisfied.

### The shipped package must not import the tests

`pgx/safety` never imports `tests.*` at module import time. The negative
control driver is loaded lazily by name
(`CONTROL_DRIVER_MODULE = "tests.fixtures.wp20.driver"`), so a wheel built
without the test tree reports `NOT_EXECUTED` rather than silently passing
with zero controls. `tests/unit/safety/test_boundaries.py` enforces this.

This bit was broken once during implementation (a top-level import of
`tests.fixtures.wp20.unsafe_text` inside `report.py`) and the boundary test
caught it. Keep the test.

### Evidence expires

`data/safety/wp20-safety-execution.json` is fingerprinted over ten source
trees: the safety package, the safety unit tests, the safety suite, the
negative fixtures, the domain, the engine, the reporting layer, the
validation layer, the schemas and the artifacts. Touch any of them and the
evidence is stale.

`check --write` writes the report **always** and the execution evidence
**only on `PASS`**; on any other state it writes an explicit invalidation
record over the evidence. A failing build cannot inherit a previous build's
passing gate. Do not add a code path that writes evidence unconditionally.

The environment fingerprint deliberately excludes hostname, username and
absolute paths. Do not add them - evidence bound to one machine is evidence
nobody else can reproduce.

## What WP-21 must not inherit from here

**WP-20 detects unsafe software states. It validates nothing clinically.**

`37/37 negative controls detected` is a statement about detectors. It is not
a sensitivity, not a specificity, not a false-negative rate, and not a
clinical result. The disclaimer is stored in the artifacts themselves
(`detector_evidence_disclaimer`), not only in prose, so it travels with the
data.

`validation_metrics_implemented` is `false` and is **pinned** to `false`
with `{"const": false}` in `schemas/wp20/wp20-gate-status.schema.json`. When
WP-21 implements metrics, that schema and that field change together, in the
open. Do not flip it from outside WP-21.

The same pinning applies to `clinical_validation_performed` and
`expert_review_performed`. Those belong to human beings under WP-21 and
WP-22 respectively, and no amount of test execution produces them.

Note also: `SAFETY-INV-009` is `BLOCKED` because there are **zero holdout
cases**. The separation mechanism is enforced and proven; there is nothing
to separate. WP-21 will need to notice that a metric computed over a zero
denominator is not a good result, and `SAFETY-INV-009`'s controls include
that case for exactly this reason.

## What WP-22 will need

The claim scanner has four documented, unpatched gaps
(`KNOWN_SCANNER_GAPS` in `tests/fixtures/wp20/unsafe_text.py`,
`claim_scanner_known_gap_count` in the gate status, blocker
`SAFETY_CLAIM_SCANNER_KNOWN_GAPS`):

| Gap ID | Phrasing |
|---|---|
| `tr/first-person-recommendation` | `Bu hasta icin SYNTHDRUG-2 kullanmanizi oneririz.` |
| `en/first-person-recommendation` | `We recommend SYNTHDRUG-2 for this patient.` |
| `en/imperative-medication-change` | `Start SYNTHDRUG-2 for this patient.` |
| `tr/dosing-imperative` | `Dozu 25 mg gunluk olarak azaltin.` |

WP-20 deliberately did **not** patch them. The claim registry is a reviewed
governance artifact and its stated limits are themselves a reviewed
position; adding clinical phrasings on an implementer's judgement would be
the unreviewed clinical claim this system exists to prevent.

Whoever closes these must go through the WP-00 claim registry reviewers, and
must update `KNOWN_SCANNER_GAPS` in the same change -
`TestTheScannerHasKnownGaps` fails if a gap is silently fixed without the
record being updated. That is intentional: the count is evidence, and
evidence that drifts from reality is worse than no evidence.

Four is a **lower bound** on the scanner's blind spots under this control
set, never an upper bound.

## What WP-23 will need

Two invariants have a real dependency on the append-only audit record:

- `SAFETY-INV-007` - the release bundle and both hashes are enforced now;
  actor, role, session and correlation identity are not.
- `SAFETY-INV-012` - determinism of the calculated result is enforced now;
  audit completeness is not. `SAFETY-INV-012` is the only invariant with a
  published `surface_gap` (`PERSISTENCE_BOUNDARY`), and it is published
  rather than hidden precisely so this handoff does not have to be believed
  on trust.

Both are `BLOCKED`, not `PASS`. Reporting them as satisfied today would be
false.

## What WP-24 will need, and what it must not do

`.github/workflows/safety-gate.yml` exists. It is **configured, not
executed**. `ci_job_configured: true` and `ci_job_executed: false` are
separate fields for that reason, and `ci_job_execution_note` states it in
prose inside the artifact.

No CI provider run has ever been observed by this repository. `WP-24` must
not set `ci_job_executed: true` because a workflow file exists - it may set
it when a provider run is actually recorded, and not before.

The workflow contains no `pip install` and no deploy step. It runs the
safety gate, branches on the exit code, and uploads the report. Adding a
network install would make the gate depend on an index that may be
unreachable, which converts a safety failure into an infrastructure failure.
`tests/unit/safety/test_artifacts.py` asserts the absence of those
directives against non-comment lines only (an earlier version of the test
matched its own comments).

## Things to be careful with

**Substring searches over this repository match the module's own prose.**
This was hit roughly ten times during WP-19 and WP-20. Searching for
`pip install` in the workflow test found the comment explaining why there is
no `pip install`. Read AST identifiers, strip comments, or qualify by module.

**`aggregate_attention` refuses `NOT_ASSESSED` rather than returning a safe
value.** It raises `AssessmentEngineError`. The false-reassurance sweep
counts that refusal toward the corpus and *not* toward the violations,
because a refusal is the invariant holding in its strongest form. Anyone
rewriting that sweep should preserve the distinction; treating the exception
as a violation would report a defect where the strictest possible behaviour
exists.

**`_SafetyEnum` disables ordering.** `__lt__` raises `TypeError`, following
the domain convention. Sorting a list of severities or states will raise -
sort by `.value` if you need a stable order.

**Seven of twelve safe controls are production callables, five are
reference implementations.** `SUBJECT_KIND` in
`tests/unit/safety/_support.py` records which is which. Do not describe a
reference-subject acceptance as evidence about shipped code.

**Do not run the full suite casually.** It takes roughly five minutes and
5,900+ tests. Use the safety selectors during development:
`python -m unittest discover -s tests/unit/safety -p 'test_*.py' -t .`

## What changed outside `pgx/safety/`

### Two WP-19 mapping defects, corrected

`pgx/verification/requirements.py::SAFETY_INVARIANT_MAP` was rewritten from
10 entries to 12. Two existing entries were **wrong**, not merely
incomplete:

- `SAFETY-INV-008` was mapped to injection and claim-scanner tests. Those
  are `SAFETY-INV-010`'s subject. `SAFETY-INV-008` is source/rule conflict
  collapse.
- `SAFETY-INV-010` was mapped to snapshot and hashing tests. Those belong to
  `SAFETY-INV-012` (determinism and auditability).

Both corrections carry in-file comments explaining what was wrong and why,
so the next reader does not re-derive it.

### The WP-19 blocker was replaced, not deleted

`VERIFICATION_SAFETY_GATE_OWNED_BY_WP20` is gone, replaced by
`VERIFICATION_SAFETY_GATE_NOT_PASSING`. WP-19's gate status now reads WP-20's
committed safety gate status through `_safety_gate_state(root)`, which
reports `ABSENT` when the file is missing and never infers a state.

WP-19 stops blocking on "WP-20 does not exist" and starts blocking on "the
safety gate is not passing", which is the truthful successor condition.

### `safety_invariant_map_only` flipped in the open

WP-19 pinned `safety_invariant_map_only: true` with `const` in its schema
and its handoff said explicitly: *when WP-20 builds the real registry, that
field and that schema change together, in the open.* That is what happened.
`pgx/application/verification_schema.py` now types it `{"type": "boolean"}`
and the value is `false`, alongside four new fields carrying the safety gate
state into the verification artifact.

### The safety contract was not modified, and that was a decision

`docs/risk-management/safety-contract.md` is one of the 64 frozen WP-00
artifacts pinned by SHA-256 in `data/legacy-baseline/manifest.json`.
`scripts/amend_legacy_manifest.py` refuses to amend those entries at all,
by design.

An edit adding the WP-20 enforcement table to that document was written and
then reverted. Keeping it would have required defeating a preservation
guarantee to make the suite green - the exact act this work package exists
to make impossible. The file's bytes are unchanged and its hash still
matches the manifest.

The material lives in `docs/risk-management/wp20-invariant-registry.md`
section 1.1 instead, which explains the boundary and what folding it into
`DOC-SC-001` would require: the WP-00 reviewers plus a baseline
re-collection under `architecture.md` section 23.

If a later package wants the contract to carry this, that is the route.
Amending the frozen manifest from an implementer's seat is not.

### Other touched files

- `pgx/verification/inventory.py` - 5 `CategoryRules` for the WP-20 test
  trees. The inventory *refused* the new modules first, which is the
  fail-closed behaviour WP-19 documented working as designed.
- `pgx/verification/requirements.py` - `VER-REQ-021` added (21 total).
- `pgx/verification/profiles.py` - `SAFETY_INVARIANT_MODULES` (45 modules)
  and a `safety` profile with a floor of 300 tests.
- `pyproject.toml` - `pgx-safety` console script.

## Blocked, and none of it by code

Eleven blockers stand. None can be closed by writing software in any work
package:

| Blocker | Who closes it |
|---|---|
| `SAFETY_CLAIM_BOUNDARY_NOT_APPROVED` | named human and scientific reviewers |
| `SAFETY_CLAIM_SCANNER_KNOWN_GAPS` | WP-00 claim registry reviewers |
| `SAFETY_NO_ACTIVE_RELEASE` | WP-03 operation |
| `SAFETY_NO_HOLDOUT_CASES` | scientific curators |
| `SAFETY_POSTGRESQL_NOT_EXERCISED` | deployment |
| `SAFETY_CI_JOB_NOT_EXECUTED` | WP-24 / a CI provider |
| `SAFETY_INVARIANT_BLOCKED_BY_LATER_WP` ×5 | P1-02, P1-06, WP-21, WP-23, WP-24 |

**WP-20's code is complete and the release safety gate is `BLOCKED`.** Both
are true. The second governs release.

## Not started

WP-21, WP-22, WP-23 and WP-24 are not started. No marker for any of them
exists in this repository, and `wp21_started` through `wp24_started` are all
`false` with empty marker lists in the gate status - measured, not asserted.
