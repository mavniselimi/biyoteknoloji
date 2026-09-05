# PGx Platform V2 - Safety Contract and Invariant Registry

| Field | Value |
|---|---|
| Document ID | `DOC-SC-001` |
| Document version | `0.1.0-draft` |
| Status | **DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW** |
| Work package | WP-00 - Intended Purpose, Claims Boundary, and Safety Contract |
| Machine-readable counterpart | `pgx/domain/claims.py` |
| Test evidence | `tests/unit/test_claims.py` |
| Companion document | `docs/architecture/intended-purpose.md` |
| Architecture source | `architecture.md` sections 2.2, 3, 9, 10.2, 12.1, 12.4, 13 |
| Created | 2026-08-29 |
| Approved by | *(not approved - see section 10)* |

> **This document is not approved.** No expert review, scientific approval,
> holdout result, or safety validation has been performed. The invariants
> below are *requirements*, not evidence that the system satisfies them.
> Most are implemented by work packages that have not started.

---

## 1. Architecture safety principles

These are system requirements, not documentation suggestions
(`architecture.md` section 3). Every principle maps to at least one
invariant in section 2.

1. Missing data must never produce `LOW` or `NO_ACTIVE_ATTENTION`.
2. Only `VALIDATED` rules from the active immutable ruleset may execute.
3. Every calculated finding must include at least one traceable evidence
   reference.
4. `RAPID` and `ULTRARAPID` are distinct unless a validated rule explicitly
   lists both.
5. Risk and coverage are separate first-class outputs.
6. Same input plus the same release bundle must produce the same structured
   assessment.
7. Candidate exploration must never label a candidate as safer or recommend
   treatment.
8. LLM output is optional, downstream, schema-checked, and unable to alter
   clinical facts.
9. Development/curation cases and independent holdout cases must not be
   mixed.
10. Dataset, ruleset, software, input, and output identities must be
    auditable.

**Fail-closed rule.** Where an invariant cannot be evaluated, the system
must behave as though it were violated: refuse to calculate, refuse to
persist, or refuse to release the report. Degrading to a permissive default
is itself a safety defect.

## 2. Safety invariant registry

Status legend: `SPECIFIED` = required and documented, implementation owned by
the listed WP. `PARTIAL` = a mechanism exists in WP-00. No invariant is
`VERIFIED` at WP-00.

---

### `SAFETY-INV-001` - Missing data must not produce low or no-active attention

- **Requirement:** When any required input, rule, or evidence for an axis is
  absent, medication-level attention is `NOT_ASSESSED` and coverage is not
  `FULL`. The engine must never emit `LOW` or `NO_ACTIVE_ATTENTION` as a
  consequence of absence. `NOT_ASSESSED` is not numerically ordered against
  `LOW`/`MEDIUM`/`HIGH`.
- **Rationale:** The highest-consequence failure mode of a PGx tool is
  *false reassurance*: a clinician reading "no risk" where the correct
  reading is "we did not look". Legacy `risk_engine.py` returns top-level
  risk `none` for unsupported drugs and renders it as
  `"Düşük / uyarı yok"` (`LEGACY-BUG-002`), which conflates the two.
- **Enforcement layers:** domain enums; coverage engine (WP-13); risk engine
  (WP-14); structured report (WP-15); API serialisation (WP-16); UI
  rendering (WP-17); claim scanner category `FALSE_REASSURANCE`.
- **Verification:** `tests/safety/` case matrix over every coverage reason
  code; property test asserting no absence path yields `LOW` or
  `NO_ACTIVE_ATTENTION`; report snapshot tests; blocking CI gate (WP-20).
- **On violation:** assessment fails closed with an explicit error; nothing
  is persisted or rendered; audit records the failure code. In CI the build
  fails.
- **Status:** `PARTIAL` (claim scanner category exists; engine owned by
  WP-13/WP-14/WP-20).

---

### `SAFETY-INV-002` - An LLM must not alter calculated facts

- **Requirement:** The optional LLM renderer receives only the
  `StructuredReport`. It may not change any drug, gene, phenotype, attention
  level, coverage status, coverage reason, rule ID, rule version, evidence
  reference, or version identifier, and may not introduce a new drug, dose,
  treatment, contraindication, or safety claim. A post-processor verifies
  every entity against the input; failure returns the deterministic report.
- **Rationale:** A generative layer that can silently rewrite a calculated
  fact destroys determinism, traceability, and the evidence chain at once.
- **Enforcement layers:** reporting/LLM adapter (WP-15, P1-06); schema
  validator; entity-existence post-check; claim scanner on LLM output;
  `ENABLE_LLM_REPORTS=false` default.
