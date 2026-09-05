# P0 Definition of Done — all fifteen items

**1 of 15 satisfied.**

## The count discrepancy

WP-25's own brief describes *"all 14 THS 6 Definition of Done items"*.
`architecture.md` §21 enumerates **fifteen** bullets.

This registry implements fifteen — `P0-DOD-001` through `P0-DOD-015` — and
emits the disagreement as a finding:

```
finding_code:      THS6_DOD_DECLARED_COUNT_MISMATCH
declared_count:    14   (WP-25 prose)
enumerated_count:  15   (architecture.md §21)
resolution:        evaluate all 15
owner:             architecture/document owner
blocking_effect:   visible, but permits no item to be ignored
```

Merging two bullets — folding "rollback works" into "independently versioned",
say — would have produced a registry matching the declared count and would
have made a requirement disappear from a document whose whole purpose is to
show that no requirement disappeared. A visible disagreement is cheaper than a
missing obligation. The schema pins `enumerated_count` to 15, so a future
document with fourteen items fails validation.

## The fifteen

| ID | Architecture bullet (verbatim) | Satisfied | Owner |
|---|---|---|---|
| P0-DOD-001 | One integrated web prototype runs the representative workflow. | no | platform owner |
| P0-DOD-002 | Assessment facts are deterministic for the same release and input. | no | release approver |
| P0-DOD-003 | Every finding has traceable evidence. | no | curation lead |
| P0-DOD-004 | Missing data is never shown as low/no risk; coverage is separate. | no | curation lead |
| P0-DOD-005 | Software, dataset, and ruleset are independently versioned and rollback works. | no | release approver |
| P0-DOD-006 | At least 50 serious validation cases exist, with a preference for 100+. | no | validation owner |
| P0-DOD-007 | An independent holdout set was not used for rule development. | no | validation owner |
| P0-DOD-008 | All safety invariants pass in CI. | no | platform owner |
| P0-DOD-009 | Blind-first expert review is completed under the approved protocol. | no | expert review chair |
| P0-DOD-010 | Experts use the representative workflow, not only static reports. | no | expert review chair |
| P0-DOD-011 | Benchmark metrics are release-specific. | no | validation owner |
| P0-DOD-012 | Audit records actor/time/input hash/version bundle/output hash. | no | platform owner |
| P0-DOD-013 | A staging prototype, health checks, and basic reliability report exist. | no | platform owner |
| P0-DOD-014 | Every THS 6 claim links to a concrete artifact or metric. | **yes** | WP-25 evidence owner |
| P0-DOD-015 | Core demo completes with network unavailable, LLM off, and every P1 feature off. | no | platform owner |

## Why several of these look closer than they are

**P0-DOD-003 and P0-DOD-004 hold vacuously today.** Zero reports means every
finding trivially has traceable evidence. The invariants are implemented and
proven over fixtures; they have never been exercised over governed content
because none exists. Vacuous truth is recorded as unsatisfied.

**P0-DOD-008 is half done.** Twelve invariants execute and pass locally. The
workflow file exists. No CI provider has ever run it, and WP-20's artifact
carries a field explaining that a workflow file is `CONFIGURED`, not
`EXECUTED`.

**P0-DOD-015 is half done in a way worth stating precisely.** The interface
does render offline, with the language model off, with every P1 surface absent
from the tree — all three environment conditions of the demo are met. What it
renders is an empty state, because there is no governed content behind it.
Half the bullet is about the environment and half is about producing a result;
the first half holds.

## P0-DOD-014 is the one WP-25 can discharge

It is satisfied because every registered claim names required evidence and no
identifier or path in the traceability matrix dangles — computed, not
asserted, and re-derived each time the registry is built.

Discharging it says nothing whatever about the other fourteen. It is the
bullet about the *pack*, and the pack is the only thing this work package was
able to build.
