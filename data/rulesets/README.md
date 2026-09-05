# Frozen ruleset artifacts

This directory is the **production registry root**. `FrozenRulesetRegistry()`
with no arguments looks here.

It contains **no frozen ruleset**, and it will not until real human scientific
approvals exist. That is the correct state, not an incomplete one.

## Why it is empty

A ruleset may be frozen only when every member rule is `VALIDATED`, and a rule
may be validated only when it descends from a genuinely `CURATED` curation
revision under a complete approval envelope signed by three separated people,
citing evidence inside an approved build, under an approved protocol.

None of those exist here:

| Gate | State |
|---|---|
| Curation protocol | `AWAITING_EXPERT_REVIEW` — no scientist has approved it |
| Evidence build | `QUARANTINED`, `NOT_PUBLICATION_ELIGIBLE` |
| Canonical dataset | `BUILDING` |
| Source policy | every entry `PENDING_REVIEW` |
| Curated interpretations | 0 |
| Rule approval envelopes | 0 |
| Role assignments | 0 — empty by design until WP-23 |

`wp11-real-gate-status.json` and `wp11-real-build-attempt.json` in this
directory report all of that with stable machine-readable codes, and name the
human role that can clear each one.

## What is here

| File | What it is |
|---|---|
| `wp11-real-gate-status.json` | whether real rules are possible today, and what blocks them |
| `wp11-real-build-attempt.json` | an honest attempt to build a real ruleset, and where it stopped |

## Where synthetic fixtures live

Under `tests/fixtures/wp11/`, which this directory does not reach. That
separation is deliberate: a test cannot make the production registry executable
by accident, and a synthetic ruleset can never be mistaken for an approved one.

Every synthetic artifact is marked `SYNTHETIC`, `TEST ONLY`,
`NOT CLINICAL DATA` and `NOT FOR REAL ASSESSMENT`.