- **Verification:** adversarial fixtures in which the model adds a dose,
  changes an attention level, invents an evidence ID, or drops version
  metadata - each must fall back to the deterministic report; contract tests
  over the renderer schema.
- **On violation:** discard the LLM output, serve the deterministic report,
  record an audit event with both hashes.
- **Status:** `SPECIFIED` (owner: WP-15 / P1-06 / WP-20).

---

### `SAFETY-INV-003` - Unvalidated or deprecated rules must not execute

- **Requirement:** Only rules with lifecycle state `VALIDATED` belonging to
  the pinned active ruleset version may participate in a calculation. Draft,
  proposed, rejected, superseded, and deprecated rules must be inert at
  assessment time.
- **Rationale:** The scientific claim of the product rests entirely on rule
  governance. An unapproved rule that can fire makes the approval workflow
  decorative. Legacy `MANUAL_EFFECT_HINTS` is exactly such content
  (`LEGACY-BUG-006`).
- **Enforcement layers:** rule registry and validator (WP-11); release bundle
  pinning (WP-03); assessment service (WP-14); database constraint on rule
  state.
- **Verification:** integration test loading a ruleset containing draft and
  deprecated rules and asserting they never appear in findings; rollback test
  after re-activation of a previous ruleset.
- **On violation:** assessment aborts; the ruleset is treated as corrupt and
  the release is not activated.
- **Status:** `SPECIFIED` (owner: WP-11 / WP-14 / WP-20).

---

### `SAFETY-INV-004` - `RAPID` must not implicitly equal `ULTRARAPID`

- **Requirement:** Phenotype matching is exact string equality against the
  P0 phenotype model. A rule applying to more than one phenotype must encode
  an explicit set. No synonym table, prefix match, or ordinal proximity may
  be applied at assessment time; normalisation happens before the call.
- **Rationale:** `LEGACY-BUG-001`: the legacy matcher lets `RAPID` and
  `ULTRARAPID` match each other, silently applying a rule outside its
  evidence. Implicit equivalence is an unreviewed scientific claim.
- **Enforcement layers:** phenotype engine (WP-12); rule schema (WP-11);
  normalisation boundary (WP-07).
- **Verification:** matrix test over all six phenotype values x rule
  phenotype sets, asserting no cross-match; explicit regression test for the
  `RAPID` / `ULTRARAPID` pair.
- **On violation:** the finding is invalid; the engine raises rather than
  emitting it.
- **Status:** `SPECIFIED` (owner: WP-12 / WP-20).

---

### `SAFETY-INV-005` - A candidate must not be labelled safer or preferred

- **Requirement:** Candidate exploration may display, for each candidate,
  only its **data status**: whether the canonical dataset contains the
  chemical, whether a validated rule exists for the relevant axis, and the
  resulting coverage and attention values. It must not rank by safety,
  produce a suitability score, or use the words safer, preferred, suitable,
  better, or clinically equivalent. The legacy 0-100 score is removed
  (`LEGACY-BUG-009`).
- **Rationale:** A ranked list is read as a recommendation regardless of
  disclaimers. The legacy score mixes "we have data" with "this is a good
  option", which is precisely the confusion that harms patients.
- **Enforcement layers:** candidate exploration (P1-02); reporting; claim
  scanner category `CANDIDATE_PREFERENCE`; UI templates.
- **Verification:** fixtures asserting no ordering key derives from attention
  level; claim-scanner tests for `daha güvenli` / `safer` / `preferred` /
  `en uygun`; template review checklist.
- **On violation:** report release is blocked; the feature is disabled until
  the wording and ordering are corrected.
- **Status:** `PARTIAL` (scanner category and tests exist; feature owned by
  P1-02).

---

### `SAFETY-INV-006` - Every calculated finding must carry traceable evidence

- **Requirement:** A finding may be emitted only with at least one resolvable
  evidence reference that exists in the pinned dataset version, reachable
  from finding -> rule -> interpretation -> evidence -> source record.
  Evidence strength belongs to the exact evidence or interpretation, never to
  the mere existence of a drug-gene pair (`LEGACY-BUG-005`).
- **Rationale:** Without a resolvable citation, an "explainable" output is an
  assertion. Traceability is the core THS 6 claim of this system.
- **Enforcement layers:** domain model (WP-02); evidence store (WP-08); rule
  registry (WP-11); assessment service (WP-14); structured report (WP-15);
  coverage reason `EVIDENCE_REFERENCE_MISSING`.
- **Verification:** every finding in every validation run resolves its
  evidence IDs; negative test with a dangling reference; evidence
  traceability rate metric reported per release (WP-21).
