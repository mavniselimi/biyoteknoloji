# Reviewer instructions

**Nothing in this package has been reviewed. You would be the first.**

## What is being asked of you

A scientific review of a candidate pharmacogenetic decision-support build,
written by one person with no pharmacogenetics specialist involved at any
point.

What is wanted is criticism. The useful outcome is a list of what is wrong
with it, in your order of priority — not a verdict, and not encouragement.

This is not a sign-off request. There is no form here for approving the
software, because approval is not what this project needs and not what a
review of this kind can give. If your conclusion is that the work should not
proceed, that is a complete and valid answer.

## What it is not

- Not clinical validation.
- Not independent validation in any regulatory sense.
- Not a release decision, and not capable of becoming one. Recording your
  review changes no authority state anywhere in this repository.
- Not confidential. Your review is stored in the project's public git
  repository. Read `03-consent-and-data-handling.md` before you start.

## The order

1. **Declare conflicts** — `02-conflict-of-interest.md`. Before you read the
   scientific material, not after.
2. **Record who you are** — `01-qualification-and-identity.md`.
3. **Read consent and data handling** — `03-consent-and-data-handling.md`.
4. **Read the package**, sections 1–15 of `docs/expert-package/`. Roughly two
   hours; sections 8, 9, 10 and 13 are where the real decisions are.
5. **Do the reserved cases blind-first** — `04-blind-first-workflow.md`. Your
   expectation is recorded before you see what the software returns. This is
   the only part of the review that produces independent evidence, and the
   ordering is what makes it so.
6. **Answer the twelve questions** — `05-review-questionnaire.md`.
7. **Sign and date** — in your own hand or your own typing, by you, not by
   the project owner on your behalf.
8. **Submit** — `06-submission-procedure.md`.

Steps 1–3 first is not bureaucracy. A conflict declared after reading is worth
less than one declared before, and both of us should be able to say which it
was.

## Time

Reading, two hours. Twelve reserved cases blind-first, one to two hours. The
questionnaire, an hour or more if you are thorough. Call it four to five
hours. If you have less, do the reserved cases and Q09; that is the highest
value per hour in the package.

## What you may keep, change or refuse

- You may refuse any question. Write `DECLINED` and why.
- You may withdraw at any point, before or after submission. The project will
  record the withdrawal and stop citing your review.
- You may amend a submitted review by appending a correction; nothing is
  overwritten.
- You may disagree with the framing of a question. `Q10` exists partly for
  that.

## What the project may not do with your review

- It may not summarise it into approval.
- It may not cite it as validation, independent or otherwise.
- It may not extend it. If you approve one axis, that is one axis.
- It may not alter your words. Your response is preserved byte-for-byte and
  hashed; corrections are appended, never edited in.

Those are enforced by the intake machinery, not only promised: see
`docs/closure/wp-c14b-correction-protocol.md`.

## Who to contact

The project owner, through whoever sent you this package. There is no
reviewer account, no login and no portal — the review is documents in, JSON
out, by hand. That is deliberate: creating an account for you before you have
agreed to review would mean inventing a reviewer.
