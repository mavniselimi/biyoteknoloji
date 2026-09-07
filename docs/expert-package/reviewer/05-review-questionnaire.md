# Scientific review questionnaire

Twelve questions. For each: an answer in free text, a severity, and a
correction priority. Write `DECLINED` for any you will not answer.

**Severity** — `BLOCKING` (must be fixed before this goes further),
`MAJOR`, `MINOR`, `OBSERVATION`.
**Correction priority** — `P0` (immediately), `P1`, `P2`, `P3`, `NONE`.

Nothing here is phrased to invite agreement. If your answer to every question
is that the work is sound, say so — but the questions are written on the
assumption that it is not, because nobody has checked.

---

## Q01-SCIENTIFIC-APPROPRIATENESS

Is the overall scientific approach appropriate for what this software claims
to be, and where is it not?

> Answer:
>
> Severity: ____________  Correction priority: ____________

## Q02-PGX-INTERPRETATION-QUALITY

Is the pharmacogenetic interpretation of each covered axis correct, and where
would you interpret differently? Sections 6 and 8 hold the tables. Cell-level
disagreements are the most useful form.

> Answer:
>
> Severity: ____________  Correction priority: ____________

## Q03-SOURCE-SELECTION

Are the four approved sources the right ones for a first release, and what is
missing or should not be there? Is four drugs and two genes a defensible first
release at all?

> Answer:
>
> Severity: ____________  Correction priority: ____________

## Q04-SOURCE-CONFLICT-HANDLING

Where approved sources disagree, the engine refuses rather than choosing. Is
that defensible? What would you do instead?

> Answer:
>
> Severity: ____________  Correction priority: ____________

## Q05-PHENOTYPE-AND-ACTIVITY-SCORE-MAPPING

Is the phenotype vocabulary right, is the mapping from source terms right, and
are the thirteen refusals right? Specifically: *likely intermediate* and
*likely poor* refused; `INDETERMINATE` refused; CYP2D6 `RAPID` refused; no
activity scores or diplotypes accepted at all.

> Answer:
>
> Severity: ____________  Correction priority: ____________

## Q06-AMITRIPTYLINE-JOINT-REPRESENTATION

Is modelling amitriptyline as one joint CYP2C19+CYP2D6 decision correct? Are
the twelve cells right? Is refusing when only one of the two genes is observed
right?

> Answer:
>
> Severity: ____________  Correction priority: ____________

## Q07-CLOPIDOGREL-ACS-PCI-RESTRICTION

Is restricting clopidogrel to an explicitly declared `ACS_OR_PCI` context
correct? Is refusing without it right, or should the product answer with a
prominent qualifier? Should `ACS_OR_PCI` be split into separate settings?

> Answer:
>
> Severity: ____________  Correction priority: ____________

## Q08-COVERAGE-AND-MISSING-DATA

Is the coverage and missing-data behaviour correct, and does the output make
the difference between a finding and a refusal clear enough to a clinician who
is not reading carefully?

> Answer:
>
> Severity: ____________  Correction priority: ____________

## Q09-UNSAFE-REASSURANCE

Is there anywhere a clinician could read this output as reassurance when it is
not? Name each place, with the input that produces it.

This is the most valuable answer this review can contain. The project's own
benchmark reports zero unsafe false reassurances across 55 cases, and the
person who chose those 55 wrote the code they were testing.

> Answer:
>
> Severity: ____________  Correction priority: ____________

## Q10-WARNINGS-AND-CLAIMS

Are the warnings and the claim boundary adequate, honest and correctly placed?
If you think accepting a dataset over a failed data-quality gate is approval
by another name, this is where to say it.

> Answer:
>
> Severity: ____________  Correction priority: ____________

## Q11-USEFULNESS

Would this be useful to a pharmacist or clinician in its intended
demonstration role, and what would make it useless?

> Answer:
>
> Severity: ____________  Correction priority: ____________

## Q12-RECOMMENDED-CORRECTIONS

What must be corrected before this could be considered further, in your order
of priority?

> Answer:
>
> Severity: ____________  Correction priority: ____________

---

## Unsafe or misleading outputs

Separately from Q09, list every specific output you consider unsafe or
misleading, one per row. Each becomes a tracked feedback item.

| # | Input that produces it | What the software shows | Why it is unsafe | Severity |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |

## Overall free-text criticism

Anything the twelve questions did not ask for.

>
>
>

---

## Signature

To be completed by the reviewer personally. Nobody may complete it on your
behalf.

> I have reviewed the package identified above. This is a scientific review.
> It is not approval for clinical use, not independent validation, and not a
> release decision.
>
> Signed: ____________________
>
> Name (printed): ____________________
>
> Date: ____________
