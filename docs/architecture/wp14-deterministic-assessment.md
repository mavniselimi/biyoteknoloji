# WP-14 — the deterministic assessment engine

| Field | Value |
|---|---|
| Document ID | `DOC-ARCH-014` |
| Work package | WP-14 — Deterministic PGx Assessment Engine Migration |
| Depends on | WP-03 release registry, WP-11 frozen rulesets, WP-12 exact matching, WP-13 coverage |
| Hands to | WP-15 reporting. WP-14 renders nothing |

---

## 1. One question

*Given a coverage result that says which axes could be evaluated, what did the
governed rules actually say about them?*

Not *what could be evaluated* — that is WP-13, and this engine consumes its
answer rather than recomputing it. Not *how to say any of this to a person* —
that is WP-15, and there is no prose here. And not *what should be done about
it*, which this product does not answer at all.

## 2. The package

| Module | What it holds |
|---|---|
| `pgx/engine/risk.py` | `pgx-assessment-engine/2`; the finding gate and the computation |
| `pgx/engine/risk_models.py` | findings, medication results, and the attention aggregation table |
| `pgx/engine/risk_errors.py` | six failure types and 22 stable codes |
| `pgx/engine/risk_legacy.py` | the legacy comparison and its difference allowlist |
| `pgx/application/assessment_models.py` | `pgx-assessment-input/1`, the pinned release context and the canonical entity index |
| `pgx/application/assessment_snapshot.py` | the reproducible input snapshot and its verification |
| `pgx/application/assessment_read_model.py` | the lossless read model of a stored assessment |
| `pgx/application/assessment_service.py` | the ten-step sequence, over injected ports |
| `pgx/application/assessment_schema.py` | the seven published JSON Schemas |
| `pgx/application/assessment_gate_status.py` | why no real assessment can execute yet |
| `pgx/application/assessment_cli.py` | 10 read-only commands, 12 refused flags |
| `pgx/infrastructure/db/assessments.py` | the row mapping and the append-only repository |
| `migrations/versions/0009_wp14_assessments.py` | five tables, immutable after insert |

`pgx/engine` remains stdlib-only. WP-14's engine modules import `pgx.domain`
and `pgx.engine` and nothing else: no application module, no infrastructure
module, no network client, no model client, **no clock**, no `re`, no `csv`,
and not the legacy script.

## 3. The input contract

`AssessmentInput` is *what was asked*: a mode, an input kind, a WP-12 phenotype
profile, and canonically sorted medications. `content_hash()` covers exactly
that.

It excludes the assessment id, the actor, the request time, the process, the
source path, any UI metadata, the order the caller listed things in — and
**`case_id`**. That last one is a decision, documented here and asserted by
test: a case identifier labels a run, it is not part of the question. If it
entered the hash, two runs of the same question under different case ids would
look like different questions, destroying the comparison the hash exists to
support. The case id is recorded, persisted and returned; it is simply not part
of what was asked.

19 field names are refused outright, and a request carrying one is
refused *as a whole*: `genotype`, `diplotype`, `star_allele`, `alleles`,
`activity_score`, `vcf`, `vcf_path`, `ehr`, `ehr_id`, `patient_narrative`,
`clinical_notes`, `narrative`, `diagnosis`, `indication`, `dose`, `dosage`,
`patient_name`, `date_of_birth`, `mrn`. Using the acceptable half of an
unacceptable request would confirm the caller's belief that this system reads
VCFs.

A medication the pinned dataset does not contain is kept exactly as supplied,
so coverage can report it as unsupported. Dropping it would make an
unanswerable question look answered.

## 4. Release pinning

The service reads the WP-03 active-release pointer **once**, before
calculation, capturing the generation it saw. Everything after that point works
from a `PinnedAssessmentRelease` — a value, not a lookup. An activation
committing mid-run therefore cannot change a calculation already in progress,
not because the service checks for it but because there is nothing left to
check.

