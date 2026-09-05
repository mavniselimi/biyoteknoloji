# WP-12 — the exact phenotype engine

| Field | Value |
|---|---|
| Document ID | `DOC-ARCH-012` |
| Work package | WP-12 — Exact Phenotype Engine Migration |
| Depends on | WP-07 gene normalisation, WP-11 rule conditions, the P0 phenotype model |
| Hands to | WP-13 coverage, WP-14 assessment. WP-12 computes neither |

---

## 1. One question

*Does this normalised phenotype satisfy this WP-11 phenotype condition?*

That is the entire scope. The engine answers it, records what it compared, and
stops. It does not decide whether a rule applies overall, which drug is being
assessed, how much attention anything warrants, or whether an axis is covered.

## 2. The package

| Module | What it holds |
|---|---|
| `pgx/engine/phenotype_normalization.py` | the input boundary, `pgx-phenotype-input/1` |
| `pgx/engine/phenotype_models.py` | observation, profile, decision, and their vocabularies |
| `pgx/engine/phenotype.py` | the exact matcher, `pgx-phenotype-matcher/1` |
| `pgx/engine/phenotype_legacy.py` | the legacy comparison and the difference allowlist |
| `pgx/engine/phenotype_errors.py` | three failure types, each with a stable code |

`pgx/engine` is stdlib-only. It imports `pgx.domain`, `pgx.rules` and
`pgx.normalization` — all layers beneath it — and nothing else: no
infrastructure, no framework, no network client, no clock, no `re`, no `csv`,
and not the legacy script. `pgx/application` holds the CLI and the schema
loader.

## 3. The input boundary

Version 1 accepts transport-level formatting and nothing else: trim, case-fold,
exact canonical token. `"POOR"`, `"poor"` and `" Poor "` all name `POOR`.

Everything else is refused with a reason code, including values that are
obviously mappable: `PM`, `poor metabolizer`, `zayıf`, `decreased_function`,
`*1/*2`, an activity score, a sentence. Mapping any of them is a scientific
claim about what a source meant, and version 1 makes none. A reviewed
vocabulary can be `pgx-phenotype-input/2`.

There is no substring test, no prefix test, no edit distance, no regular
expression over content, no similarity, no "closest" phenotype, no numeric
coercion — and no fallback to `NORMAL`. The last one is the point: falling
back to normal is false reassurance in its purest form.

A gene key is whatever WP-07's normaliser would allocate for its symbol. WP-07
is imported rather than re-described, so a second copy of the grammar cannot
drift from the first.

## 4. Four outcomes, not two

| Status | Means |
|---|---|
| `NORMALIZED` | a canonical token; carries a phenotype |
| `MISSING` | nothing was supplied |
| `INDETERMINATE` | it was recorded that no determination could be made |
| `UNSUPPORTED` | something was supplied and it is not a phenotype |

`INDETERMINATE` is a status rather than a phenotype value, so it can never be
handed to the matcher as something to compare. A failed observation carries a
reason code and no phenotype; a successful one carries a phenotype and no
reason code. Both couplings are enforced in the model and again in the
published schema.

## 5. Exact matching

`EXACT` is satisfied by equality with its single declared value. `ONE_OF` is
satisfied by membership in its explicitly listed set. The two branches perform
the *same* comparison — membership in a declared tuple — because WP-11 has
already enforced how many values each operator may declare. No cross-match can
hide in a difference between them, because there is no difference.

`RAPID` and `ULTRARAPID` match each other only when a `ONE_OF` names both
(`SAFETY-INV-004`). There is no default arm, no wildcard, no priority, no
ordering, no most-severe-wins, and no broad-group expansion.

## 6. Three failures that stay three failures

`INPUT_MISSING`, `INPUT_INDETERMINATE` and `INPUT_UNSUPPORTED` reach the
decision unchanged and are never reported as `NO_MATCH`.

Collapsing them would look tidy: all three fail to match. But `NO_MATCH` is a
statement *about the input* — a phenotype was observed and this rule does not
cover it — while the other three say no phenotype was observed at all. WP-13
must report the second class as an absence of coverage and WP-14 as
`NOT_ASSESSED`. Lost here, at the earliest possible point, nothing downstream
can recover it, and the system reports "no rule applies" where the truth is
"we could not look" (`SAFETY-INV-001`).

## 7. Scope against a whole rule condition

`match_condition(profile, condition)` evaluates the profile's phenotype for the
condition's **gene**. It does not consult the drug, and it does not read the
rule's outcome, provenance or evidence — a matcher that read the outcome could
let the answer depend on what the answer would cause. Selecting drugs and
evaluating a complete axis belong to WP-14.

A profile silent about the gene yields `INPUT_MISSING`: a rule about a gene
nobody supplied a value for has not been shown not to apply.

## 8. Profiles

Immutable, sorted by canonical gene, hashable, and complete — every supplied
gene keeps an explicit observation, including the ones that could not be
interpreted. A profile that dropped those would look complete.

The semantic hash excludes display names, demo prose, raw spellings,
insertion order, the source file and the clock. Two callers who observed the
same phenotypes for the same genes have the same profile. The caller's mapping
is copied, so mutating it afterwards changes nothing.

Two spellings of one gene are a refusal, not a choice: picking either would
invent an observation, and picking the first would make the result depend on
dictionary order. Catalogue validation fails closed — asking for it with an
empty catalogue is refused rather than passing everything.

## 9. What WP-12 does not do

It calculates no attention level and no coverage status, creates no finding,
aggregates nothing, executes and persists no assessment, infers no phenotype
from a genotype, implements no phenoconversion, interprets no star allele, and
adds no database migration. Phenotype matching is a pure operation over values,
so there is no state for a migration to hold.
