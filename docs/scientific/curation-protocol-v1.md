# Scientific curation protocol v1 (WP-09)

| Field | Value |
|---|---|
| Document ID | `DOC-SCI-009` |
| Protocol version | `pgx-curation-protocol/1` |
| Content hash | `sha256:e0a76f45b0f606e4fd76d4c31829fcd61825278b01e407b71c13fc38298b56d6` |
| Status | **`AWAITING_EXPERT_REVIEW`** |
| Machine-readable form | [`config/curation/protocol-v1.json`](../../config/curation/protocol-v1.json) |

> **This protocol has not been scientifically approved.** Every vocabulary and
> definition in it is `DRAFT / AWAITING EXPERT REVIEW` until a named scientist
> records an approval against the content hash above. Nothing here is settled
> science, and nothing produced under it may be used to assess a person.

---

## 1. What this protocol governs

The fourth stage of the pipeline:

```
RawArtifact -> Canonical Entity -> EvidenceRecord ->
CuratedInterpretation -> ComputableRule
      WP-06         WP-07            WP-08
                                            ^^^^^^^^^^^^^^^^^^^^^^
                                            WP-09 defines this contract
```

WP-08 recorded what sources stated. This protocol defines what it means for a
human to reach a conclusion about that evidence, and refuses conclusions that
would not withstand review.

**It does not run a workflow.** No database row is written, no state transition
is enforced, no authorization is checked, and no `CuratedInterpretation` is
created. WP-10 owns the workflow; WP-11 owns rules.

## 2. Source fact versus curator conclusion

The central separation. An evidence record says:

```json
{"significance": {"term": "yes"}, "score": 3.75, "polarity": "..."}
```

Those are ClinPGx's fields, meaning what ClinPGx defined them to mean. In this
protocol they are held in `SourceReportedValues` **for comparison only**.

| Never | Because |
|---|---|
| `significance=yes` → `SUPPORTED` | The source's flag answers the source's question, not this project's. |
| `score=3.75` → confidence | A ClinPGx score is not a probability, a strength, or a risk. |
| `polarity` → direction of patient risk | Polarity describes an association's sign, not a clinical consequence. |

A curator concluding `SUPPORTED` must explain in the rationale **how the
selected evidence supports it**. Repeating the source's flag is not that
explanation, and a rationale that does only that is rejected as circular.

## 3. The unit of curation

A **curation question**, not a gene/drug pair:

| Axis | Required | Note |
|---|---|---|
| Gene canonical key | yes | `GENE:CYP2C19` |
| Drug canonical key | yes | `DRUG:clopidogrel` |
| Effect dimension | yes | one controlled member |
| Question text | yes | the exact question, in words |
| Phenotype scope | no | exact `Phenotype` members; empty is **not** a wildcard |
| Population context | no | absent means unstated, not universal |

A pair-level conclusion is **not** applied to every annotation sharing that
pair. That is the legacy defect this protocol exists to stop: the previous seed
produced 3,084 rows from pair-level overrides applied broadly.

If the granularity cannot be determined, the answer is `INSUFFICIENT` or
`NOT_INTERPRETABLE` — never a broad default.

## 4. Controlled vocabularies

Eleven, all **non-ordered**, none carrying a number. Comparing two members
raises `VocabularyError`: `INSUFFICIENT` is not a low `SUPPORTED`, and a scale
would let a later stage sort these into a severity.

| Vocabulary | Members |
|---|---|
| `InterpretationStatus` | DRAFT, UNDER_REVIEW, CURATED, REJECTED |
| `ConclusionState` | SUPPORTED, CONFLICTING, INSUFFICIENT, NOT_INTERPRETABLE, OUT_OF_SCOPE, NOT_APPLICABLE |
| `EvidenceRelationship` | SUPPORTS, CONTRADICTS, CONTEXT_ONLY, EXCLUDED |
| `Applicability` | APPLICABLE, PARTIALLY_APPLICABLE, NOT_APPLICABLE, UNCLEAR |
| `ConflictState` | NONE_IDENTIFIED, PRESENT, UNRESOLVED, ADJUDICATION_REQUIRED |
| `EffectDimension` | EXPOSURE, CLEARANCE, ACTIVATION, RESPONSE_ASSOCIATION, ADVERSE_EVENT_ASSOCIATION, FUNCTIONAL_ACTIVITY, OTHER, INSUFFICIENT_TO_CLASSIFY |
| `ExclusionReason` | nine controlled reasons (§6) |
| `CurationRole` | six roles (§8) |
| `CaseRole` | TRAINING, CALIBRATION, DEVELOPMENT, INTER_CURATOR_EXERCISE, INTERNAL_HOLDOUT, EXPERT_HOLDOUT |
| `LegacyReviewState` | six states (§9) |
| `ProtocolStatus` | DRAFT, AWAITING_EXPERT_REVIEW, APPROVED, REJECTED, SUPERSEDED |

