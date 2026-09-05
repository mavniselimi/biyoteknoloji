# WP-14 — safety invariants, and how each is enforced

| Field | Value |
|---|---|
| Document ID | `DOC-EVID-014B` |
| Work package | WP-14 — Deterministic PGx Assessment Engine Migration |
| Contract | `docs/risk-management/safety-contract.md` |
| Safety tests | `tests/safety/test_assessment_safety.py` |
| Boundary tests | `tests/unit/engine/test_wp14_boundaries.py` |
| Persistence tests | `tests/unit/infrastructure/test_assessment_persistence.py` |

---

## `SAFETY-INV-001` — missing data must not produce low or no-active attention

This is the invariant WP-14 exists to serve. `LEGACY-BUG-002` reported "we did
not look" as *"Düşük / uyarı yok"*, and every layer below is arranged so that
becomes unreachable.

Enforced in **five** places, and the count is the point — a single check is a
single edit away from not existing:

1. **In the aggregator.** `aggregate_attention` returns
   `NO_ACTIVE_ATTENTION` only when coverage is `FULL`; every other absence
   path returns `NOT_ASSESSED`.
2. **In the type.** `MedicationAssessment` refuses construction when
   `NO_ACTIVE_ATTENTION` accompanies non-`FULL` coverage, and when
   `NOT_ASSESSED` accompanies a finding.
3. **In the domain aggregate.** `Assessment` refuses the same combination at
   the overall level.
4. **In the published schema.** The same coupling as `if`/`then`, so a
   downstream reader enforces it without trusting this repository.
5. **In the database.** `ck_assessments_no_active_attention_requires_full_
   coverage` and its medication-row counterpart, plus
   `ck_assessments_full_coverage_is_not_unassessed` for the reverse.

Asserted as a **property**, not as examples: over every `CoverageStatus`, and
over every `CoverageReasonCode` paired with every non-`FULL` status. A new
reason code is held to the rule without anybody adding a case.

`NOT_ASSESSED` is additionally excluded from `ATTENTION_PRECEDENCE`, so absence
cannot be outranked into invisibility either — it is not in the comparison at
all.

## `SAFETY-INV-003` — only validated rules may execute

A finding requires an approval record in the frozen artifact evidencing that
*this exact content* was validated. Membership in a frozen ruleset and
validation are separate facts, and the engine reads the second rather than
inferring it from the first. A rule whose approval record is absent, or
evidences different content, is `ASSESSMENT_RULE_NOT_EXECUTABLE`.

No WP-14 module names `RuleStatus.DRAFT` or `RuleStatus.CURATED`, and nothing
loads a ruleset except through WP-11's frozen registry.

## `SAFETY-INV-004` — `RAPID` is not `ULTRARAPID`

Inherited, not re-implemented. The engine calls WP-12's `match_observation`; a
boundary test asserts no WP-14 module defines a phenotype alias table, a group
normaliser, a `phenotype_matches` function or a "closest phenotype" helper.
`RAPID` and `ULTRARAPID` each fail to reach the other's rule, and the legacy
comparison records that the old engine's group matching is what is being
corrected.

## `SAFETY-INV-005` — no candidate is preferred, ranked or scored

Enforced by absence. No WP-14 model, schema, database column or CLI command
contains `dose`, `dosage`, `recommend`, `preferred`, `safer`, `suitability`,
`treatment`, `alternative`, `rank`, `prescription` or a diagnosis field —
checked as identifiers, dataclass fields, schema properties, migration column
names and CLI commands.

The only numeric fields on a medication result are `axis_count`,
`finding_count` and `conflicted_axis_count`, and a test asserts no other bare
number appears there. Medications are sorted by canonical key; any other order
would be a ranking whether or not anybody meant it as one.

## `SAFETY-INV-006` — every finding carries traceable evidence

`CalculatedFinding` refuses construction without at least one evidence
reference. The engine additionally resolves each reference against the pinned
build and refuses the finding if any does not resolve. The database enforces it
a third time, as a **deferred** constraint trigger — deferred because a finding
and its evidence links are inserted in the same transaction, so the check is
meaningful at commit rather than at statement order. The link table's foreign
key is `ON DELETE RESTRICT`, so an evidence record a stored finding cites
cannot be deleted.

## `SAFETY-INV-007` — missing release metadata must fail persistence

`PinnedReleaseProvenance` holds nineteen fields — release, software, dataset,
ruleset, evidence build, coverage manifest, protocol and source policy, each by
identity and content hash, plus the active-pointer generation observed at pin
time. All of them are required to construct it.

`Assessment.require_complete_release_metadata()` is called by the repository
*before* the transaction opens, so an assessment missing a pinned version never
reaches a database that would have to reject it. Every corresponding column is
`NOT NULL`, and the release, software version, dataset version and ruleset
version are real foreign keys with `ON DELETE RESTRICT`.

The request cannot supply any of it: `AssessmentInput` has no version field,
and the only release-related thing a caller may set is *which* release.

## `SAFETY-INV-008` — a source conflict must not collapse into reassurance

A conflicted axis emits no finding and is never resolved: no lower level, no
higher level, no average, no rule order. The conflict status and every conflict
reference are preserved through to the top of the result, and the database
requires a `SOURCE_CONFLICT` axis row to name at least one conflict reference.

An independent covered axis keeps its finding, and the medication's attention
reflects only non-conflicted findings; if there are none it is `NOT_ASSESSED`.
A WP-13 conflict signal carries no governed outcome — a test asserts it has no
attention, level or outcome attribute — so there is nothing in it from which a
level could be manufactured.

---

## The determinism boundary

`architecture.md` 9.6 lists what may not influence a calculation. Each is
addressed:

| May not influence | How |
|---|---|
| wall-clock time | no engine module imports `datetime`; the service's clock is injected and excluded from the hash |
| unordered database iteration | every collection is sorted by an explicit key before hashing |
| active release changes after start | the pointer is read once; the running calculation holds a value the pointer cannot reach |
| LLM output | no model client is importable from any WP-14 module |
| UI display choices | no label, template or renderer exists here |
| external network calls | no network client is importable |
| non-versioned local CSV files | no WP-14 module imports `csv`; the legacy comparison scans the calculation path and reports 0 of 7 |

## What these tests do not establish

That the assessment semantics are the *right* semantics. They match
`architecture.md` 9.3 and this repository's safety contract; whether that is
what a pharmacogenomics expert would approve is a question for a reviewer, and
the curation protocol is still `AWAITING_EXPERT_REVIEW`. Every fixture in this
work package is synthetic, no real assessment has been executed, and no finding
has been persisted.