- **On violation:** the finding is not emitted; coverage degrades with reason
  `EVIDENCE_REFERENCE_MISSING`; the run is flagged.
- **Status:** `SPECIFIED` (owner: WP-08 / WP-14 / WP-20).

---

### `SAFETY-INV-007` - Missing release metadata must fail assessment persistence

- **Requirement:** An assessment may be persisted only with a complete
  release bundle: `release_id`, `software_version`, `dataset_version`,
  `ruleset_version`, plus `input_hash` and `output_hash`. The release bundle
  is pinned before calculation begins and does not change mid-assessment.
- **Rationale:** An unversioned result cannot be reproduced, audited, or
  retracted. Legacy summaries went stale relative to their own data
  (`LEGACY-BUG-007`) precisely because identity was not enforced.
- **Enforcement layers:** release service (WP-03); assessment service
  (WP-14); database `NOT NULL` and foreign-key constraints; audit writer
  (WP-23).
- **Verification:** persistence test with each metadata field omitted in turn,
  each expected to fail; determinism test re-running a pinned bundle and
  comparing `output_hash`.
- **On violation:** the write is rejected; the assessment is not returned as
  a validated result.
- **Status:** `SPECIFIED` (owner: WP-03 / WP-14 / WP-23).

---

### `SAFETY-INV-008` - A source conflict must not collapse into a reassuring result

- **Requirement:** When validated rules or sources disagree for an axis, the
  system reports coverage `SOURCE_CONFLICT` with reason
  `VALIDATED_RULES_CONFLICT` and surfaces the disagreement. It must not pick
  the lower attention level, average the levels, or drop the conflicting rule
  to produce a clean answer.
- **Rationale:** Conflict is information. Silent resolution manufactures a
  false consensus and hides exactly the case a clinician most needs to see.
- **Enforcement layers:** rule evaluation (WP-14); coverage engine (WP-13);
  reporting (WP-15); source conflict v1 (P1-03).
- **Verification:** fixtures with deliberately conflicting validated rules
  asserting `SOURCE_CONFLICT` and preservation of the higher attention
  finding; unresolved-conflict count reported per release (WP-21).
- **On violation:** the assessment is invalid; the conflict is escalated to
  curation.
- **Status:** `SPECIFIED` (owner: WP-13 / WP-14 / P1-03).

---

### `SAFETY-INV-009` - Development and expert-holdout roles must not overlap

- **Requirement:** A validation case has exactly one role (`DEVELOPMENT`,
  `INTERNAL_HOLDOUT`, `EXPERT_HOLDOUT`). No case ID may appear in more than
  one role; holdout cases must not inform rule design or code tuning; metrics
  are reported separately per role and never pooled. Expert holdout payloads
  are not committed to a developer-visible directory when the same developer
  authors rules.
- **Rationale:** Independence is the entire evidential value of a holdout
  set. Once it leaks into development, the resulting metric measures memory,
  not generalisation - and no later analysis can undo it.
- **Enforcement layers:** validation case store (WP-18); repository layout and
  access control; metrics reporter (WP-21); review module (WP-22); CI check
  for case-ID overlap.
- **Verification:** automated overlap detection across role directories;
  `who_has_seen` metadata audit; a metrics test asserting no aggregate mixes
  roles or hides a zero denominator.
- **On violation:** the affected holdout set is burned - it is reclassified as
  development data and a new holdout set must be constructed. The release
  cannot claim Gate D.
- **Status:** `SPECIFIED` (owner: WP-18 / WP-21 / WP-22).

---

### `SAFETY-INV-010` - Prohibited claim text must block report release

- **Requirement:** Every user-facing text surface - deterministic report,
  structured report strings, API response text, UI template output, and any
  LLM rendering - is scanned by `pgx.domain.claims.scan_claim_text()` before
  release. Any `BLOCKING` violation prevents release of that text.
- **Rationale:** Safe templates are the primary control, but templates drift,
  source summaries carry dosing language (`LEGACY-BUG-012`), and generative
  renderings are unpredictable. A deterministic last-line check makes the
  failure loud instead of silent.
- **Enforcement layers:** `pgx/domain/claims.py` (WP-00); reporting (WP-15);
  API error path (WP-16); UI (WP-17); LLM post-processor (P1-06); CI over
  static templates.
- **Verification:** `tests/unit/test_claims.py` - Turkish and English
  prohibited fixtures, negation and clinician-deferral fixtures, multi-
  violation structure, empty/neutral false-positive fixtures, and legacy
  warning fixtures.
- **On violation:** `assert_claim_text_allowed()` raises
  `ProhibitedClaimError`; the layer serves an error or the safe template, and
  records the rule IDs and categories in the audit entry. Never auto-edit the
  offending text into compliance.