The pinned context carries, each by identity *and* content hash: the release,
its manifest, the pointer generation, the software version and source-tree
hash, the dataset, its canonical build, the ruleset, its frozen content hash,
the evidence build, the coverage manifest, the curation protocol and the source
policy. All of it is NOT NULL in the database (`SAFETY-INV-007`).

The request cannot override any of it. `AssessmentInput` has no version field
at all; the only release-related thing a caller may set is *which* release,
and a release that is not `ACTIVE` at pin time is refused. Historical replay is
not part of WP-14.

## 5. Coverage-first execution

Coverage is calculated before any finding, and is the gate:

| Axis coverage | Finding? |
|---|---|
| `FULL` | yes, if it verifies |
| `PARTIAL` (medication level) | findings from its `FULL` axes are preserved |
| `INSUFFICIENT` | no |
| `UNSUPPORTED_DRUG` | no |
| `UNSUPPORTED_PHENOTYPE` | no |
| `SOURCE_CONFLICT` | no, and the conflict is preserved |

Every non-`FULL` coverage result stays in the final structured calculation.
`risk.py` never recomputes or infers coverage — a test asserts it does not even
name `evaluate_coverage`.

## 6. The finding gate

For a `FULL` axis, seven checks, all of which must pass:

1. the axis names exactly one supporting rule;
2. that rule is a member of the pinned frozen ruleset;
3. its content hash equals what coverage recorded;
4. the frozen artifact carries an approval record for that exact content
   (`SAFETY-INV-003` — membership is not validation);
5. its condition names this exact drug and gene;
6. WP-12's `match_observation` reports MATCH (`SAFETY-INV-004`);
7. its evidence is non-empty and resolves (`SAFETY-INV-006`).

**A `FULL` axis that fails any of these is corruption, not absence.** Coverage
was computed against a manifest; this runs against the artifact. A disagreement
means one of two governed documents is wrong and neither may be trusted, so the
assessment fails closed with a stable code. Quietly downgrading the axis to
`NOT_ASSESSED` would hide that behind an answer that looks routine.

Two rules covering one axis is `ASSESSMENT_CONFLICT_UNRESOLVED`. WP-11 refuses
such a ruleset; if one appears anyway, this engine will not pick between them
and will not take a maximum.

## 7. The finding contract, and the codes that are absent

A finding carries the drug, the gene, the observed phenotype, the attention
level, the rule id, family, version and content hash, the **rationale
reference**, the evidence references, the curation revision and its hash, and
the ruleset, dataset and coverage-manifest identities.

`effect_code` and `explanation_code` are **absent**, and this is the WP-02
contract reconciliation done honestly.

WP-02 modelled both as required, anticipating that a governed rule would carry
them. The governed rule outcome WP-11 actually built carries two things: an
attention level and a `rationale_reference` pointing at the approved curated
interpretation whose reasoning justifies it. Nothing in this repository
produces a reviewed scientific effect or explanation code.

So `pgx.domain.models.AssessmentFinding` was evolved: both codes are now
optional and default to `None`, `rationale_reference` is required, and a
supplied code may not be blank — absent and present-but-blank must not be
confusable. The database columns are nullable for the same reason; `NOT NULL`
would have forced every row to invent one.

An invented `DECREASED_ACTIVATION` would be a scientific claim wearing the
appearance of a reviewed one, and a downstream reader cannot tell the two
apart. **WP-15 must render the absence as absence.** If a future protocol puts
these codes into hash-covered versioned rule content, they can be populated
from there.

## 8. Attention

`ATTENTION_PRECEDENCE` is an explicitly written tuple — `HIGH`, `MEDIUM`,
`LOW`, `NO_ACTIVE_ATTENTION` — read top to bottom, first present wins. Nothing
uses enum ordering, and no numeric score exists anywhere.

`NOT_ASSESSED` is **not in the tuple**, and its absence is the specification.
It means *we did not look*, which is not a magnitude; every possible position
for it in a maximum is wrong, so passing it into an aggregation raises.

