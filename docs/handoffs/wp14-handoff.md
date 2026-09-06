# WP-14 handoff

| Field | Value |
|---|---|
| Document ID | `DOC-HANDOFF-014` |
| Work package | WP-14 — Deterministic PGx Assessment Engine Migration |
| Status | **Offline scope complete. No real assessment was executed, no finding was persisted, and the default service refuses before reading anything.** |
| Output for WP-15 | a deterministic, release-pinned `AssessmentComputation`: structured facts only, with no prose and no rendered text anywhere in it |

> Read this before WP-15. Two items must not be presented as met.
>
> **A43**, real clinical/scientific execution, is **BLOCKED** — the claim
> boundary is `DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW` and eight further
> governance gates are closed behind it. The machinery is implemented and
> verified; what is missing is human and scientific judgement.
>
> **The scientific codes are absent.** WP-15 must render the absence as
> absence; section 3 below says why, and what not to do instead.
>
> WP-13's **A38**, WP-12's **A33**, WP-11's **A30** and **A26**, WP-10's
> **A24**–**A26** and WP-09's **A21**–**A23** remain blocked and were not
> touched.

---

## 1. What exists now

| Artefact | What it is |
|---|---|
| `pgx/engine/risk.py` | `pgx-assessment-engine/1`; the seven-check finding gate |
| `pgx/engine/risk_models.py` | findings, medication results, the attention table |
| `pgx/engine/risk_errors.py` | six failure types, 20 stable codes |
| `pgx/engine/risk_legacy.py` | the legacy comparison and its four-entry allowlist |
| `pgx/application/assessment_models.py` | the input contract and the pinned release |
| `pgx/application/assessment_service.py` | the ten-step sequence over injected ports |
| `pgx/application/assessment_schema.py` | seven published JSON Schemas |
| `pgx/application/assessment_gate_status.py` | nine blockers, each with an owner |
| `pgx/application/assessment_cli.py` | 10 read-only commands, 12 refused flags |
| `pgx/infrastructure/db/assessments.py` | the pure row mapping and the append-only repository |
| `migrations/versions/0009_wp14_assessments.py` | five tables, immutable after insert |
| `data/assessments/wp14-real-gate-status.json` | why no real assessment can execute |
| `data/migration/wp14/` | the comparison report and its allowlist |

## 2. What WP-15 receives

An `AssessmentComputation` carrying the overall coverage and attention, a
result per medication with its coverage status and reason codes, and a finding
per covered axis with its full traceability chain — pinned to the release,
software, dataset, ruleset, evidence build and coverage manifest it was
computed against, each by identity and hash.

What WP-15 must not do with it:

- **Do not render `NOT_ASSESSED` as a low level.** It is not a level. It means
  nothing was evaluated, and the language rule in the safety contract is that
  it reads as *"not assessed / outside the assessed scope"*. Rendering it as
  reassurance reproduces `LEGACY-BUG-002` in the one layer a reader actually
  sees.
- **Do not display attention without coverage.** They are separate first-class
  outputs and neither summarises the other. A `HIGH` beside a `PARTIAL` means
  *the worst of what we could evaluate*, and a reader shown only the first
  will believe the assessment was complete.
- **Do not resolve or hide a `SOURCE_CONFLICT`.** WP-14 preserved every side
  because choosing one is an adjudication, and a renderer has less information
  with which to make it than the engine that refused to.
- **Do not recompute, re-aggregate or re-order anything.** The collections are
  canonically sorted and the output hash covers them; a renderer that sorted
  differently would be displaying something the hash does not describe.
- **Do not add a scientific code, a dose, a recommendation or a comparison
  between medications.** None exists in the input, and inventing one at render
  time is the failure mode the schema's `additionalProperties: false` exists to
  make impossible upstream.

## 3. The reconciliation WP-15 inherits

The WP-02 `AssessmentFinding` required `effect_code` and `explanation_code`.
The governed WP-11 `RuleOutcome` carries neither — it carries an attention
level and a `rationale_reference` naming the approved curated interpretation
whose reasoning justifies it.

Rather than fabricate codes, the contract was evolved: both are now optional
and default to `None`, `rationale_reference` is required, a supplied code may
not be blank, and the database columns are nullable for the same reason.

**The limitation, stated for WP-15:** a rendered report cannot currently show
*what* effect a rule describes, only *how much attention* it warrants and
*which reviewed interpretation* justifies that. A renderer must show the
rationale reference and must render the absence as absence — saying the effect
code is not carried by the governed ruleset. It must not substitute prose of
its own, and it must not derive a code from the attention level; either would
invent the scientific content the pipeline deliberately does not yet have.

If a future protocol puts these codes into hash-covered versioned rule content,
they can be populated from there and this limitation lifts.

## 4. Where the real state stands