**Effect dimensions are neutral.** They name what was observed to differ, never
what to do about it. There is no member for a dose, an avoidance, a preference
or a risk level, and adding one would require changing this document.

**Phenotypes reuse `pgx.domain.enums.Phenotype` unchanged.** `RAPID` and
`ULTRARAPID` are distinct members and a scope covering both must list both
(`SAFETY-INV-004`).

**There is no numeric judgement anywhere.** No confidence, strength, quality,
safety or severity score. A number invites arithmetic, and arithmetic over
scientific judgement produces a result nobody reviewed.

## 5. Evidence selection

Every conclusion cites at least one `EvidenceRecord`. Each citation carries:

- the evidence record UUID and natural key;
- its relationship to the conclusion;
- a written rationale — for inclusions as well as exclusions;
- the source version status, provider and origin source;
- trace-verification status (null means *not checked*, which is not *checked
  and fine*);
- relevant fragment and publication identifiers.

**Excluded evidence stays in the record**, with one of nine controlled reasons:
`WRONG_ENTITY`, `WRONG_PHENOTYPE_SCOPE`, `WRONG_POPULATION`,
`DUPLICATE_SOURCE_RECORD`, `SUPERSEDED_SOURCE_VERSION`, `INSUFFICIENT_DETAIL`,
`OUT_OF_SCOPE`, `UNRESOLVED_PROVENANCE`, `OTHER_WITH_RATIONALE`.

None of these may be applied automatically. **Evidence is never excludable
for**: contradicting the conclusion, being older, coming from a different
guideline organisation, or having an unknown version. Those conditions stay
visible and argued.

A conclusion whose every citation is excluded is refused: excluding everything
is a finding of `INSUFFICIENT`, recorded as one.

## 6. The rationale contract

Reaching `CURATED` requires eleven named parts, each substantive:

`curation_question`, `selected_evidence`, `excluded_evidence`,
`source_to_conclusion`, `phenotype_normalization`, `effect_normalization`,
`significance_explanation`, `applicability_statement`, `conflict_assessment`,
`uncertainty_and_limitations`, `missing_data_statement` — plus a named author,
a distinct named independent reviewer, both timestamps, and the protocol
version.

These are **rejected**:

| Rejected | Why |
|---|---|
| "copied from legacy" | The legacy value is what is under review. |
| "MANUAL_EFFECT_HINTS says so" | A hint is not evidence. |
| "the score is high" | A source's score is not an argument. |
| "the AI selected it" | No machine is a curator here. |
| "this is clinically known" | Without a citation, this is an appeal to authority. |
| blank or whitespace | Nothing was explained. |
| a restatement of the conclusion | Circular: `source_to_conclusion` must add reasoning. |

Circularity is measured on significant words, so reordering the conclusion does
not evade it.

## 7. Conflict handling

**There is no precedence rule.** No CPIC-wins, no DPWG-wins, no label-wins, no
newer-wins, no higher-score-wins. There is no precedence field in
`ConflictAnalysis`, and a test reads the module's identifiers and fails if one
appears. WP-05 took this position for source conflicts; this is the same
position one stage later, for the same reason: a global precedence order
silently answers every future disagreement using a judgement made once in a
different context.

A recorded conflict preserves every conflicting record, the disputed field, the
source versions, applicability differences, materiality, the curator's analysis,
and whether adjudication is required.

`CONFLICTING` is a **reviewed conclusion**. It does not resolve the underlying
disagreement, and it does not mean "no risk" (`SAFETY-INV-008`).

An unresolved material conflict — `UNRESOLVED`, `ADJUDICATION_REQUIRED`, or
`PRESENT` and material — **blocks rule construction** and cannot back a
`SUPPORTED` conclusion. Resolution requires a named human with written reasons.
WP-09 states this requirement; WP-10 performs the workflow.

## 8. Insufficiency

`INSUFFICIENT` is a first-class answer. It must state:

- what information is missing;
- which evidence was reviewed (an empty list is refused — otherwise it cannot
  be told apart from nobody having looked);
- why no stronger conclusion is supported;
- what scope remains unresolved;
- whether more evidence or adjudication is required.

It may **never** be represented as low risk, no risk, no effect, safe, normal,
or negative evidence (`SAFETY-INV-001`). Both the conclusion text and the
statement itself are screened for reassuring language, because the vocabulary
can be respected while the prose beside it says "so this is probably fine".

Unknown source version, unknown origin and quarantined evidence stay visible.
They are not hidden behind a confidence label — there is no confidence label.

## 9. Roles

