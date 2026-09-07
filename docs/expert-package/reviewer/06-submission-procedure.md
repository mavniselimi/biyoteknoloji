# Submission procedure

## What to send

One of:

- the completed markdown forms (`01`, `02`, `03`, `05`) plus the completed
  `expert-reserved-worksheet.json`; or
- one completed `reviewer-response-template.json`, which carries all of it.

The JSON is easier to import; the markdown is easier to fill in. Either is
accepted, and the project converts rather than asking you to redo it.

## Where to send it

To the project owner, by whatever channel sent you this package. There is no
upload portal and no reviewer account. Creating an account for you before you
had agreed to review would have meant inventing a reviewer, so none exists.

## What the project does on receipt, in order

1. **Preserves it verbatim.** Your response is written to
   `data/expert-review/wp-c12-response-<reviewer-slug>.json` exactly as
   received, and hashed. That hash is recorded and never recomputed from an
   edited file.
2. **Checks the binding.** Your response names the release, the frozen
   combined hash and the package manifest hash you reviewed. If the repository
   has moved on, the mismatch is recorded — your review still stands, against
   the version you actually read.
3. **Refuses to proceed if anything is still `HUMAN_REQUIRED`.** The intake
   tool will not accept a partially completed response as a complete one.
4. **Extracts feedback items**, one per discrete point, each carrying the
   verbatim source text and its location in your response.
5. **Links each item** to the rule, screen, document or artifact it concerns.
6. **Classifies impact and safety.**
7. **Assigns a disposition** — `ACCEPTED`, `ACCEPTED_WITH_MODIFICATION`,
   `NOT_APPLICABLE`, `DISAGREED_WITH_RATIONALE`, `REQUIRES_FUTURE_WORK` —
   with a written reason for anything not accepted.
8. **Reruns what your feedback touches**, and records before/after metrics.

Steps 4–8 are WP-C14B. The machinery exists and is empty; it refuses to create
a feedback item without a real response file behind it. See
`docs/closure/wp-c14b-correction-protocol.md`.

## The exact command

The project owner runs, from the repository root:

```
python3 scripts/wp_c14b_intake.py \
    --response /path/to/your-completed-response.json \
    --reviewer-slug <short-name>
```

It writes the preserved response, a feedback register, and an impact matrix.
It exits non-zero and writes nothing if the response is a template, if any
required field is still `HUMAN_REQUIRED`, or if the reviewer block is
incomplete.

## What you will get back

- Confirmation of the hash of what was received.
- The extracted feedback items, so you can say whether they represent your
  points fairly. **Nothing is dispositioned before you have seen them.**
- Once dispositions are decided, the register — including every
  `DISAGREED_WITH_RATIONALE` and its reasons.

## Corrections and withdrawal

Send a correction and it is appended with its own timestamp; the original is
never edited. Withdraw and the project records the withdrawal, stops citing
the review, and removes the response file in a new commit — without claiming
to have erased git history, which it cannot do.

## What will not happen

No part of this procedure sets any gate to pass, closes THS-6, registers the
candidate release, or changes `permits_transition`. Those are separate,
governed, human acts. A completed review is an input to them and is not one of
them.
