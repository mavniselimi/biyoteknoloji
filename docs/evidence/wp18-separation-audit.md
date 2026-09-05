# WP-18 — Separation audit evidence

## What exists, counted

| | Count |
| --- | --- |
| Development cases | **7** |
| Internal holdout cases | **0** |
| Expert holdout cases | **0** |
| Holdout total | **0** |
| Real-patient cases | **0** — structurally, see below |
| P0 target | 50 |
| Shortfall | **50** |

The seven are the WP-17 catalogue: `PGX-VAL-DEV-P1` … `PGX-VAL-DEV-P6` and
`PGX-VAL-DEV-INSUFFICIENT`. Every one is `DEVELOPMENT`,
`is_validation_evidence: false`, `is_holdout: false`.

**There are no validation cases.** The P0 Definition of Done asks for at least
50 serious ones, preferably 100 or more, and this repository has none. That gap
is reported as a blocker (`VALIDATION_BELOW_P0_CASE_TARGET`) and is not
closable by code: authoring a holdout case needs a source, a derivation a
reviewer can follow, and — for an expert holdout — a named expert working it
blind. Generating one would be the fabrication this architecture exists to
prevent.

## Audit result

`data/validation/wp18-separation-audit.json`:

```
is_clean:                 true
checked_case_count:       7
development_count:        7
internal_holdout_count:   0
expert_holdout_count:     0
issue_count:              0
```

Clean over a set with nothing to separate is a weak result and is stated as
such. What the audit demonstrates in this repository is that the seven
development cases do not duplicate each other, do not split a derivation family
and do not conflict on release compatibility. Its ability to catch a
cross-partition leak is demonstrated by tests rather than by data — each of the
eight rules has a case set that is wrong in exactly that one way.

## The rules, and that each is separately exercised

| Rule | Test |
| --- | --- |
| `ROLE_OVERLAP` | `test_one_identifier_in_two_roles_is_refused` |
| `CONTENT_DUPLICATE_ACROSS_PARTITIONS` | `test_the_same_content_across_partitions_is_refused` |
| `CONTENT_DUPLICATE_WITHIN_PARTITION` | `test_the_same_content_within_one_partition_is_refused` |
| `DERIVATION_FAMILY_SPLIT` | `test_neither_content_nor_identifier_would_have_caught_it` |
| `HOLDOUT_DERIVED_FROM_DEVELOPMENT` | `test_a_holdout_derived_from_development_cannot_be_built` |
| `DEVELOPMENT_RELABELLED_AS_HOLDOUT` | `test_development_becoming_holdout_is_refused` |
| `HOLDOUT_PROVENANCE_MISSING` | `test_a_holdout_without_provenance_cannot_be_built` |
| `RELEASE_COMPATIBILITY_CONFLICT` | `test_two_pinned_and_different_rulesets_conflict` |

Plus the opposite direction, which matters more: `test_two_similar_but_distinct_cases_are_not_reported`,
`test_silence_is_not_a_conflict`, `test_one_family_inside_one_partition_is_fine`
and `test_an_unchanged_role_is_not_reported` assert that legitimate work is not
refused. A check that refused everything would also pass the first table.

## No validation percentage exists

None. No rate, no ratio, no denominator appears in any WP-18 module or
artifact, and a boundary test fails the build if a quotient is computed
anywhere in `pgx/validation`.

The reason is arithmetic before it is policy: with zero holdout cases, every
rate over this dataset has a zero denominator, and a zero-denominator rate is
not a number. WP-21 owns metrics and cannot start honestly until there is
something to count.

## Real-patient count: structurally zero

`real_patient_case_count: 0`, with the source recorded as *structurally zero*
rather than *counted*. The case model refuses every real-patient, genotype and
raw-sequencing field at any nesting depth, in metadata and in payloads, so
there is no path by which such a case could exist to be counted. Real-patient
ingestion is P2-03/P2-04 and is not implemented.

## What was executed

All WP-18 suites run without a framework, a database, a network or a browser.

| Suite | Tests |
| --- | --- |
| `tests/unit/validation/test_cases.py` | 32 |
| `tests/unit/validation/test_fingerprint.py` | 27 |
| `tests/unit/validation/test_separation.py` | 28 |
| `tests/unit/validation/test_access.py` | 26 |
| `tests/unit/validation/test_restricted_import.py` | 25 |
| `tests/unit/validation/test_manifests_and_catalog.py` | 20 |
| `tests/unit/validation/test_artifacts.py` | 26 |
| `tests/unit/validation/test_wp18_boundaries.py` | 17 |
| `tests/failure/test_wp18_partition_violations.py` | 17 |
| `tests/integration/validation/test_wp18_flow.py` | 5 |

The restricted-import tests drive a real temporary filesystem, including
traversal, symlink escape, oversize refusal and atomicity. A fail-closed
boundary that has never been made to fail is not known to be fail-closed.

## Blockers, none of which WP-18 can clear

| Code | Owner |
| --- | --- |
| `VALIDATION_NO_HOLDOUT_CASES` | scientific curators |
| `VALIDATION_BELOW_P0_CASE_TARGET` | scientific curators |
| `VALIDATION_RESTRICTED_STORAGE_NOT_CONFIGURED` | deployment |
| `VALIDATION_NO_ACTIVE_RELEASE` | WP-03 operation once artifacts exist |
| `VALIDATION_CLAIM_BOUNDARY_NOT_APPROVED` | named human and scientific reviewers |
| `VALIDATION_METRICS_NOT_IMPLEMENTED` | WP-21 |
| `VALIDATION_EXPERT_REVIEW_NOT_IMPLEMENTED` | WP-22 and named experts |

**Gate D remains open.** It needs independent holdout results, metrics and
blind expert review; WP-18 supplies the architecture for the first and none of
the other two. No independent validation, no expert agreement and no clinical
performance is claimed anywhere in this work package.