| Role | Authors | Reviews | Approves science | Adjudicates |
|---|:-:|:-:|:-:|:-:|
| Protocol Owner | – | – | – | – |
| Scientific Curator | yes | – | yes | – |
| Independent Scientific Reviewer | – | yes | yes | – |
| Adjudicator | – | yes | yes | yes |
| Data/Provenance Steward | – | – | – | – |
| Engineering Observer | – | – | – | – |

- **Author and independent reviewer must be different people.** The default
  protocol rule, enforced case-insensitively at construction.
- **An engineering role alone cannot approve scientific meaning.** Neither can
  the protocol owner, nor the provenance steward. Confirming the pipeline is
  sound is a different claim from the science being right.
- **There is no machine curator role.** No member of `CurationRole` names an
  AI, LLM, model or automated system, and adding one would require changing
  this document in the open.
- **Placeholder names are treated as absence.** `TEST_REVIEWER`, `team`,
  `scientific advisor`, `anonymous`, `system`, `Claude` and thirty others are
  refused — not as weak identity, but as none.
- **An adjudicator preserves both original responses.** An adjudication that
  replaced them would erase the disagreement it settled.

## 10. Case separation

One case holds exactly one role (`SAFETY-INV-009`).

| Rule | Statement |
|---|---|
| `one_role_per_case` | Two roles would let a holdout result be reported as independent after informing development. |
| `development_and_holdout_disjoint` | DEVELOPMENT, INTERNAL_HOLDOUT and EXPERT_HOLDOUT are mutually exclusive. |
| `legacy_and_demo_are_development` | Legacy hints and demo profiles shaped the code; they are DEVELOPMENT or TRAINING only. |
| `derived_cases_are_not_external` | A case built from the current evidence set is not independent external validation, whatever it is labelled. |
| `no_expected_answers_in_blind_packets` | A packet carries no expected answer, and no response may be generated from one. |
| `no_machine_curator` | A language model cannot serve as an independent scientific curator. |

WP-18 owns the full validation-dataset architecture. WP-09 defines only the
curation-facing separation rule.

## 11. Requirement map

Every obligation, mapped to where it is implemented, which schema field carries
it, which validation code reports its absence, and which test proves it. A
requirement missing any of those is a principle nobody enforces, and the
validator refuses the document.

