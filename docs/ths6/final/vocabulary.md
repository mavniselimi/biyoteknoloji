# Vocabulary

Four enumerations and one deliberate omission.

## The omission: there is no truthy API

No `is_ok`, no `__bool__`, no `passed`, no `status` string a caller could
truth-test. Every one of those is a place where `IMPLEMENTED` quietly becomes
`PASS`.

The affirmative predicates that do exist are narrow, named for the exact
decision they may inform, and each is true for one or two values only. A unit
test asserts their absence across every module in the package by inspection,
because the failure mode is somebody adding a convenience helper months from
now.

## Evidence type — twelve values

| Value | Means | May support a claim |
|---|---|---|
| `REAL_EXECUTED` | a real operation ran and its result was recorded | **yes** |
| `REAL_OBSERVED` | a real system was watched behaving | **yes** |
| `IMPLEMENTATION_TEST` | a unit or integration test passed | no |
| `CONFIGURED_NOT_EXECUTED` | a workflow, image definition or policy exists; nothing ran it | no |
| `DOCUMENT_ONLY` | prose: a runbook, protocol, policy or contract | no |
| `TEST_ONLY_REHEARSAL` | machinery exercised against labelled fixtures | no |
| `HUMAN_PENDING` | blocked on a named person acting | no |
| `SCIENTIFIC_PENDING` | blocked on an approved source, curated rule or metric | no |
| `OPERATIONAL_PENDING` | blocked on a database, runtime, provider or host | no |
| `STALE` | true about inputs that have since changed | no |
| `INVALID` | fails its own schema, is a symlink, or holds credential-shaped content | no |
| `UNAVAILABLE` | named by a document, not present in the tree | no |

`IMPLEMENTATION_TEST` is the state most of this repository is in and the one
most likely to be misread. This project's test suite passing proves the
software does what its authors intended. It proves nothing about whether a
pharmacogenomic rule is correct, and no gate here lets a test count close a
scientific gate.

The three `*_PENDING` states are not defects. A missing approval is not a bug;
a stale artifact is. The registry keeps `is_pending` and `is_defective`
disjoint.

## Claim support — five values

`SUPPORTED` (the only sufficient value) · `PARTIALLY_SUPPORTED` ·
`UNSUPPORTED` · `NOT_EVALUATED` · `CONTRADICTED`

`PARTIALLY_SUPPORTED` is reported as its own value rather than rounded up: a
partially supported claim is one nobody may make.

`NOT_EVALUATED` is never a synonym for `UNSUPPORTED`. "We did not look" and
"we looked and found nothing" are different states with different fixes.

`CONTRADICTED` is the most serious value and the one an aggregate must never
average away: evidence exists and it says the opposite.

## Gate result — five values

`PASS` (the only affirmative) · `BLOCKED` · `FAIL` · `NOT_EVALUATED` ·
`STALE`

`BLOCKED` is an absence: a named precondition is missing. `FAIL` is a defect:
a condition was evaluated and came out wrong, or a source artifact is
unreadable. `FAIL` exits `1` and `BLOCKED` exits `2`, because a blocked gate
is the expected state of this programme and a failing one means something is
broken — a caller treating both as "not zero" would never notice the day a
checksum stopped matching.

## Ordering is disabled on all four

`PARTIALLY_SUPPORTED` is not "greater than" `UNSUPPORTED` on any scale that
exists. Comparison raises `TypeError`, because the first thing built on an
invented scale would be `support >= PARTIALLY_SUPPORTED`.

## Blocker codes

41 declared codes, each with an explanation. The set is closed: a code
invented at a call site is one no aggregator can enumerate and no document can
be searched for. Every blocker carries a `detail` and an `owner`, and both are
required at construction — an unowned blocker is one nobody clears.

## Findings versus blockers

A **finding** says a document, a count or an artifact is wrong, and carries an
owner and a resolution. A **blocker** says a condition is unmet, and carries
an owner. They are counted separately everywhere in this pack.

## Two phrases used consistently

**"Implemented is not operational."** WP-23's phrase, and it holds across the
whole pack: what software can do, what this deployment has composed, and what
has actually happened are three separate questions.

**"Pack integrity is not achievement."** Spelled once in the code as a
constant and emitted verbatim by every command that reports a pack result, so
no output can be quoted as though the first implied the second.