- **Status:** `PARTIAL` (scanner implemented and tested at WP-00; integration
  into report/API/UI owned by WP-15/WP-16/WP-17).

---

### `SAFETY-INV-011` - Real patient or genomic data must not enter P0

- **Requirement:** P0 accepts only the input kinds enumerated as
  `PermittedInputKind`. No VCF, FASTQ, genotype, diplotype, EHR extract,
  laboratory report, or direct patient identifier may be ingested, stored, or
  inferred from. `PILOT` mode remains disabled.
- **Rationale:** The intended purpose, the privacy posture, the security
  model, and the validation evidence are all scoped to synthetic and
  protocol-defined data. Accepting real data silently invalidates all four.
- **Enforcement layers:** `is_mode_enabled()` / `require_mode_enabled()`
  (WP-00); API request schema (WP-16); validation case schema PII assertion
  (WP-18); claim scanner category `REAL_PATIENT_DATA`; absence of any
  ingestion path.
- **Verification:** `tests/unit/test_claims.py` asserts `PILOT` is disabled;
  API contract tests reject genomic payload fields; case schema requires an
  explicit no-PII assertion.
- **On violation:** the request is rejected; any ingested artifact is treated
  as an incident, not a feature.
- **Status:** `PARTIAL` (mode gate implemented at WP-00; API/schema owned by
  WP-16/WP-18).

---

### `SAFETY-INV-012` - Determinism and auditability of every released result

- **Requirement:** The same input plus the same release bundle produces a
  byte-identical structured assessment. Wall-clock time, unordered database
  iteration, mid-run release changes, LLM output, UI choices, external network
  calls, and non-versioned local CSV files must not influence calculation.
  Every assessment writes an append-only audit record: actor, role, UTC
  timestamp, correlation ID, action, object identity, input/output hashes,
  version bundle, and result code.
- **Rationale:** Principles 6 and 10. A result that cannot be reproduced
  cannot be reviewed, defended, or retracted, and an unaudited result cannot
  be attributed.
- **Enforcement layers:** assessment service determinism boundary (WP-14);
  canonical input hashing and sorted output collections; audit writer
  (WP-23); CI repeat-run check.
- **Verification:** repeated-run hash equality; ordering-independence test
  with shuffled input; audit completeness test; deterministic repeatability
  rate reported per release (WP-21).
- **On violation:** the release fails Gate C/E and cannot be activated.
- **Status:** `SPECIFIED` (owner: WP-14 / WP-23 / WP-24).

---

## 3. Prohibited clinical claims

The authoritative list is section 7 of
`docs/architecture/intended-purpose.md`, encoded as
`ProhibitedClaimCategory` in `pgx/domain/claims.py`.

| Category | Prohibited because | Detected by |
|---|---|---|
| `DIAGNOSIS` | The system evaluates rules, not patients | `CLAIM-DIAG-*` |
| `PRESCRIPTION` | Prescribing is a licensed clinical act | `CLAIM-RX-*` |
| `DOSING` | No dose logic exists, and none is validated | `CLAIM-DOSE-*` |
| `MEDICATION_CHANGE` | Starting/stopping therapy is a clinical decision | `CLAIM-MEDIC-*` |
| `TREATMENT_SELECTION` | Selection requires indication and clinical context the system never sees | `CLAIM-TXSEL-*` |
| `SAFETY_ASSURANCE` | Absence of an attention finding is not evidence of safety | `CLAIM-SAFE-*` |
| `CANDIDATE_PREFERENCE` | Data availability is not clinical preferability (`SAFETY-INV-005`) | `CLAIM-CAND-*` |
| `FALSE_REASSURANCE` | Missing data is not low risk (`SAFETY-INV-001`) | `CLAIM-REASSURE-*` |
| `REAL_PATIENT_DATA` | Out of intended purpose in P0 (`SAFETY-INV-011`) | `CLAIM-REALDATA-*` |
| `CLINICAL_DECISION_SUBSTITUTION` | The system is explicitly not a decision-maker | `CLAIM-DECISION-*` |
| `VALIDATION_OVERCLAIM` | Demo cases and rule-row counts are not clinical evidence | `CLAIM-VALID-*` |

### 3.1 Scope and honest limits of the claim scanner

`scan_claim_text()` is a **lexical, pattern-based defense layer**. It is
**not** an NLP system, not a semantic classifier, and not a scientific or
regulatory assessment of text. It must never be presented as one, in a demo
or in a THS 6 artifact.

