# WP-18 handoff

## State

The validation dataset architecture is implemented. The dataset is not, and
cannot be by code.

`pgx/validation/` (11 modules, framework-free), 5 published schemas, 4 data
artifacts, 5 documents, 223 new tests. Seven development cases, **zero holdout
cases**, and a gate status that says so in those words.

```
python -m pgx.application.validation_cli artifacts     # regenerate
python -m pgx.application.validation_cli audit         # run the separation rules
python -m pgx.application.validation_cli gate-status   # what can be said
```

## What the next work package inherits

### The partition is structural

Three roles, immutable per case. A holdout cannot be constructed
author-visible, cannot declare a development source, and cannot omit
provenance — those are constructor refusals, not audit findings. The audit
catches the six faults a constructor cannot see, reads no payload while doing
it, and reports every problem at once.

**Do not add a fourth role without deciding which side of the line it is on.**
`HOLDOUT_ROLES` is named rather than written as `!= DEVELOPMENT` at each call
site, so a new member has to be classified deliberately.

### A case has no expected result, anywhere

Not in the metadata, not in the payload, not in the schemas — and the schemas
*refuse* the field rather than merely not listing it, so a document carrying
one fails validation. WP-22 records what an expert concluded, under its
protocol, with a named human. That is a different thing from a field on a case,
and putting it here would invite an AI-authored answer.

### The access ledger is evidence, not permission

It records a caller's claim about itself. `actor_authenticated` is `false` in
every event and pinned by `const` in the published schema. **WP-23 must not
flip that field without changing the schema in the open**, because an audit
trail that started recording unverified names as verified would be worse than
one that recorded nothing.

### The import boundary is ready and unused

Nothing has passed through it. WP-22 supplies a storage root and a payload; the
boundary computes its own hashes, refuses traversal and symlinks after
resolution, writes atomically, and preserves the previous state on every
refusal. Issue codes are coarse on purpose — the exceptions underneath quote
paths, and a path is one of the things this boundary exists not to disclose.

## Blocked, and none of it by code

| Blocker | Owner |
| --- | --- |
| Zero holdout cases; P0 wants ≥ 50 | scientific curators |
| No restricted storage configured | deployment (`PGX_VALIDATION_RESTRICTED_ROOT`) |
| No active release to resolve compatibility against | WP-03 operation |
| Claim boundary DRAFT | named human and scientific reviewers |
| No metric | WP-21 |
| No expert review | WP-22 and named experts |
| **Gate D** | all of the above |

## What WP-21 will need, and must not do

It reads `is_validation_evidence` rather than re-deciding it, and it must never
compute a rate that mixes partitions or hides a zero denominator. Today every
denominator is zero, so **there is no honest metric to compute yet** — the
first useful thing WP-21 can do is refuse to report one.

`audit_partition` should run before any metric, and a non-clean audit should
stop the report rather than annotate it.

## What WP-22 will need

The import boundary, the expert-holdout role, and the release path for a payload
— which is the one thing WP-18 deliberately did not build, because releasing a
holdout to a reviewer is a protocol decision with a named human in it.

`decide_access` refuses every expert-holdout payload read today, including to
an expert. WP-22 widens that, and the widening should be visible in one place.

## Things to be careful with

**The seven development cases are a view, not a copy.**
`pgx/validation/catalog.py` reads `data/demo/wp17-development-cases.json` and
never writes. Copying them would create a second file that can drift, and drift
between "the demo catalogue" and "the validation catalogue" is exactly the
ambiguity a partition cannot afford.

**Fingerprint normalisation is asymmetric on purpose.** Removing a difference
that carries no meaning is safe; removing one that does hides a case. That is
why `ORDER_INSENSITIVE_FIELDS` names three fields instead of sorting every
list. Adding a fourth is a decision, not a tidy-up.

**Null is not zero.** `restricted_payload_count`, `validation_metric_count`
and `expert_reviewed_case_count` are `null` because nobody looked. Rendering
them as `0` would turn "we did not look" into "we looked and found none".

**One web file changed.** `apps/web/gate_status.py`'s WP-18 blocker text said
the architecture was not implemented, which stopped being true. `wp18_started`
was already measured from the filesystem and flipped on its own. No `apps/api`
file changed, so the WP-16 runtime-verification evidence is unaffected.

## Not started

WP-19, WP-20, WP-21, WP-22, WP-23, WP-24, WP-25. Measured from the filesystem
in the gate status (`wp19_started`, `wp21_started`, `wp22_started`), not
asserted.