Unchanged by this work package, and reported rather than asserted:

| Count | Value |
|---|---|
| Real executable release contexts | 0 |
| Real completed assessments | 0 |
| Real findings | 0 |
| Real medication results | 0 |
| Real persisted assessments | 0 |

Nine blockers, none clearable by writing code:

- the claim boundary is DRAFT and awaiting human and scientific review;
- no release is active, so there is nothing to pin;
- there is no frozen ruleset, so no rule can execute;
- there is no approved coverage manifest, so no axis can be `FULL`;
- no rule has reached VALIDATED;
- the curation protocol is `AWAITING_EXPERT_REVIEW`;
- the canonical dataset is `BUILDING`;
- the evidence build is quarantined;
- and no identity holds a scientific role.

`data/assessments/wp14-real-gate-status.json` names each, who owns it, and what
clearing it would unblock.

## 5. The load-bearing things to preserve

**The pointer is read once.** Everything after pinning works from a value. The
temptation, when a release seems stale, is to re-read the pointer mid-run;
doing so would let an activation change an answer already being calculated, and
the stored assessment would name a release it did not entirely use.

**A `FULL` axis that does not verify is corruption, not absence.** The
temptation, when the ruleset and the coverage manifest disagree, is to downgrade
the axis to `NOT_ASSESSED` and carry on. That converts a disagreement between
two governed artifacts into an answer that looks routine, and nobody would ever
find it.

**`NOT_ASSESSED` is not in the precedence tuple.** The temptation, when writing
a maximum, is to give it a position "for completeness". Every position is
wrong: below `LOW` makes absence lose to a real finding and vanish; above
`HIGH` makes one unevaluable axis suppress a genuine one.

## 6. Open items

| Item | Owner | Blocks |
|---|---|---|
| A43 — real execution | named humans, then the whole chain below | every real assessment |
| Claim-boundary approval | the people named in `docs/architecture/intended-purpose.md` | the service refusing before it reads anything |
| Protocol approval | a named scientific expert | curation, rules, coverage, assessment |
| Dataset publication and evidence de-quarantine | WP-07 and source-policy review | a release pinning something stable and citable |
| Role assignment | WP-23, then whoever assigns roles | every separated approval above |
| A real ruleset, coverage manifest and active release | curators, reviewers, approvers | a release context that can be pinned |
| Effect/explanation codes in governed rule content | a future curation protocol | WP-15 being able to state what a rule describes |
| PostgreSQL execution of migration 0009 | an environment with a server | the trigger and constraint behaviour, checked live |

## 7. What was verified, and how

4,687 tests pass across WP-00-WP-15 as this is written, 16 skipped (they require PostgreSQL,
which is unavailable in this environment). WP-14 contributes 446 of them:

| Tests | File |
|---|---|
| 36 | `tests/unit/application/test_assessment_input.py` |
| 35 | `tests/unit/application/test_release_pinning.py` |
| 37 | `tests/unit/application/test_assessment_determinism.py` |
| 40 | `tests/unit/application/test_assessment_cli.py` |
| 30 | `tests/unit/engine/test_risk_execution.py` |
| 33 | `tests/unit/engine/test_risk_legacy_regression.py` |
| 42 | `tests/unit/engine/test_wp14_boundaries.py` |
| 37 | `tests/unit/engine/test_wp14_documentation.py` |
| 56 | `tests/unit/infrastructure/test_assessment_persistence.py` |
| 38 | `tests/safety/test_assessment_safety.py` |
| 35 | `tests/contract/test_wp14_schemas.py` |
| 27 | `tests/integration/engine/test_assessment_end_to_end.py` |

Those counts include the WP-15 preflight repairs, which corrected five
WP-14 defects in place rather than as a separate work package: canonical
entity identities are now resolved instead of minted, the stored input
snapshot carries the whole canonical input and hashes back to it, the
coverage result is embedded whole beside its hash, retrieval returns a
lossless read model, and the active pointer generation is recorded without
entering the output hash. `tests/unit/application/test_assessment_preflight.py`
holds the proofs and is counted under WP-15.

**PostgreSQL was not available.** SQLAlchemy, Alembic and a driver cannot be
installed in this environment, so migration 0009 was **not run** and no ORM
class was imported. What was verified is what the migration and the models
*say*: the revision chain, the five tables, every constraint and trigger, the
downgrade refusal, and the agreement between the ORM declarations and the
migration. The row mapping is pure and was executed. No claim is made here that
Alembic ran or that a trigger fired.

Everything WP-14 was verified against is synthetic. The one place real names
appear is the legacy comparison, which reads the real snapshots and the real
legacy script in order to report honestly what they still do.

Nothing here is clinical validation, and no attention level produced by this
work package asserts safety, preference or suitability for any medicine.
