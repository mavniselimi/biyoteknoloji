# WP-13 — safety invariants, and how each is enforced

| Field | Value |
|---|---|
| Document ID | `DOC-EVID-013B` |
| Work package | WP-13 — Coverage Engine |
| Contract | `docs/risk-management/safety-contract.md` |
| Property tests | `tests/safety/test_coverage_safety.py` |
| Boundary tests | `tests/unit/engine/test_wp13_boundaries.py` |

---

## How these are tested

`tests/safety/test_coverage_safety.py` does not check examples. It builds a
coverage result exhibiting **each of the eight reason codes**, each reached by
a different real path through the engine, and then asserts the same invariants
across all of them. A test that checked one insufficient case would prove that
one case was written correctly; these hold a new code — or a new path to an old
one — to the same rules without anybody remembering to add a test.

A separate test asserts the eight codes are exactly the eight the domain
declares: a published code no path can emit is a promise the system does not
keep, and a path with no code is an absence nobody can act on.

---

## SAFETY-INV-001 — missing data is never reported as low or absent concern

This is the invariant WP-13 exists to serve. The legacy engine reported "we did
not look" as *"Düşük / uyarı yok"* (`LEGACY-BUG-002`), and coverage is a
separate first-class output precisely so that absence cannot be reported as
reassurance.

Enforced in four places:

1. **In the type.** `AxisCoverage`, `MedicationCoverage` and `CoverageResult`
   all refuse construction when a non-`FULL` status carries no reason code, and
   refuse a `FULL` status carrying one. A future caller assembling a result by
   hand meets the same rule as the engine.
2. **In the engine.** Every row of every decision table but the covered one
   carries at least one reason; the tables are checked against the enum.
3. **In the published schema.** The same coupling, as `if`/`then`/`else`, so a
   downstream reader enforces it without trusting this repository.
4. **By property test.** Over every reason code, at every level of every
   result.

Also asserted: no unusable input ever becomes `FULL`. `""`, `"unknown"`,
`"n/a"`, `"-"`, `"0"` and `"poor metabolizer"` each produce a non-`FULL` status
with a reason — there is no fallback to `NORMAL`, which is false reassurance in
its purest form.

## SAFETY-INV-003 — only validated rules may support a claim

Membership in a frozen ruleset and validation are separate facts. The frozen
artifact carries an approval record per member rule, naming who validated it
and **what content** was validated; both the manifest builder and the validator
read those records rather than inferring validation from membership.

- The builder refuses an axis whose rule has no approval record, or whose
  approval evidences different content
  (`COVERAGE_MANIFEST_RULE_NOT_VALIDATED`).
- The validator reports the same as `COVERAGE_AXIS_RULE_NOT_VALIDATED`.
- No WP-13 module mentions `RuleStatus.DRAFT` or `RuleStatus.CURATED`.

## SAFETY-INV-004 — `RAPID` is not `ULTRARAPID`

Inherited, not re-implemented. Axis matching calls WP-12's
`match_observation`; a second equality rule would be a second place for the two
to start meaning each other. A test asserts that neither `RAPID` nor
`ULTRARAPID` reaches a rule declared for the other, and a boundary test asserts
no WP-13 module defines a phenotype alias table, a phenotype group table, or a
"closest phenotype" function.

## SAFETY-INV-005 — no candidate is preferred, ranked or scored

`LEGACY-BUG-009` in its general form: a 0–100 number beside a drug name reads
as suitability however it is labelled.

- No WP-13 model, schema or module contains `attention`, `overall_attention`,
  `risk`, `risk_level`, `risk_score`, `severity`, `dose`, `recommendation`,
  `preferred`, `safer`, `suitability_score`, `treatment`, `score`, `rank`,
  `priority` or `confidence` — checked as identifiers, dataclass fields, schema
  properties and JSON keys at any depth.
- The only numeric field on a medication is `axis_count`, and a test asserts
  no other bare number appears there.
- Medications in a result are sorted by canonical key. Any other order is a
  ranking whether or not anybody meant it as one.
- The one exemption is a name prefixed `legacy_`, which quotes the old
  engine's own field in the migration comparison — bounded to the legacy module
  and its report schema, and asserted to appear nowhere else.

## SAFETY-INV-006 — a claim names evidence that resolves

A `FULL` axis names a validated rule **and** resolvable evidence **and** the
phenotype it evaluated; the dataclass refuses all three omissions
(`COVERAGE_FULL_WITHOUT_RULE`, `COVERAGE_FULL_WITHOUT_EVIDENCE`,
`COVERAGE_FULL_WITHOUT_PHENOTYPE`). Evidence that does not resolve — wholly or
partly — makes the axis `INSUFFICIENT` with `EVIDENCE_REFERENCE_MISSING`, and
the axis still names the rule it could not support.

The manifest validator treats a **missing evidence resolver** as a failure
(`COVERAGE_EVIDENCE_RESOLVER_MISSING`) rather than a pass. An unperformed check
is not a check, and a manifest accepted because a check was skipped would be a
claim nobody verified wearing the appearance of one that was.

## SAFETY-INV-008 — a source conflict is never reassurance

`SourceConflictSignal` carries a `resolved` field that must be `False`; a
resolved conflict is not a conflict, and accepting one would let a caller
settle a disagreement by passing a flag rather than by adjudicating it. A
conflict names at least two rules, because one rule disagrees with nothing.

Asserted behaviour:

- A conflicting axis reaches the top of the result, through every level.
- It carries the conflict's identifier, and every rule and evidence reference
  from **every** side. No side is dropped and none is chosen.
- A conflict beats an otherwise `FULL` axis — which is where the loss would
  happen if it happened.
- A conflict survives an input nobody supplied: the disagreement is about the
  axis, not about the input.
- Every other medication's status and reasons survive alongside it, which is
  what distinguishes preserving a fact from ranking a status.

---

## The attention separation contract

WP-13 computes coverage; WP-14 computes attention. A document that could carry
both would let one be read as the other, so no WP-13 model or schema has a
field an attention level could be written into. This is enforced by absence and
asserted four ways: identifiers, dataclass fields, schema properties (every
schema is `additionalProperties: false` at every level), and the CLI's command
list.

The only permitted mention of attention is documentation saying WP-13 does not
calculate it. A boundary test reads every line of every WP-13 module that
contains the word and requires a denial in its immediate context.

## What the tests do not establish

That the coverage semantics are the *right* semantics. They match
`architecture.md` 9.2 and this repository's safety contract; whether that is
what a pharmacogenomics expert would declare is a question for a reviewer, and
the curation protocol is still `AWAITING_EXPERT_REVIEW`. Every fixture in this
work package is synthetic, and no approved coverage manifest exists.