| Case | Coverage | Result |
|---|---|---|
| at least one calculated level | any | the first level in the precedence that is present |
| none | `FULL` | `NO_ACTIVE_ATTENTION` |
| none | anything else | `NOT_ASSESSED` |

Coverage never *lowers* a calculated level: a medication with one `HIGH`
finding and one unevaluable axis is `HIGH` **with `PARTIAL` beside it**. The
two are separate first-class outputs and neither summarises the other.

Under coverage-first execution a `FULL` axis always carries a matched validated
rule, and a matched rule always has a governed outcome — so
`NO_ACTIVE_ATTENTION` here is a level a curator approved, not the residue of
nothing having happened. The no-finding branches are backstops, tested
directly.

Overall attention aggregates only *calculated* medication levels, excluding
`NOT_ASSESSED`, and never hides `PARTIAL` or `SOURCE_CONFLICT` behind a level.

## 9. Conflicts

Not resolved. A conflicted axis emits no finding, keeps `SOURCE_CONFLICT` and
`VALIDATED_RULES_CONFLICT`, and preserves every conflict reference. No lower
level, no higher level, no average, no rule order. An independent covered axis
keeps its finding; if none exists the medication is `NOT_ASSESSED`. A WP-13
conflict signal carries no governed outcome, so there is nothing in it to
manufacture a level from (`SAFETY-INV-008`).

## 10. Determinism

`output_hash` covers the calculated facts and every pinned version. It excludes
the assessment id, `created_at`, `completed_at`, the actor, database insertion
order, local paths, wall-clock time, the process id, runtime duration, UI
labels and report prose.

Two executions of the same input against the same pinned release therefore have
identical structured content and identical hashes even when their ids, actors
and timestamps differ. Medications, axes, findings, rule references, evidence
references and reason codes are all sorted by explicit stable keys.

## 11. Persistence

Five tables, created by migration 0009 and immutable after insert: triggers
refuse `UPDATE` and `DELETE` on every one. The repository has no update method
and no delete method — the absence is the contract.

One assessment is one transaction: the assessment, its medications, its axes,
its findings, its evidence links and one `ASSESSMENT_COMPLETED` audit event are
staged and committed together. A refusal writes `ASSESSMENT_REFUSED` carrying
a stable code and no case content, and never a success.

The database enforces, independently of application code: complete release
metadata (`NOT NULL` on every pinned column), `NO_ACTIVE_ATTENTION` only with
`FULL` coverage, `FULL` coverage never `NOT_ASSESSED`, non-`FULL` coverage
carrying a reason, a finding never `NOT_ASSESSED`, every finding citing
evidence (a deferred constraint trigger), a conflicted axis naming its
conflict, `PILOT` not storable, canonical hash formats, one finding identity
per assessment, every child row belonging to its parent's assessment, and
`ON DELETE RESTRICT` on the release, the rule and the evidence record a stored
assessment cites.

Downgrade refuses, in a transaction that changes nothing, when any assessment
is stored.

## 12. What WP-14 does not do

It diagnoses nothing; recommends, ranks and chooses no medication; calculates
no dose; states of no medicine that it is appropriate; infers no phenotype from
a genotype; implements no phenoconversion and no drug-interaction adjustment;
reads no VCF, EHR or clinical narrative; executes no `RAW`, `DRAFT`, `CURATED`
or `DEPRECATED` rule and no merely-`VALIDATED` ruleset; infers no coverage;
treats no missing data as low concern; resolves no source conflict; reads no
mutable CSV; calls no network and no model; lets no clock reach a calculated
fact; re-reads no active pointer after pinning; and renders no report prose.

## 13. No real assessment exists

Every artefact was verified against synthetic fixtures. The claim boundary is
`DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW`, and the default service refuses
before reading anything. `data/assessments/wp14-real-gate-status.json` reports
nine blockers, who owns each, and what clearing it would unblock. None can be
cleared by writing code.
