# WP-13 — the coverage engine

| Field | Value |
|---|---|
| Document ID | `DOC-ARCH-013` |
| Work package | WP-13 — Coverage Engine |
| Depends on | WP-11 frozen rulesets, WP-12 exact phenotype matching, WP-07 canonical dataset, WP-05 evidence build |
| Hands to | WP-14 assessment. WP-13 computes no attention level |

---

## 1. One question

*What could this governed ruleset evaluate, and why could it not evaluate the
rest?*

That is the entire scope. WP-13 does not answer *what attention level should be
reported* — that is WP-14 — and it does not answer *is this medicine safe*,
which this system does not answer at all. Coverage and attention are separate
first-class outputs (`architecture.md` 9.2, 9.3), and keeping them separate is
the reason this work package exists as its own layer rather than as a field on
a finding.

## 2. The package

| Module | What it holds |
|---|---|
| `pgx/engine/coverage_manifest.py` | `pgx-ruleset-coverage-manifest/1`; the declared scope and the builder that verifies it |
| `pgx/engine/coverage_models.py` | axis, medication and overall results, and the medication reference that enters one |
| `pgx/engine/coverage.py` | `pgx-coverage-engine/1`; three decision tables and the functions that follow them |
| `pgx/engine/coverage_validator.py` | 18 ways a manifest can be untrue of what it pins |
| `pgx/engine/coverage_legacy.py` | the legacy risk-versus-coverage comparison and its difference allowlist |
| `pgx/engine/coverage_errors.py` | four failure types, each with a stable code |
| `pgx/application/coverage_cli.py` | 10 read-only commands, 9 refused flags |
| `pgx/application/coverage_schema.py` | the six published JSON Schemas |
| `pgx/application/coverage_gate_status.py` | why no real coverage claim can exist yet |

`pgx/engine` remains stdlib-only. WP-13's modules import `pgx.domain`,
`pgx.rules` and `pgx.engine` — all beneath or beside them — and nothing else:
no infrastructure, no framework, no network client, no model client, no clock,
no `re`, no `csv`, and not the legacy script. There is no coverage *service*,
because evaluating coverage transitions no state; and no migration, for the
same reason.

## 3. The manifest is a separate document

WP-11's `RulesetManifest.structural_axes` lists the gene/drug/phenotype triples
its member rules happen to be keyed on, and its own `note` field says that this
is a membership inventory rather than a claim of clinical coverage. WP-13 did
not relabel it. The coverage manifest is a separate document, pinned to the
exact ruleset, dataset, evidence build, curation protocol and source policy it
was declared against — each **by identity and by hash**, so a ruleset rebuilt
underneath a manifest is detected rather than inherited.

For each drug it carries two different things:

- `expected_gene_keys` — which genes a *complete* assessment of this drug would
  have to consider.
- `supported_axes` — which `(gene, phenotype)` axes the ruleset can actually
  evaluate, each with the validated member rule that covers it, that rule's
  version and content hash, and its evidence references.

The first is the load-bearing one, and it is **declared, never derived**. It
cannot come from the chemical catalogue, from every gene appearing in evidence,
from guideline presence, from the existence of one rule, or from a legacy CSV
row. It is governed scientific metadata and requires a named human declaration,
separately reviewed and separately approved.

The reason is a single sentence: *a scope derived from the rules that exist
makes every drug look exactly as covered as its rules happen to make it, and no
gap is ever visible.* A drug with a rule for one gene and none for another
looks complete if you read only the rules. It is the expected scope that turns
the second gene from an invisible absence into a reported gap.

The builder may **verify**: given a declared axis, find the validated member
rule whose condition covers exactly that axis, check that the frozen artifact's
own approval record evidences that content, check the evidence resolves, and
attach the references. That is checking somebody's claim. It never adds a gene
and never adds an axis.

A manifest whose expected scope is exactly the set of genes the ruleset has
rules for — with every axis supported — is reported as
`COVERAGE_STRUCTURAL_AXES_COPIED`. That shape may be a correct scope, and it is
also precisely what copying `structural_axes` produces, so it needs a reviewer
to say which. It is not accepted silently.

## 4. Six statuses, eight reason codes

`CoverageStatus` and `CoverageReasonCode` come from `pgx.domain.enums`
unchanged.

| Status | Means |
|---|---|
| `FULL` | the axis was evaluable: declared, covered by a validated rule, evidence resolves |
| `PARTIAL` | some of what was expected was evaluable and some was not |
| `INSUFFICIENT` | nothing was evaluable, and here is why |
| `UNSUPPORTED_DRUG` | the pinned canonical dataset does not contain the drug |
| `UNSUPPORTED_PHENOTYPE` | a value was supplied for the gene and could not be used |
| `SOURCE_CONFLICT` | validated sources disagree, and the disagreement is unresolved |

| Reason code | Says |
|---|---|
| `DRUG_NOT_IN_CANONICAL_DATASET` | the pinned dataset does not contain this chemical |
| `PHENOTYPE_NOT_PROVIDED` | the profile said nothing about this gene |
| `PHENOTYPE_NOT_SUPPORTED` | a value was supplied and could not be used |
| `NO_VALIDATED_RULE_FOR_AXIS` | nobody declared this exact axis as supported |
| `SOME_AXES_NOT_COVERED` | part of what was expected was not evaluable |
| `VALIDATED_RULES_CONFLICT` | validated sources disagree, unresolved |
| `DATASET_RULESET_MISMATCH` | the artifacts supplied are not the ones each other pins |
| `EVIDENCE_REFERENCE_MISSING` | the supporting evidence does not resolve |

Neither enum has an ordering, and neither may acquire one. Every non-`FULL`
result at every level carries at least one reason code; `FULL` carries none.
Both couplings are enforced in the dataclass, again in the published schema,
and again by property tests over every reason code.