| ID | Requirement | Implementation | Schema field | Validation code | Test |
| --- | --- | --- | --- | --- | --- |
| `CUR-PROT-001` | Source facts and curator conclusions are separate objects | `models.SourceReportedValues<br>models.CurationRecordDraft` | `source_reported` | `CUR_SOURCE_CONCLUSION_MERGED` | `TestSourceAndConclusionStaySeparate` |
| `CUR-PROT-002` | Source significance does not become a conclusion | `models.Rationale part 'significance_explanation'` | `rationale.parts.significance_explanation` | `CUR_SIGNIFICANCE_MAPPED_DIRECTLY` | `TestSourceSignificanceIsNotAConclusion` |
| `CUR-PROT-003` | A conclusion is recorded against an explicit question | `models.CurationQuestion` | `question` | `CUR_GRANULARITY_UNDEFINED` | `TestCurationGranularity` |
| `CUR-PROT-004` | Every conclusion cites at least one evidence record | `models.CurationRecordDraft.__post_init__` | `evidence` | `CUR_EVIDENCE_MISSING` | `TestEvidenceIsRequired` |
| `CUR-PROT-005` | Evidence inclusions and exclusions are both reasoned | `models.EvidenceSelection` | `evidence[].exclusion_reason` | `CUR_EXCLUSION_UNREASONED` | `TestExclusionsAreReasoned` |
| `CUR-PROT-006` | Contradictory evidence is retained, never dropped | `models.CurationRecordDraft._check_conclusion_consistency` | `evidence[].relationship` | `CUR_CONTRADICTION_HIDDEN` | `TestContradictoryEvidenceIsRetained` |
| `CUR-PROT-007` | No source has precedence | `models.ConflictAnalysis (no precedence field exists)` | `conflict` | `CUR_SOURCE_PRECEDENCE_ENCODED` | `TestNoSourcePrecedence` |
| `CUR-PROT-008` | Unresolved material conflict blocks rule construction | `models.ConflictAnalysis.blocks_rule_construction` | `conflict.blocks_rule_construction` | `CUR_CONFLICT_NOT_BLOCKING` | `TestUnresolvedConflictBlocksRules` |
| `CUR-PROT-009` | INSUFFICIENT is never reassurance | `models.InsufficiencyStatement<br>models.find_reassuring_language` | `insufficiency` | `CUR_INSUFFICIENT_AS_REASSURANCE` | `TestInsufficientIsNotLowRisk` |
| `CUR-PROT-010` | A CURATED conclusion requires a structured, non-placeholder rationale | `models.Rationale` | `rationale.parts` | `CUR_RATIONALE_PLACEHOLDER` | `TestRationaleContract` |
| `CUR-PROT-011` | Author and independent reviewer are different people | `models.Rationale.__post_init__` | `rationale.reviewed_by` | `CUR_ROLE_SEPARATION_MISSING` | `TestAuthorReviewerSeparation` |
| `CUR-PROT-012` | An engineering role cannot approve scientific meaning | `vocabulary.SCIENTIFIC_APPROVAL_ROLES<br>protocol.ROLE_DEFINITIONS` | `roles[].may_approve_science` | `CUR_ENGINEERING_APPROVAL` | `TestOnlyScientificRolesApprove` |
| `CUR-PROT-013` | Adjudication preserves both original responses | `exercises.AdjudicationTemplate` | `adjudication.preserved_responses` | `CUR_ADJUDICATION_REPLACES_RESPONSES` | `TestAdjudicationPreservesResponses` |
| `CUR-PROT-014` | One case holds exactly one role | `protocol.check_case_separation<br>CASE_ROLE_RULES` | `cases[].role` | `CUR_CASE_ROLE_OVERLAP` | `TestCaseSeparation` |
| `CUR-PROT-015` | Legacy manual hints stay unreviewed until a human reviews them | `legacy_review.build_review_inventory` | `proposals[].review_state` | `CUR_LEGACY_AUTO_REVIEWED` | `TestLegacyHintsStayUnreviewed` |
| `CUR-PROT-016` | Legacy hints are blinded during initial evidence review | `exercises.build_exercise_packet` | `cases[].legacy_hint_blinded` | `CUR_LEGACY_HINT_NOT_BLINDED` | `TestLegacyHintsAreBlinded` |
| `CUR-PROT-017` | The inter-curator comparison does not adjudicate | `exercises.compare_responses` | `comparison.fields` | `CUR_COMPARISON_ADJUDICATES` | `TestComparisonDoesNotAdjudicate` |
| `CUR-PROT-018` | A comparison requires two genuinely completed responses | `exercises.CuratorResponse.is_complete<br>exercises.compare_responses` | `responses[].completed` | `CUR_COMPARISON_INCOMPLETE_INPUT` | `TestComparisonRequiresCompletedResponses` |
| `CUR-PROT-019` | No numeric risk, confidence or safety score exists | `models.PROHIBITED_CURATION_FIELDS` | `-` | `CUR_NUMERIC_SCORE_PRESENT` | `TestNoNumericJudgement` |
| `CUR-PROT-020` | No executable rule or treatment field exists | `models.PROHIBITED_CURATION_FIELDS` | `-` | `CUR_EXECUTABLE_FIELD_PRESENT` | `TestNoExecutableOrPrescriptiveFields` |
| `CUR-PROT-021` | RAPID and ULTRARAPID stay distinct | `pgx.domain.enums.Phenotype<br>models.CurationQuestion.phenotype_scope` | `question.phenotype_scope` | `CUR_PHENOTYPE_COLLAPSED` | `TestRapidAndUltrarapidStayDistinct` |
| `CUR-PROT-022` | Every controlled field has an owner and a null meaning | `fields.FIELD_DICTIONARY` | `fields[]` | `CUR_FIELD_DEFINITION_MISSING` | `TestFieldDictionaryIsComplete` |
| `CUR-PROT-023` | Protocol approval requires genuine named metadata | `protocol.ApprovalRecord` | `approval` | `CUR_APPROVAL_METADATA_INCOMPLETE` | `TestApprovalMetadataIsGenuine` |
| `CUR-PROT-024` | Technical completeness and expert approval are reported apart | `validation.validate_protocol` | `report.expert_approval` | `CUR_APPROVAL_ABSENT` | `TestCompletenessAndApprovalAreSeparate` |
| `CUR-PROT-025` | Exercise cases reference real, traceable evidence | `exercises.build_exercise_packet` | `cases[].evidence_record_uuids` | `CUR_EXERCISE_EVIDENCE_MISSING` | `TestExerciseReferencesRealEvidence` |

Checklist wording for each is in
[curation-review-checklist.md](curation-review-checklist.md).

## 12. What must remain blocked

| Blocked | Requires |
|---|---|
| Protocol approval | A named scientist reading it and recording an approval against the content hash. |
| The inter-curator exercise | Two named scientific curators completing it independently. |
| A comparison and adjudication record | Those two responses, then a named adjudicator. |
| Any legacy hint accepted or rejected | A named human reviewing that hint. |
| Any `CuratedInterpretation` row | WP-10's workflow, over an approved protocol. |
| Any computable rule | WP-11, over approved interpretations. |

`pgx-curation-protocol approval-status` reports these and exits non-zero.
