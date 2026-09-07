# WP-C14B — post-expert correction and revalidation

**State: machinery built, register empty. No external expert response exists,
so there is nothing to correct and no correction has been implemented.**

Artifacts: `data/closure/wp-c14b/feedback-register.json`,
`data/closure/wp-c14b/correction-impact-matrix.json`.
Code: `pgx/closure/wp_c14b.py`, `scripts/wp_c14b_intake.py`.

## Why it is empty

WP-C12 is a human step. This repository may not author an external expert's
judgment, so it has not written one, and a correction loop with no review
behind it would be a loop correcting nothing towards nothing.

What exists is the machinery: the vocabularies, the refusals, the extraction,
the impact matrix and the rerun decision. All of it runs today, on an empty
input, and produces an empty register that says why.

## The eight refusals

`scripts/wp_c14b_intake.py` writes nothing at all unless every one passes.

| Code | Refused because |
|---|---|
| `RESPONSE_IS_THE_TEMPLATE` | the file is the blank template |
| `HUMAN_REQUIRED_FIELD_REMAINS` | at least one field a person must complete is still `HUMAN_REQUIRED` |
| `REVIEWER_NOT_IDENTIFIED` | no name and qualification |
| `NOT_SIGNED` | no signed name and date |
| `CONFLICT_OF_INTEREST_NOT_DECLARED` | the declaration is blank |
| `CONSENT_NOT_RECORDED` | the consent block is blank |
| `NOTHING_ANSWERED` | no question, reserved case or free-text field carries content |
| `RELEASE_BINDING_ABSENT` | the response does not name the release and frozen hash it reviewed |

Run against the blank template, six of the eight fire and the exit status is
3. That is the intended behaviour and it is asserted by test.

## Immutable preservation

The response is written to
`data/expert-review/wp-c12-response-<slug>.json` **byte-for-byte as
received**, and hashed from those bytes — never from a parsed and
re-serialised copy, which would hash what this project made of the response
rather than the response. An existing preserved file is never overwritten: a
second submission is a correction, appended with its own author and instant.

## Feedback-item extraction

One item per discrete point. Each carries:

- `source_text_verbatim` — the reviewer's own words;
- `source_path` — the JSON path it was read from, so the item can be checked
  against the response;
- `subject` — the question id or reserved case id;
- the reviewer's own severity and correction priority, unaltered.

There is **no code path that constructs an item without verbatim source
text**. `extract_feedback_items` returns early on empty text, so an item
nobody wrote cannot be produced by this module.

Five kinds: `QUESTIONNAIRE_ANSWER`, `RESERVED_CASE_DISAGREEMENT`,
`RESERVED_CASE_PRODUCT_ANSWER`, `UNSAFE_OUTPUT_REPORT`, `FREE_TEXT`.

## Classification

Left `HUMAN_REQUIRED` by the intake. Inferring an impact class from a
reviewer's wording would be putting words in their mouth, and inferring a
disposition would be deciding whether the project agrees with them.

**Impact** — `RULE_CONTENT`, `RULESET_SCOPE`, `PHENOTYPE_MAPPING`,
`REFUSAL_BEHAVIOUR`, `EVIDENCE_OR_CITATION`, `PRODUCT_PRESENTATION`,
`DOCUMENTATION`, `SCOPE_OR_GOVERNANCE`.

**Safety** — `UNSAFE_OUTPUT`, `INCORRECT_SCIENCE`,
`MISLEADING_PRESENTATION`, `INCOMPLETE`, `NO_SAFETY_IMPACT`.

## The five dispositions

| Disposition | What it commits the project to |
|---|---|
| `ACCEPTED` | agrees, will make the change as described |
| `ACCEPTED_WITH_MODIFICATION` | agrees there is a problem, will fix it differently; **the difference must be written down** |
| `NOT_APPLICABLE` | does not apply to this build, with the reason |
| `DISAGREED_WITH_RATIONALE` | does not agree; records its reasons in full beside the reviewer's, which is never removed |
| `REQUIRES_FUTURE_WORK` | agrees and cannot act now; what is missing and who would clear it are both named |

Every one requires a written rationale. A disposition with none is not
recordable.

## Affected-test selection

Declared per impact class in `AFFECTED_TEST_MAP`, not inferred. A correction
loop that chose its own regression tests would be choosing what could catch
it. For example `RULE_CONTENT` selects `tests/unit/engine`,
`tests/unit/closure`, `tests/unit/closure/test_wave03b_assessment.py` and a
full benchmark rerun.

## The benchmark rerun decision

Fails towards rerunning:

- **any** item still unclassified → rerun required;
- any item classified `UNSAFE_OUTPUT` or `INCORRECT_SCIENCE` → rerun required;
- any item whose impact is `RULE_CONTENT`, `RULESET_SCOPE`,
  `PHENOTYPE_MAPPING` or `REFUSAL_BEHAVIOUR` → rerun required.

An undecided register therefore cannot produce a decision *not* to
re-measure. With no items at all the answer is "nothing to re-measure",
recorded with that reason rather than as a false negative.

## Before/after metrics and the regression demonstration

Both `HUMAN_REQUIRED` in the matrix the moment any item exists, and `null`
while none does. Filling them means: rerun the sealed catalogue's 55 scored
cases, record the metric block before and after, and drive the corrected
behaviour through the interface once more.

**The sealed catalogue's expected answers are not edited to match a
correction.** If a correction changes what the right answer is, the catalogue
disagreement is recorded as an issue; a new case is added, and the old
expectation stays with its history. The sealing script refuses to rewrite a
sealed catalogue, which is what makes that discipline enforceable rather than
intended.

## What WP-C14B may never do

- Create a feedback item with no preserved response behind it.
- Record a disposition with no rationale.
- Edit a reviewer's text.
- Implement a correction before its item exists.
- Set any gate, close THS-6, register the candidate release, or change
  `permits_transition`.