## 5. Axis semantics

`evaluate_axis` follows `AXIS_DECISION_TABLE` top to bottom; the first matching
row wins. The order is part of the answer:

1. **boundary mismatch** → `INSUFFICIENT` / `DATASET_RULESET_MISMATCH`. Checked
   first, because a mismatched pin makes every later answer a statement about
   something nobody supplied. Fails closed: a good phenotype does not rescue a
   bad pin.
2. **unresolved conflict** → `SOURCE_CONFLICT` / `VALIDATED_RULES_CONFLICT`,
   with every rule and evidence reference from every side preserved. Checked
   before the phenotype, because a disagreement about an axis is a fact about
   the axis whatever was observed — including when nothing was observed.
3. **phenotype absent** → `INSUFFICIENT` / `PHENOTYPE_NOT_PROVIDED`.
4. **phenotype unusable** (unsupported or indeterminate) →
   `UNSUPPORTED_PHENOTYPE` / `PHENOTYPE_NOT_SUPPORTED`.
5. **axis not declared** → `INSUFFICIENT` / `NO_VALIDATED_RULE_FOR_AXIS`.
6. **rule not a member, or content hash disagrees** → `INSUFFICIENT` /
   `DATASET_RULESET_MISMATCH`.
7. **rule does not cover the observed phenotype** → `INSUFFICIENT` /
   `NO_VALIDATED_RULE_FOR_AXIS`.
8. **evidence unresolvable** → `INSUFFICIENT` / `EVIDENCE_REFERENCE_MISSING`.
9. **covered** → `FULL`, with no reason.

Steps 3 and 4 stay separate because *nothing was supplied* and *what was
supplied could not be read* are different failures. Step 7 is decided by WP-12's
`match_observation` and is not reimplemented here: a second equality rule is a
second place for `RAPID` to start meaning `ULTRARAPID`.

## 6. Aggregation is a table, not a comparison

`MEDICATION_DECISION_TABLE` and `OVERALL_DECISION_TABLE` are written out case by
case, which is longer and is the point. Nothing uses `max`, `min`, sorting or
enum declaration order to combine statuses — `max` and `min` do not appear in
these modules at all, and no sort in them touches a status.

Medication level: a drug absent from the dataset is `UNSUPPORTED_DRUG` and no
axis is fabricated for it; a recognised drug with no declared scope is
`INSUFFICIENT` (recognition is not coverage, `architecture.md` 6.2); any
conflicting axis makes the medication `SOURCE_CONFLICT`; all axes `FULL` is
`FULL`; some `FULL` is `PARTIAL` with `SOME_AXES_NOT_COVERED` *plus* the
underlying axis reasons; homogeneous unusable-phenotype failures keep that
status; anything else is `INSUFFICIENT` with the reasons the axes gave.

Overall level: the same shape over medications, with `UNSUPPORTED_DRUG`
surviving as its own status when every drug is absent.

**Conflict precedence is preservation, not severity.** When a disagreement is
present anywhere the result says so, and every other status and reason survives
alongside it. That is not `SOURCE_CONFLICT` outranking `PARTIAL`; it is the one
fact that must not disappear into an aggregate (`SAFETY-INV-008`).

A `PARTIAL` medication keeps both kinds of axis. One that dropped its covered
axes would be indistinguishable from an insufficient one; one that dropped its
uncovered axes would look complete.

## 7. The downstream contract

Six JSON Schemas are published. Every one is `additionalProperties: false` at
every level, which is where the separation of coverage from attention is
actually enforced: an attention level, a risk level, a risk score, a severity, a
dose, a recommendation, a preferred or safer flag, a suitability score or a
treatment cannot be attached to any of these documents by anything downstream,
because the schema refuses every property it does not name.

None of them uses `contains`. This project's validator raises on any keyword it
does not implement, and a schema asserting something the validator cannot check
would report documents as valid while silently not checking the constraint its
author wrote. Where a constraint cannot be expressed in the supported keyword
set — `PARTIAL` carrying `SOME_AXES_NOT_COVERED`, specifically — the schema says
so, and the constraint is enforced in the model and by test instead.

## 8. What WP-13 does not do

It calculates no attention level and returns no `LOW`, `MEDIUM`, `HIGH` or
`NO_ACTIVE_ATTENTION`; creates no `AssessmentFinding` and no `AssessmentResult`;
evaluates no rule outcome; aggregates no attention; recommends, ranks and scores
no medication; assigns no risk score; asserts safety for no medicine;
treats no missing data as low concern; infers no coverage from the existence of
a chemical, from guideline presence, from WP-11's structural axes, or from
anything else; infers no expected drug-gene relationship; infers no phenotype
from a genotype; implements no phenoconversion and no drug-interaction
adjustment; reads no mutable CSV as coverage configuration; uses no `DRAFT` or
`CURATED` rule; bypasses no frozen-ruleset registry; calls no network and no
model; creates no human approval; and adds no database migration.

The strongest of those guarantees are the ones enforced by absence rather than
by a check: there is no field in any WP-13 model or schema an attention level
could be written into, and `tests/unit/engine/test_wp13_boundaries.py` asserts
that as identifiers, dataclass fields, schema properties and CLI commands.

## 9. No real coverage claim exists

Every artefact in this work package was verified against synthetic fixtures. No
approved coverage manifest exists, and none can while the curation protocol is
`AWAITING_EXPERT_REVIEW`, the canonical dataset is `BUILDING`, the evidence
build is quarantined, no frozen ruleset is registered, no drug has an approved
expected gene scope, and no identity holds a scientific role.
`data/coverage/wp13-real-gate-status.json` reports all eight blockers, who owns
each, and what clearing it would unblock. None can be cleared by writing code.
