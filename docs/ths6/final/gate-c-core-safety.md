# Gate C — Core Safety

**Result: BLOCKED.** 0 of 9 mandatory conditions met. 9 blockers.

`architecture.md` §20: *exact phenotype, coverage, deterministic
engine/report, safety suite pass.*

| # | Condition | Read from | Required | Observed |
|---|---|---|---|---|
| C1 | an assessment computed from governed content | `data/assessments/wp14-real-gate-status.json` → `assessment_state.real_completed_assessments` | ≥ 1 | 0 |
| C2 | a coverage manifest executed | `data/coverage/wp13-real-gate-status.json` → `coverage_state.real_coverage_executions` | ≥ 1 | 0 |
| C3 | at least one supported axis | same → `coverage_state.real_supported_axes` | ≥ 1 | 0 |
| C4 | at least one report produced | `data/reports/wp15-real-gate-status.json` → `real_report_count` | ≥ 1 | 0 |
| C5 | the safety gate reports PASS | `data/safety/wp20-real-gate-status.json` → `safety_gate_status` | `PASS` | `BLOCKED` |
| C6 | safety invariants executed by a CI provider | same → `ci_job_executed` | true | false |
| C7 | the claim boundary is approved | same → `claim_boundary_approved` | true | false |
| C8 | a release is active | same → `active_release_available` | true | false |
| C9 | the API has served a real assessment | `data/api/wp16-real-gate-status.json` → `real_api_assessment_count` | ≥ 1 | 0 |

## Blockers and owners

| Code | Owner |
|---|---|
| `THS6_NO_REAL_ASSESSMENT` (×3) | curation lead, platform owner |
| `THS6_NO_COVERAGE_EXECUTION` (×2) | curation lead |
| `THS6_SAFETY_GATE_BLOCKED` | safety owner |
| `THS6_SAFETY_CI_NOT_EXECUTED` | platform owner |
| `THS6_CLAIM_BOUNDARY_NOT_APPROVED` | clinical safety authority |
| `THS6_NO_ACTIVE_RELEASE` | release approver |

## The safety picture, stated precisely

Twelve safety invariants are registered and all twelve execute. Thirty-seven
negative controls are declared and all thirty-seven are detected. 1,165 tests
run with zero unexplained skips, and zero false-reassurance violations were
found across a 36-item corpus.

That is a good result **about software detectors**. WP-20's own artifact says
so in a field: `detector_evidence_disclaimer`. Detecting an unsafe negative
control proves this software rejects that unsafe state. It is not clinical
validation and no gate here treats it as such.

Two things are missing that no amount of local execution supplies:

- **C6.** `.github/workflows/safety-gate.yml` is configured and has never
  been run by a provider. A configured workflow is not a CI run, and WP-20's
  artifact carries its own note saying exactly that.
- **C7.** The claim boundary's status is
  `DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW`. Six prohibited claim
  surfaces are declared and the scanner has four known gaps. Until a named
  clinical safety authority approves the boundary, no outward statement about
  what this system may claim is authorised.

## What C1 and C4 actually mean

Zero assessments and zero reports means the properties C1 and C4 guard hold
*vacuously*. "Every finding has traceable evidence" is trivially true when
there are no findings. This pack records those as unsatisfied rather than met,
because a vacuous truth is not the property anybody wanted.
