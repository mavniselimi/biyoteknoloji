# 16. The questions

Twelve areas. Criticism is the useful answer; agreement is the less useful
one. Nothing here is phrased to invite approval, and there is no question
asking whether the project may proceed — that is not yours to grant and not
ours to ask for.

Record your answers in
[`reviewer/05-review-questionnaire.md`](reviewer/05-review-questionnaire.md)
or in `data/expert-package/reviewer-response-template.json`. Each carries a
severity (`BLOCKING`, `MAJOR`, `MINOR`, `OBSERVATION`) and a correction
priority (`P0`…`P3`, or `NONE`).

---

**Q01-SCIENTIFIC-APPROPRIATENESS**
Is the overall scientific approach appropriate for what this software claims
to be (section 1), and where is it not? Include the case where your answer is
that a phenotype-in, attention-level-out product is the wrong shape.

**Q02-PGX-INTERPRETATION-QUALITY**
Is the pharmacogenetic interpretation of each covered axis correct, and where
would you interpret differently? The tables are in sections 6 and 8, cell by
cell.

**Q03-SOURCE-SELECTION**
Are the four approved sources the right ones for a first release (section 3),
and what is missing or should not be there? Is four drugs and two genes a
defensible first release at all?

**Q04-SOURCE-CONFLICT-HANDLING**
Where approved sources disagree, the engine refuses rather than choosing. Is
that defensible, and what would you do instead? Note that the behaviour is
implemented and currently unexercised.

**Q05-PHENOTYPE-AND-ACTIVITY-SCORE-MAPPING**
Is the phenotype vocabulary right, is the mapping from source terms right, and
are the thirteen refusals right (section 10)? In particular: refusing
*likely intermediate* and *likely poor*; refusing `INDETERMINATE`; refusing
CYP2D6 `RAPID`; and accepting no activity scores or diplotypes at all.

**Q06-AMITRIPTYLINE-JOINT-REPRESENTATION**
Is modelling amitriptyline as one joint CYP2C19+CYP2D6 decision correct
(section 8)? Are the twelve cells right? Is refusing when only one of the two
genes is observed right?

**Q07-CLOPIDOGREL-ACS-PCI-RESTRICTION**
Is restricting clopidogrel to an explicitly declared `ACS_OR_PCI` context
correct (section 9)? Is refusing without it the right behaviour, or should the
product answer with a prominent qualifier? Should `ACS_OR_PCI` be split?

**Q08-COVERAGE-AND-MISSING-DATA**
Is the coverage and missing-data behaviour correct (section 6), and does the
output make the difference between a finding and a refusal clear enough to a
clinician who is not reading carefully?

**Q09-UNSAFE-REASSURANCE**
**Find one.** Is there anywhere a clinician could read this output as
reassurance when it is not? Name each place, with the input that produces it.
This is the single most valuable answer this review can contain.

**Q10-WARNINGS-AND-CLAIMS**
Are the warnings and the claim boundary adequate, honest and correctly placed
(sections 1 and 2)? If you think `ACCEPTED_FOR_CANDIDATE_USE` over a failed
data-quality gate is approval by another name, say so here.

**Q11-USEFULNESS**
Would this be useful to a pharmacist or clinician in its intended
demonstration role, and what would make it useless?

**Q12-RECOMMENDED-CORRECTIONS**
What must be corrected before this could be considered further, in your order
of priority? Anything you mark `BLOCKING` will be treated as blocking.

---

## The twelve reserved cases

Separately from the questions above, twelve cases in
`data/expert-package/expert-reserved-worksheet.json` carry a product question
and **no expected answer**. They have never been run against this build, and
nothing in this repository holds an opinion about how they should come out.

Record your expectation *before* running each one. The blind-first workflow in
[`reviewer/04`](reviewer/04-blind-first-workflow.md) explains why that
ordering is the only thing that makes the answer evidence rather than
agreement.

| Case | The question it puts |
|---|---|
| `EXP-01` | two drugs on one gene in opposite directions, reported separately with no interaction claim |
| `EXP-02` | the same pair on a normal metabolizer: is the difference legible? |
| `EXP-03` | all four drugs at once: is the aggregate honest about findings versus refusals? |
| `EXP-04` | mixed phenotypes: does the dominant level hide the refused drugs? |
| `EXP-05` | one covered drug, one out of scope: can the partial answer be mistaken for a whole one? |
| `EXP-06` | one covered, two out of scope, on a toxicity-risk phenotype: does refusal noise bury the finding? |
| `EXP-07` | an observation for a gene the axis does not name, silently ignored |
| `EXP-08` | the same, where a clinician would expect that gene to matter |
| `EXP-09` | a joint drug beside a single-gene one, on a cell where the two approaches diverge |
| `EXP-10` | an irrelevant care setting, ignored rather than refused |
| `EXP-11` | `NO_ACTIVE_ATTENTION` beside a refusal — will one be read as the other? |
| `EXP-12` | nothing answerable at all: is an empty result clearly not an assessment? |