What it does: folds Turkish diacritics and case, splits text into sentences,
matches a registry of Turkish and English patterns, and suppresses a match
when the same sentence negates it (`değildir`, `üretmez`, `does not`),
forbids it (`verme`, `avoid`, `must not`), or defers it to a clinician
(`yalnızca hekim tarafından`, `by a physician`). Direct second-person
imperatives are non-negatable: `Bu ilacı kullanın; bu bir öneri değildir.`
is still a violation.

Known limitations, stated deliberately:

- paraphrase evades it (`Bu ilacı tercih etmeniz yerinde olur`);
- sentence-scoped negation is a heuristic; a negation in a neighbouring
  clause can suppress a real claim for non-imperative patterns;
- it cannot judge whether a *true* statement is scientifically supported;
- a clean scan means "no known prohibited pattern was found", never "this
  text is safe".

Safe templates and human review remain the primary control. The scanner is
the last line, not the first.

## 4. The "missing data != low/no risk" contract

This is the single most important behavioural contract in the system
(`SAFETY-INV-001`).

| Situation | Coverage | Reason code | Attention |
|---|---|---|---|
| Drug absent from canonical dataset | `UNSUPPORTED_DRUG` | `DRUG_NOT_IN_CANONICAL_DATASET` | `NOT_ASSESSED` |
| Phenotype not supplied for a relevant gene | `INSUFFICIENT` | `PHENOTYPE_NOT_PROVIDED` | `NOT_ASSESSED` |
| Phenotype outside the supported model | `UNSUPPORTED_PHENOTYPE` | `PHENOTYPE_NOT_SUPPORTED` | `NOT_ASSESSED` |
| No validated rule for the axis | `INSUFFICIENT` | `NO_VALIDATED_RULE_FOR_AXIS` | `NOT_ASSESSED` |
| Some axes covered, others not, no finding | `PARTIAL` | `SOME_AXES_NOT_COVERED` | `NOT_ASSESSED` |
| Some axes covered with a finding, others not | `PARTIAL` | `SOME_AXES_NOT_COVERED` | the calculated level, with coverage still `PARTIAL` |
| Validated rules conflict | `SOURCE_CONFLICT` | `VALIDATED_RULES_CONFLICT` | never the lower level (`SAFETY-INV-008`) |
| Evidence reference unresolvable | `INSUFFICIENT` | `EVIDENCE_REFERENCE_MISSING` | `NOT_ASSESSED` |
| Full coverage, no applicable finding | `FULL` | *(none)* | `NO_ACTIVE_ATTENTION` |

`NO_ACTIVE_ATTENTION` is reachable **only** from `FULL` coverage. Every other
absence path terminates in `NOT_ASSESSED`.

Language rule: `NOT_ASSESSED` must be rendered as *"not assessed / outside
current scope"*, never as *"low"*, *"no risk"*, *"düşük"*, or
*"uyarı yok"*. The legacy label `"Düşük / uyarı yok"` (`risk_engine.py`)
violates this and is retired at WP-15.

## 5. Risk and coverage separation

Attention and coverage are **two independent first-class outputs**. Neither
may be derived from, folded into, or displayed as a substitute for the other.

- Attention answers: *given what we could evaluate, what stands out?*
- Coverage answers: *how much of the question could we evaluate at all?*

Requirements:

- both appear at axis, medication, and overall level;
- both are present in every API response, structured report, and UI view;
- a UI must never render an overall attention level without the coverage
  status adjacent to it;
- coverage is derived from the ruleset coverage manifest, never inferred from
  the mere presence of a chemical row (`architecture.md` section 9.2);
- `NOT_ASSESSED` is excluded from any maximum, average, or sort that would
  place it on the `LOW`-`HIGH` scale.

## 6. Fields the LLM may not change

Under `SAFETY-INV-002`, the optional renderer receives only the
`StructuredReport` and may not alter, omit, or invent:

| Immutable field group | Examples |
|---|---|
| Identity | `assessment_id`, `input_hash`, `output_hash` |
| Release bundle | `release_id`, `software_version`, `dataset_version`, `ruleset_version` |
| Clinical facts | `overall_attention`, `overall_coverage`, per-medication `attention`, `coverage`, `coverage_reasons` |
| Finding facts | `gene`, `phenotype`, `attention`, `effect_code`, `explanation_code` |
| Traceability | `rule_id`, `rule_version`, `evidence_refs` |
| Mandatory text | the canonical warning; version metadata block |

The LLM may only reorder, summarise, and translate prose *around* these
values. It may not add a drug, a dose, a contraindication, a comparison, or a
safety statement. Post-processing verifies that every entity in the output
exists in the input; any failure returns the deterministic report.
`ENABLE_LLM_REPORTS=false` is the default.

## 7. Candidate exploration limits

Under `SAFETY-INV-005`, and only from P1-02 onward:

