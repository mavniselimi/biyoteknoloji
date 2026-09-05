# Curation review checklist (WP-09)

| Field | Value |
|---|---|
| Document ID | `DOC-SCI-011` |
| Protocol | `pgx-curation-protocol/1` (`AWAITING_EXPERT_REVIEW`) |

Read alongside [curation-protocol-v1.md](curation-protocol-v1.md). Each line
cites the validation code that refuses the failure and the test that proves the
refusal, so a reviewer can tell which items a machine already checked and which
need a person.

> A checked box is not an approval. Approval is a named scientist recording a
> decision against the protocol's content hash.

---

## A. Before reviewing a conclusion

- [ ] I am not the author of this conclusion.
- [ ] I have read the cited evidence myself, not only the curator's summary.
- [ ] I have not seen the legacy project's previous answer for this question,
      if this is an exercise case.

## B. The question

- [ ] The question names a gene, a drug and an effect dimension, not just a
      gene/drug pair.
- [ ] Phenotype scope, where given, uses exact members. `RAPID` and
      `ULTRARAPID` are both listed if both are meant.
- [ ] An empty phenotype scope is intended as *unscoped*, not as *all*.
- [ ] The population context is stated, or its absence is deliberate.

## C. The evidence

- [ ] Every cited record exists in the sealed evidence build.
- [ ] Every inclusion has a rationale that says why *this* record bears on
      *this* question.
- [ ] Every exclusion has a controlled reason **and** a written rationale.
- [ ] No record was excluded for contradicting, for being older, for coming
      from another organisation, or for having an unknown version.
- [ ] Contradicting evidence, if any, is still present and assessed.
- [ ] Source version status and origin are carried from the evidence record
      unchanged.
- [ ] Where trace verification is null, I read that as *not checked*.

## D. The conclusion

- [ ] The conclusion follows from the cited evidence, not from the source's own
      significance flag or score.
- [ ] The effect dimension describes what differs, not what to do.
- [ ] Nothing in the record scores, ranks or weights a scientific judgement.
- [ ] Nothing in the record could be executed or read as clinical advice.
- [ ] If `INSUFFICIENT`: it states what is missing and reads as absence of
      knowledge, not absence of risk.
- [ ] If `CONFLICTING`: every conflicting record is preserved, and the text
      does not suggest the disagreement is harmless.
- [ ] No source was preferred by rule rather than by argument.

## E. The rationale

- [ ] All eleven parts are present and substantive.
- [ ] `source_to_conclusion` explains the reasoning; it does not restate the
      conclusion or cite the source's flag.
- [ ] Phenotype and effect normalisation are each explained.
- [ ] Uncertainty, limitations and missing data are stated rather than implied.
- [ ] The author is a named person, and I am a different named person.

## F. Protocol requirements

- [ ] **CUR-PROT-001** — Does the record keep the source's own reported values apart from the curator's conclusion?
      <sub>Refuses via `CUR_SOURCE_CONCLUSION_MERGED`. Verified by `TestSourceAndConclusionStaySeparate`.</sub>
- [ ] **CUR-PROT-002** — Does the rationale explain the conclusion rather than repeat the source's significance flag?
      <sub>Refuses via `CUR_SIGNIFICANCE_MAPPED_DIRECTLY`. Verified by `TestSourceSignificanceIsNotAConclusion`.</sub>
- [ ] **CUR-PROT-003** — Is the exact question stated, including phenotype scope and effect dimension?
      <sub>Refuses via `CUR_GRANULARITY_UNDEFINED`. Verified by `TestCurationGranularity`.</sub>
- [ ] **CUR-PROT-004** — Does every conclusion cite real evidence record identifiers?
      <sub>Refuses via `CUR_EVIDENCE_MISSING`. Verified by `TestEvidenceIsRequired`.</sub>
- [ ] **CUR-PROT-005** — Is every exclusion given a controlled reason and a written rationale?
      <sub>Refuses via `CUR_EXCLUSION_UNREASONED`. Verified by `TestExclusionsAreReasoned`.</sub>
- [ ] **CUR-PROT-006** — Is contradicting evidence still present and assessed?
      <sub>Refuses via `CUR_CONTRADICTION_HIDDEN`. Verified by `TestContradictoryEvidenceIsRetained`.</sub>
- [ ] **CUR-PROT-007** — Has any source been preferred by rule rather than by argument?
      <sub>Refuses via `CUR_SOURCE_PRECEDENCE_ENCODED`. Verified by `TestNoSourcePrecedence`.</sub>
- [ ] **CUR-PROT-008** — Does an unresolved material conflict stop this conclusion reaching a rule?
      <sub>Refuses via `CUR_CONFLICT_NOT_BLOCKING`. Verified by `TestUnresolvedConflictBlocksRules`.</sub>
