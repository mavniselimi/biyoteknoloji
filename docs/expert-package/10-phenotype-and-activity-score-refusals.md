# 10. Phenotype and activity-score refusals

Source: `data/candidate-rulesets/PGX-CANDIDATE-RULESET-WAVE03B/provenance.json`.

## The phenotype vocabulary

Five determinate members: `POOR`, `INTERMEDIATE`, `NORMAL`, `RAPID`,
`ULTRARAPID`. Plus `INDETERMINATE`, which describes an input and which the
rule condition grammar refuses as a rule phenotype.

There is no member for a *likely* assignment, and none was added.

## The thirteen refusals

Curation refused to encode thirteen source rows. Every refusal is recorded
with the source term, the reason and a code — this is data in the release, not
commentary about it.

| Count | Code | What was refused |
|---|---|---|
| 9 | `PHENOTYPE_NOT_REPRESENTABLE` | *likely intermediate*, *likely poor*, and *Indeterminate* rows across clopidogrel, omeprazole, codeine and amitriptyline |
| 2 | `AXIS_ABSENT_FROM_SOURCE` | CYP2D6 `RAPID` for codeine and for amitriptyline |
| 2 | `SOURCE_ROW_ABSENT` | amitriptyline · CYP2C19 *likely intermediate* and *likely poor* |

## The three arguments behind them

**"Likely" is not a phenotype.** Mapping *CYP2C19 likely intermediate
metabolizer* to `INTERMEDIATE` would assert a determination the source
explicitly declined to make; the guideline's own footnote says *likely* marks
uncertainty in the phenotype assignment. Mapping *likely poor* to `POOR` would
overstate what the source concluded. So neither is mapped, and a request
carrying one gets a refusal rather than a confident answer.

**`INDETERMINATE` describes the input.** The source records no recommendation
for it. An observation whose status is `INDETERMINATE` contributes nothing to
the observed set, so it can only ever fail to match — which is reported as a
refusal, explicitly, rather than as an absence of risk.

**CYP2D6 `RAPID` does not exist in this guideline's model.** CPIC's CYP2D6
phenotype table states ultrarapid, normal, intermediate and poor only. The
project's vocabulary *has* a `RAPID` member — it is needed for CYP2C19 — and
using it for CYP2D6 would present an answer the source does not contain. It
was refused for both CYP2D6 drugs. This was also a preserved owner decision:
*"CYP2D6 RAPID must not be used as an expected phenotype."*

Consequence: a request observing CYP2D6 `RAPID` and asking about codeine gets
`UNSUPPORTED_PHENOTYPE` / `PHENOTYPE_NOT_SUPPORTED`, with the detail *"That is
a refusal, not a finding of no risk: no rule was evaluated."* Reserved case
`PGX-VAL-W4-EXP-12` puts this in front of a reviewer.

## Activity scores

**This release does not accept activity scores at all.** It accepts phenotype
labels. No diplotype-to-activity-score translation, no activity-score-to-
phenotype banding, and no CYP2D6 copy-number handling exists anywhere in the
code.

That is a scope decision, not an oversight, and it has a consequence worth
stating: the software cannot be given a diplotype. Whoever supplies the
phenotype has already done the hardest and most error-prone step, and this
project neither performs nor checks it. If you consider a pharmacogenetic
product that begins at the phenotype to be answering the easy half of the
question, say so — question **Q05**.

## What to criticise

- Are the five determinate members the right vocabulary?
- Is refusing *likely* correct, or over-cautious to the point of uselessness?
- Is refusing CYP2D6 `RAPID` correct given that some laboratories report it?
- Should the product accept diplotypes or activity scores at all, and is
  starting at the phenotype defensible?