**Permitted:** listing candidates that share a therapeutic context or drug
class in the seed graph; showing, per candidate, whether the chemical is in
the canonical dataset, whether a validated rule exists, and the resulting
coverage status, reason code, and attention level; stating plainly that the
absence of a rule is a data limitation.

**Prohibited:** any safety ranking or ordering by attention level; any
numeric suitability, safety, or eligibility score - including the legacy
0-100 `MVP alternatif uygunluk ön skoru`, removed under `LEGACY-BUG-009`;
the words safer / preferred / suitable / better / clinically equivalent
applied to a candidate; presenting a manual CSV lookup as graph traversal
(`LEGACY-BUG-008`); implying that a candidate with no rule is lower risk.

Note: the legacy score *name* itself carries a suitability claim
(`uygunluk`). It is short enough that the lexical scanner does not flag it as
a sentence-level claim - a concrete illustration of section 3.1's limits. It
is prohibited by this contract regardless of scanner behaviour.

## 8. Validation and holdout separation

Under `SAFETY-INV-009` (`architecture.md` section 12.1):

| Role | May inform rule design? | May tune code? | Reported separately? |
|---|---|---|---|
| `DEVELOPMENT` | Yes | Yes | Yes |
| `INTERNAL_HOLDOUT` | No | No before freeze | Yes |
| `EXPERT_HOLDOUT` | No | No | Yes, blind protocol |

- The six current demo profiles are **development/regression seeds only** and
  may never be presented as validation evidence.
- The target is at least 50 serious cases, preferably 100+. Case count alone
  is not evidence of clinical validity.
- Expert holdout payloads are loaded from restricted storage during an
  authorised run; the repository may hold only the schema and an import stub.
- No aggregate metric may pool roles or hide a zero denominator.
- Once a holdout case is seen by a rule author, it is development data
  permanently.

## 9. Audit and version traceability

Under `SAFETY-INV-007` and `SAFETY-INV-012` (`architecture.md` section 13):

Every assessment, release activation, rollback, rule state transition,
curation approval, and review submission writes an append-only audit record:
actor and role; UTC timestamp and request/correlation ID; action and object
identity; input and output hashes where applicable; software, dataset,
ruleset, and release IDs; previous and new state for governed transitions;
success/failure code.

Audit records are append-only at the application level. A result whose audit
record is incomplete is not a valid result. Version identifiers must be
resolvable to an immutable artifact manifest; counts shown to users are
generated from that manifest, never from a stale summary file
(`LEGACY-BUG-007`).

## 10. Legacy warning inventory and canonical migration target

WP-00 **records** these strings. It does not edit, delete, or merge them.
Legacy modules stay byte-identical until WP-01 captures reproducible
snapshots (`architecture.md` section 4.1).

### 10.1 Inventory