- [ ] **CUR-PROT-009** — Does the insufficient conclusion read as absence of knowledge rather than absence of risk?
      <sub>Refuses via `CUR_INSUFFICIENT_AS_REASSURANCE`. Verified by `TestInsufficientIsNotLowRisk`.</sub>
- [ ] **CUR-PROT-010** — Does the rationale explain the reasoning rather than restate the answer?
      <sub>Refuses via `CUR_RATIONALE_PLACEHOLDER`. Verified by `TestRationaleContract`.</sub>
- [ ] **CUR-PROT-011** — Are the author and the independent reviewer different named people?
      <sub>Refuses via `CUR_ROLE_SEPARATION_MISSING`. Verified by `TestAuthorReviewerSeparation`.</sub>
- [ ] **CUR-PROT-012** — Did a scientific role, held by a named person, approve this?
      <sub>Refuses via `CUR_ENGINEERING_APPROVAL`. Verified by `TestOnlyScientificRolesApprove`.</sub>
- [ ] **CUR-PROT-013** — Are both original responses still readable after adjudication?
      <sub>Refuses via `CUR_ADJUDICATION_REPLACES_RESPONSES`. Verified by `TestAdjudicationPreservesResponses`.</sub>
- [ ] **CUR-PROT-014** — Does any case appear under two roles?
      <sub>Refuses via `CUR_CASE_ROLE_OVERLAP`. Verified by `TestCaseSeparation`.</sub>
- [ ] **CUR-PROT-015** — Has any legacy hint been accepted or rejected without a human?
      <sub>Refuses via `CUR_LEGACY_AUTO_REVIEWED`. Verified by `TestLegacyHintsStayUnreviewed`.</sub>
- [ ] **CUR-PROT-016** — Could a curator see the legacy answer before forming their own?
      <sub>Refuses via `CUR_LEGACY_HINT_NOT_BLINDED`. Verified by `TestLegacyHintsAreBlinded`.</sub>
- [ ] **CUR-PROT-017** — Does the comparison state differences without choosing a winner?
      <sub>Refuses via `CUR_COMPARISON_ADJUDICATES`. Verified by `TestComparisonDoesNotAdjudicate`.</sub>
- [ ] **CUR-PROT-018** — Were both responses completed independently by named people?
      <sub>Refuses via `CUR_COMPARISON_INCOMPLETE_INPUT`. Verified by `TestComparisonRequiresCompletedResponses`.</sub>
- [ ] **CUR-PROT-019** — Does any field score, rank or weight a scientific judgement?
      <sub>Refuses via `CUR_NUMERIC_SCORE_PRESENT`. Verified by `TestNoNumericJudgement`.</sub>
- [ ] **CUR-PROT-020** — Could anything in this record be executed or read as advice?
      <sub>Refuses via `CUR_EXECUTABLE_FIELD_PRESENT`. Verified by `TestNoExecutableOrPrescriptiveFields`.</sub>
- [ ] **CUR-PROT-021** — Does any scope treat RAPID and ULTRARAPID as one?
      <sub>Refuses via `CUR_PHENOTYPE_COLLAPSED`. Verified by `TestRapidAndUltrarapidStayDistinct`.</sub>
- [ ] **CUR-PROT-022** — Does every field say who owns it and what its absence means?
      <sub>Refuses via `CUR_FIELD_DEFINITION_MISSING`. Verified by `TestFieldDictionaryIsComplete`.</sub>
- [ ] **CUR-PROT-023** — Is there a real named scientist behind this approval?
      <sub>Refuses via `CUR_APPROVAL_METADATA_INCOMPLETE`. Verified by `TestApprovalMetadataIsGenuine`.</sub>
- [ ] **CUR-PROT-024** — Is the protocol both structurally complete and actually approved?
      <sub>Refuses via `CUR_APPROVAL_ABSENT`. Verified by `TestCompletenessAndApprovalAreSeparate`.</sub>
- [ ] **CUR-PROT-025** — Do the exercise cases point at evidence that actually exists?
      <sub>Refuses via `CUR_EXERCISE_EVIDENCE_MISSING`. Verified by `TestExerciseReferencesRealEvidence`.</sub>

## G. Before signing

- [ ] I understand that this protocol is `AWAITING_EXPERT_REVIEW` and that my
      review of a conclusion does not approve the protocol itself.
- [ ] I have recorded my name, role, the instant, and my reasons.
- [ ] Where I disagree with the author and we cannot resolve it, I have
      referred it to a named adjudicator rather than overwriting their answer.
