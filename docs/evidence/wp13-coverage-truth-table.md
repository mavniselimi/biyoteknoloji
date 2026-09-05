# WP-13 — the coverage truth tables

| Field | Value |
|---|---|
| Document ID | `DOC-EVID-013A` |
| Work package | WP-13 — Coverage Engine |
| Contract version | `pgx-coverage-engine/1` |
| Source | `pgx/engine/coverage.py`; printed by `pgx-coverage truth-table` |
| Tests | `tests/unit/engine/test_coverage_axis.py`, `tests/unit/engine/test_coverage_aggregation.py` |

---

## How to read these

Every table is read **top to bottom, first matching row wins**. The tables are
published as data — `AXIS_DECISION_TABLE`, `MEDICATION_DECISION_TABLE`,
`OVERALL_DECISION_TABLE` — so the engine, the CLI, the tests and this document
read the same tables rather than four descriptions of them. The tables below
were generated from those objects.

No status is compared with another. `CoverageStatus` has no ordering and must
never acquire one: nothing in these modules uses `max`, `min`, sorting or enum
declaration order to combine statuses, and a test asserts `max` and `min` do
not appear in them at all.

**Conflict precedence is a safety rule, not a severity rule.** When an
unresolved disagreement is present anywhere, the result says so and every other
status and reason survives alongside it. That is not `SOURCE_CONFLICT` being
"worse" than `PARTIAL`; it is the one fact that must not disappear into an
aggregate (`SAFETY-INV-008`).

**No row produces an attention level**, because this engine computes none.

A test asserts that every row in every table below is reachable — a documented
case nothing can produce is a description of a behaviour that does not exist.

---

## 1. Axis

One drug, one gene. The order of the first two rows is deliberate: a boundary
mismatch is checked before anything else because a mismatched pin makes every
later answer meaningless, and an unresolved conflict is checked before the
phenotype because a disagreement about an axis is a fact about the axis
whatever was observed.

| # | Case | When | Status | Reason codes |
|---|---|---|---|---|
| 1 | `boundary_mismatch` | the manifest, ruleset or dataset supplied are not the ones each other pins | `INSUFFICIENT` | `DATASET_RULESET_MISMATCH` |
| 2 | `unresolved_conflict` | an unresolved source conflict names this exact axis | `SOURCE_CONFLICT` | `VALIDATED_RULES_CONFLICT` |
| 3 | `phenotype_absent` | the profile says nothing about this gene, or was given an empty value for it | `INSUFFICIENT` | `PHENOTYPE_NOT_PROVIDED` |
| 4 | `phenotype_unusable` | a value was supplied and is indeterminate or not a phenotype | `UNSUPPORTED_PHENOTYPE` | `PHENOTYPE_NOT_SUPPORTED` |
| 5 | `no_declared_axis` | the manifest declares no supported axis for this exact gene/phenotype | `INSUFFICIENT` | `NO_VALIDATED_RULE_FOR_AXIS` |
| 6 | `rule_not_in_ruleset` | the declared rule is not a member of the supplied frozen ruleset, or its content hash disagrees | `INSUFFICIENT` | `DATASET_RULESET_MISMATCH` |
| 7 | `rule_does_not_cover_axis` | the member rule's condition does not match the observed phenotype exactly | `INSUFFICIENT` | `NO_VALIDATED_RULE_FOR_AXIS` |
| 8 | `evidence_unresolvable` | the supporting evidence cannot be resolved in the pinned build | `INSUFFICIENT` | `EVIDENCE_REFERENCE_MISSING` |
| 9 | `covered` | the exact axis is declared, a validated member rule covers the observed phenotype, and its evidence resolves | `FULL` | — |

Rows 3 and 4 stay separate: *nothing was supplied* and *what was supplied could
not be read* are different failures, and neither is *a rule looked and did not
apply*. Row 7 is decided by WP-12's `match_observation`; phenotype equality is
not reimplemented here.

---

## 2. Medication

| # | Case | When | Status | Reason codes |
|---|---|---|---|---|
| 1 | `drug_not_in_dataset` | the pinned canonical dataset does not contain the drug | `UNSUPPORTED_DRUG` | `DRUG_NOT_IN_CANONICAL_DATASET` |
| 2 | `drug_not_declared` | the drug is recognised but the coverage manifest declares no scope for it | `INSUFFICIENT` | `NO_VALIDATED_RULE_FOR_AXIS` |
| 3 | `any_conflict` | any axis carries an unresolved source conflict | `SOURCE_CONFLICT` | `VALIDATED_RULES_CONFLICT` |
| 4 | `all_axes_full` | every expected axis is FULL | `FULL` | — |
| 5 | `some_axes_full` | at least one axis is FULL and at least one is not | `PARTIAL` | `SOME_AXES_NOT_COVERED` |
| 6 | `all_unsupported_phenotype` | no axis is FULL and every failure is an unusable phenotype | `UNSUPPORTED_PHENOTYPE` | `PHENOTYPE_NOT_SUPPORTED` |
| 7 | `nothing_covered` | no axis is FULL and the failures are mixed | `INSUFFICIENT` | — |

- `drug_not_in_dataset` — no axis is fabricated for a drug the dataset does not have
- `drug_not_declared` — recognition is not coverage (architecture.md 6.2)
- `any_conflict` — every other axis status and reason is preserved alongside it
- `all_axes_full` — the only status that carries no reason
- `some_axes_full` — underlying axis reasons are preserved as well
- `all_unsupported_phenotype` — homogeneous failures keep their specific status
- `nothing_covered` — reasons come from the axes themselves

---

## 3. Overall

| # | Case | When | Status | Reason codes |
|---|---|---|---|---|
| 1 | `any_conflict` | any medication carries an unresolved source conflict | `SOURCE_CONFLICT` | `VALIDATED_RULES_CONFLICT` |
| 2 | `all_full` | every medication is FULL | `FULL` | — |
| 3 | `some_covered` | at least one medication is FULL or PARTIAL, and at least one is not FULL | `PARTIAL` | `SOME_AXES_NOT_COVERED` |
| 4 | `all_unsupported_drug` | nothing is covered and every drug is absent from the dataset | `UNSUPPORTED_DRUG` | `DRUG_NOT_IN_CANONICAL_DATASET` |
| 5 | `all_unsupported_phenotype` | nothing is covered and every failure is an unusable phenotype | `UNSUPPORTED_PHENOTYPE` | `PHENOTYPE_NOT_SUPPORTED` |
| 6 | `nothing_covered` | nothing is covered and the failures are mixed | `INSUFFICIENT` | — |

- `any_conflict` — conflict preservation, not severity: every other medication status and reason survives in the result
- `all_full` — the only status that carries no reason
- `some_covered` — underlying medication reasons are preserved
- `all_unsupported_drug` — homogeneous failures keep their specific status
- `all_unsupported_phenotype` — homogeneous failures keep their specific status
- `nothing_covered` — reasons come from the medications themselves

---

## 4. The couplings

Enforced in the dataclass, again in the published JSON Schema, and again by
property tests run over every reason code:

- `FULL` carries **no** reason code, at every level.
- Every non-`FULL` status carries **at least one** reason code, at every level.
- A `FULL` axis names a validated member rule, resolvable evidence, and the
  phenotype it evaluated.
- A `FULL` medication covers at least one axis.
- A `SOURCE_CONFLICT` axis names the conflict it preserves.
- `PARTIAL` carries `SOME_AXES_NOT_COVERED` *in addition to* the reasons the
  underlying axes or medications gave, never instead of them.