| # | Location | Constant / site | Text (abridged) | Notes |
|---|---|---|---|---|
| L-01 | `risk_engine.py` L43-47 | `CLINICAL_WARNING_TR` | "Bu çıktı klinik karar, doz önerisi veya tedavi önerisi değildir. ClinPGx kaynaklı veriler ve sentetik CYP profilleri ... MVP dikkat bayrağıdır." | Reference variant |
| L-02 | `gemini_report_generator.py` L53-57 | `CLINICAL_WARNING_TR` | *identical to L-01* | **Duplicated constant**, not imported |
| L-03 | `candidate_onboarding.py` L34-36 | `SAFETY_NOTICE` | "Bu rapor klinik karar, doz önerisi veya tedavi değişikliği önerisi değildir. Aday ilaçlar yalnızca MVP veri setinde değerlendirilebilir hale getirme amacıyla incelenmiştir." | "Bu rapor" not "Bu çıktı"; adds *tedavi değişikliği*; **drops** provenance/synthetic-data sentence |
| L-04 | `alternative_ranker.py` L40-46 | `SAFETY_NOTICE` | "Bu bölümde listelenen alternatifler tedavi önerisi değildir. ... Doz, ilaç değişimi veya tedavi kararı yalnızca hekim tarafından klinik tablo, endikasyon, laboratuvar değerleri ve güncel kılavuzlar dikkate alınarak verilmelidir." | Only variant that names the clinician and the decision inputs; scoped to "bu bölüm" |
| L-05 | `candidate_onboarding.py` L38-41 | `CHEMICAL_RESOLVE_NOTICE` | "Adayın ClinPGx chemical olarak çözülmesi, o adayın farmakogenetik açıdan düşük riskli olduğu anlamına gelmez." | A `SAFETY-INV-001` statement |
| L-06 | `candidate_onboarding.py` L44-47 | `NO_RULE_NOTICE` | "Bu aday ClinPGx chemical olarak çözüldü; ancak mevcut MVP seed kapsamında farmakogenetik phenotype rule bulunamadı." | Purely factual; **no** safety framing - weakest of the set |
| L-07 | `alternative_ranker.py` L48-52 | `DATA_LIMIT_NOTICE` | "... Bu nedenle düşük riskli olduğu sonucuna varılamaz ..." | `SAFETY-INV-001` statement |
| L-08 | `alternative_ranker.py` L54-58 | `INSUFFICIENT_PGX_RULE_NOTICE` | "... adayın farmakogenetik açıdan düşük dikkatli olduğu sonucu çıkarılamaz." | Uses *dikkatli*, not *riskli* - third vocabulary |
| L-09 | `alternative_ranker.py` L60-63 | `UNSUPPORTED_CANDIDATE_NOTICE` | "... düşük dikkatli olduğu sonucu çıkarılamaz. Skor yalnızca graph bağlamında aday bulunduğunu ... gösterir." | Defends the score that `LEGACY-BUG-009` deletes |
| L-10 | `alternative_ranker.py` L65 | `SCORE_NAME` | "MVP alternatif uygunluk ön skoru" | **Prohibited label** (*uygunluk* = suitability); retire under `LEGACY-BUG-009` |
| L-11 | `risk_engine.py` L27-29 | module docstring | "Bu script klinik karar, doz önerisi veya tedavi önerisi üretmez." | Diacritics present |
| L-12 | `candidate_onboarding.py` L9-10 | module docstring | "Bu script klinik karar, doz onerisi, tedavi degisikligi onerisi veya PGx risk kurali uretmez." | **ASCII, no diacritics** |
| L-13 | `alternative_ranker.py` L8-9 | module docstring | "Bu script klinik karar, doz onerisi veya tedavi degisikligi onerisi uretmez." | **ASCII, no diacritics** |
| L-14 | `gemini_report_generator.py` L191-204 | `SYSTEM_INSTRUCTION` | Prompt rules incl. "Her raporda açıkça şu uyarı yer almalı: Bu çıktı klinik karar, doz önerisi veya tedavi önerisi değildir." | **Truncated warning**: first sentence only, provenance sentence lost |
| L-15 | `gemini_report_generator.py` L338 | fallback report line | "Bu rapor ... MVP raporlama katmanıdır; klinik karar yerine geçmez." | Additional wording, not in any constant |
| L-16 | `gemini_report_generator.py` L426-430 | fallback "Sınırlar" block | 5 bullets: not validated on real patient data; no dose/treatment/alternative recommendation; synthetic profile; limited scope; no DDI claim | Richest limitation text; exists only in the fallback path |
| L-17 | `candidate_onboarding.py` L909-913 | report "Veri Kısıtları" | 5 bullets on rule/label separation | Report-only |
| L-18 | `alternative_ranker.py` L504-508 | report "Veri Kısıtları" | 5 bullets incl. "Skor klinik güvenlik değerlendirmesi değildir" | Report-only |
| L-19 | `risk_engine.py` L683-685, L862-865, L876-881 | Gemini prompt hints / `avoid` list | "doz önerisi verme", "tedavi değişikliği önerme", "kesin klinik hüküm verme" | Prompt-side control, unversioned |
| L-20 | `gemini_report_generator.py` L514-519 | post-hoc injection | Prepends the warning if `"klinik karar"` **or** `"doz önerisi"` is absent from the model output | Substring check; a paraphrased report passes it trivially |

### 10.2 Recorded differences

1. **Duplication without a shared source.** L-01 and L-02 are byte-identical
   constants in two modules. Editing one silently diverges the product.
2. **Four different subjects.** "Bu çıktı" (L-01), "Bu rapor" (L-03),
   "Bu bölümde listelenen alternatifler" (L-04), "Bu script" (L-11..L-13).
   Scope of the disclaimer differs each time.
3. **Inconsistent prohibition set.** L-01 covers decision/dose/treatment;
   L-03 adds *treatment change*; L-04 covers treatment recommendation plus a
   clinician-deferral clause. No variant covers diagnosis, safety
   declaration, candidate preference, or real-data exclusion.
4. **Provenance sentence lost.** The "ClinPGx-sourced data + synthetic CYP
   profiles" clause exists in L-01/L-02 but is dropped in L-03, L-04, and the
   prompt copy L-14.
5. **Three vocabularies for the same idea.** *düşük riskli* (L-05, L-07),
   *düşük dikkatli* (L-08, L-09), *Düşük / uyarı yok* (`RISK_LABEL_TR`).
6. **Encoding drift.** L-11 has Turkish diacritics; L-12 and L-13 are ASCII.
   Any lexical control must fold diacritics - `scan_claim_text()` does.
