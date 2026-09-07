# The blind-first case workflow

Twelve reserved cases. This is the only part of the review capable of
producing evidence that is independent of the people who built the software,
and the ordering is the entire reason.

## Why blind-first

If you look at what the software returned and then decide whether you agree,
you are reviewing a proposal. Your answer is anchored on it, and neither you
nor anybody reading later can tell how much.

If you write down what you expect and *then* look, the two are independent and
a disagreement is a finding. That is the difference between evidence and
agreement, and it costs nothing except doing the steps in order.

## Nothing in this repository holds an expected answer

The twelve cases carry `expected: null` — in the sealed catalogue, and in the
worksheet generated from it. That is not an omission. Recording an expected
answer would have invented the judgment you are being asked for, and the
sealing builder refuses to construct a reserved case that carries one:

```python
raise ValueError(
    "%s carries an expected answer; a reserved expert case must not, "
    "because recording one invents the judgment the reviewer is being "
    "asked for")
```

The worksheet you fill in has no field an expected answer could occupy, and
the packaging script refuses to run if any reserved case has acquired one.

## The steps, per case

For each of the twelve, in the order they appear in
`data/expert-package/expert-reserved-worksheet.json`:

1. **Read the request only.** The drugs, the observed phenotypes, the care
   setting if any, and the product question. Do not run it yet.
2. **Write your expectation** into three fields, before running anything:
   - `reviewer_expected_attention` — what level, if any, for each drug;
   - `reviewer_expected_refusals` — what should be refused, and why;
   - `reviewer_rationale` — the guideline or evidence you are relying on.
3. **Now run it**, or ask the project owner to run it and send you the output.
4. **Answer the product question** in `reviewer_answer_to_the_question`. This
   one is *about the output* — legibility, framing, whether a clinician would
   be misled — so it is written after you have seen it, by design.
5. **Record anything unsafe** in `reviewer_unsafe_output_note`.

Do not go back and adjust step 2 after step 3. If you got it wrong, that is
the finding.

## If you cannot run the software

Answer steps 1–2 for all twelve first, send them, and ask for the outputs.
Once your expectations are recorded and hashed, receiving the outputs cannot
contaminate them. The project will confirm the hash of what it received before
sending anything back.

## What the project does with a disagreement

Records it as a feedback item, classifies its impact and safety, links it to
the exact rule or screen it concerns, and gives it one of five dispositions —
`ACCEPTED`, `ACCEPTED_WITH_MODIFICATION`, `NOT_APPLICABLE`,
`DISAGREED_WITH_RATIONALE`, `REQUIRES_FUTURE_WORK`. A disagreement the project
disagrees with is recorded with its reasons, not dropped.

## What the twelve cases are for

They are not a test the software passes or fails. They are twelve places where
the project could not tell whether it had done the right thing, chose to ask
rather than guess, and left the answer blank on purpose.