7. **Truncation in the LLM path.** L-14 mandates only the first sentence, so
   the LLM report can legally omit the provenance and scope wording.
8. **Fragile enforcement.** L-20 checks for two substrings; it neither
   validates content nor detects prohibited language.
9. **A prohibited label survives.** L-10 asserts *suitability*, contradicting
   `SAFETY-INV-005`, while L-09 exists to explain the score away.
10. **No versioning.** No warning carries a version, an owner, or an approval
    record, so no report can state which warning text it was released under.

### 10.3 Canonical migration target

`CANONICAL_CLINICAL_WARNING_TR` / `_EN` in `pgx/domain/claims.py`, read via
`canonical_clinical_warning(language)`, is the single target. It restores the
provenance clause, adds diagnosis, adds the explicit
`missing data != low risk` sentence, and keeps L-04's clinician-deferral
clause - the strongest element of the legacy set.

Migration rules:

- **WP-00 (now):** document only. Legacy strings remain untouched and
  unmerged. `tests/unit/test_claims.py` asserts that every legacy warning
  still passes the canonical scanner and that the legacy texts still differ
  from each other and from the canonical text.
- **WP-01:** snapshot legacy outputs *including* these strings, so the
  wording change is a whitelisted, visible difference rather than a silent
  one.
- **WP-15:** the deterministic report emits the canonical text through
  `canonical_clinical_warning()`; L-16's limitation bullets are re-expressed
  as structured coverage reasons and version metadata rather than prose.
- **WP-16/WP-17:** API and UI read the same function; no layer defines a
  warning string.
- **P1-06:** the LLM prompt carries the full canonical text, and the
  post-processor asserts its literal presence instead of a substring probe.
- Legacy modules are edited only when their owning migration WP retires
  them (`architecture.md` section 4.1).

## 11. Human review checklist and approval record

**Status: DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW.** No row below may be
completed by an implementation agent.

### 11.1 Reviewer checklist

Safety principles and invariants:

- [ ] The ten principles in section 1 match `architecture.md` section 3 and
      are complete for this product.
- [ ] `SAFETY-INV-001` through `SAFETY-INV-012` are each necessary, testable,
      and correctly assigned to an enforcing layer.
- [ ] No invariant is claimed as verified while its owning WP is unstarted.
- [ ] The fail-closed rule is acceptable for every listed enforcement point.
- [ ] Additional invariants required by the reviewers are recorded here
      before Gate C.

Claim boundary:

- [ ] The prohibited-claim categories in section 3 cover every clinical claim
      this product could plausibly be read as making.
- [ ] The scanner's stated limits (section 3.1) are acknowledged, and the
      scanner is nowhere presented as scientific validation.
- [ ] The canonical warning text is scientifically and linguistically correct
      in Turkish and English.

Behavioural contracts:

- [ ] The missing-data table in section 4 is complete and clinically
      defensible for every reason code.
- [ ] The risk/coverage separation rules in section 5 are enforceable in the
      planned UI.
- [ ] The LLM immutable-field list in section 6 is complete.
- [ ] The candidate limits in section 7 remove every safety-preference
      reading, including the legacy score.
- [ ] The validation/holdout separation in section 8 is workable with the
      available reviewers.
- [ ] The audit fields in section 9 satisfy the traceability claim.

Legacy migration:

- [ ] The inventory in section 10.1 is complete; no user-facing warning was
      missed.
- [ ] The differences in section 10.2 are accepted as the migration rationale.
- [ ] The canonical target in section 10.3 loses no safety content present in
      any legacy variant.

### 11.2 Approval record

| Role | Name | Affiliation | Decision | Date | Signature / record reference |
|---|---|---|---|---|---|
| Product / technical owner | *(pending)* | | *(pending)* | | |
| Scientific advisor (pharmacogenetics / clinical pharmacology) | *(pending)* | | *(pending)* | | |
| Risk management owner | *(pending)* | | *(pending)* | | |
| Independent reviewer (recommended) | *(pending)* | | *(pending)* | | |

Until every row is completed by the named person, this contract is a
**proposal**. `CLAIM_BOUNDARY_STATUS` in `pgx/domain/claims.py` must continue
to read `DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW`, and
`P0_CLAIM_BOUNDARY.is_approved` must remain `False`.

## 12. Change control

Changes to the invariant registry, the prohibited-claim categories, the
missing-data contract, the risk/coverage semantics, the LLM immutability
rules, the candidate limits, or the validation-role separation require an
Architecture Decision Record under `docs/architecture/decisions/`
(`architecture.md` section 23), plus re-approval of section 11.2.
