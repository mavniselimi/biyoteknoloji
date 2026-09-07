# Execution Wave 5 — external-expert preparation

```
AUTONOMOUS PREPARATION COMPLETE
AWAITING GENUINE EXTERNAL EXPERT EVALUATION
WP-C12 HUMAN STEP OPEN
WP-C14B NOT STARTED
WP-C15 NOT FINAL
```

Every figure below is read from `data/closure/wave-05-status.json`, which is
computed by twenty-two checks against artifacts on disk and rebuilds
byte-identically. Nothing here was reviewed by anyone outside this project,
and nothing in this wave attempted to make it look as though it had been.

## 1. What Wave 5's autonomous scope was, and was not

Wave 5 is WP-C12 → WP-C14B → WP-C15. A real external expert response is a
hard human boundary, so the work available without a person was: freeze what
an expert would review, assemble the package, preserve the reserved-case
boundary, prepare the reviewer workflow, build the post-review machinery
empty, and build a `PRE-EXPERT / NOT FINAL` evidence inventory.

All six are done. WP-C12 itself is untouched, because authoring an expert's
judgment is the one thing this repository may not do.

## 2. B1 — the frozen evaluated version

`data/closure/wave-05-frozen-candidate-version.json`.

| | |
|---|---|
| Artifacts hashed | **58** |
| Combined hash | `sha256:0f444d60…f1184` |
| Release | `PGX-CANDIDATE-REL-20260906-001` |
| Manifest hash | `sha256:0cd22a88…581d01` |
| Dataset | `PGX-DATA-20260906-001` |
| Ruleset | `PGX-CANDIDATE-RULESET-WAVE03B` / `sha256:29ca1949…c7c71a` |
| Demonstrated at | `0ff8871` |
| Status | `PRE-EXPERT / NOT FINAL` |

The record covers the canonical dataset, the candidate ruleset, the release
manifest, the validation catalogue, the benchmark output and the browser
evidence. It hashes the twelve expert-reserved cases **without parsing them** —
their bytes go into the digest and nothing reads their content. Its own
`what_this_record_is_not` list says that freezing approves nothing.

## 3. B2 — the evaluation package

`docs/expert-package/` — sixteen sections and an index — plus seven reviewer
documents and four JSON companions. Twenty-seven files, each hashed in
`data/expert-package/package-manifest.json` and bound to the frozen combined
hash.

The sixteen required subjects each have their own section: purpose and claim
boundary; DEMO/VALIDATION-only scope; source strategy; the H01 decision and
its narrow limits; dataset provenance and the candidate-only DQ decision; the
four-drug/two-gene scope; curation methodology; the amitriptyline joint
representation; the clopidogrel ACS/PCI restriction; phenotype and
activity-score refusals; rule and release lineage; internal validation
methodology and metrics; the non-independence limitation; the representative
demonstration; known limitations; and the exact questions.

Three of them do work the others cannot:

- **Section 4** lists the ten things the one human attestation this project
  holds explicitly does not approve — including *any generated
  pharmacogenetic rule*. The single approval the project has does not cover a
  single rule in the release.
- **Section 13** exists so that section 12's row of 1.0 metrics cannot be
  quoted without it. One process wrote the rules, the cases and the
  expectations.
- **Section 15** lists thirty limitations rather than summarising them,
  because a summary is where a limitation goes to die.

A test scans every package document for claims that a review happened. The
scanner skips sentences carrying a negation, which is a deliberate
false-negative trade: these documents deny external review on nearly every
page, and a scanner that flagged its own disclaimers would be deleted within a
week. Both halves — the claims that must fire and the denials that must not —
are asserted.

## 4. B3 — the reserved-case boundary, preserved and measured

`data/expert-package/expert-reserved-seal.json`.

| | |
|---|---|
| Reserved cases | 12 |
| Expected answers | **0**, in all twelve |
| Questions carried | 12 |
| Payload reads allowed | **0** |
| Access events | 24, hash-chained, chain intact |
| Evaluated against the build | **false** |

The seal is not a claim. Every case is put through WP-18's own
`decide_access` twice: once for the partition audit, which the policy allows,
and once for a payload read, which the policy **refuses** — this process holds
no WP-22 assignment permit, and `EXPERT_HOLDOUT_REQUIRES_PERMITTED_WORKFLOW`
is recorded twelve times in a hash-chained ledger. That refusal is the
evidence. It is this project's own access policy declining to hand the
reserved payloads to the process that built the package.

The reviewer worksheet is generated from the sealed catalogue and **has no
field an expected answer could occupy** — not an empty field, no field. Every
answer slot is `HUMAN_REQUIRED`. The builder itself refuses to construct a
reserved case carrying an expected answer, and the packaging script refuses to
run if one has appeared.

What is reserved is the judgment, not the input. The twelve requests are
committed in this repository in plain text and always have been; a reviewer
needs to see them to answer. The package says so rather than implying a
secrecy it does not have.

## 5. B4 — the reviewer workflow

Seven documents, in the order a review actually runs: instructions,
qualification and identity, conflict of interest, consent and data handling,
the blind-first case workflow, the questionnaire, and submission.

Conflicts are declared **before** the scientific material is read, and the
instructions say why: a conflict declared afterwards is worth less, and both
parties should be able to say which it was.

The questionnaire asks all twelve required criticism areas — scientific
appropriateness, interpretation quality, source selection, source-conflict
handling, phenotype and activity-score mapping, the amitriptyline joint
representation, the clopidogrel restriction, coverage and missing-data
behaviour, unsafe reassurance, warnings and claims, usefulness, and
recommended corrections — with severity and correction-priority fields, a
free-text criticism block, an unsafe-output table, and a signature and date
block for the reviewer to complete personally.

Nothing pre-fills a conclusion and nothing suggests approval is expected.
There is no form for approving the software, because that is not what a review
of this kind can give. No reviewer account exists: creating one before anyone
has agreed to review would mean inventing a reviewer.

The consent document does not promise what a git repository cannot deliver. It
says the review is public, permanent in history, byte-preserved, and that a
withdrawal removes the file in a new commit without erasing history.

## 6. B5 — WP-C14B, built and empty

`pgx/closure/wp_c14b.py`, `scripts/wp_c14b_intake.py`,
`data/closure/wp-c14b/`, `docs/closure/wp-c14b-correction-protocol.md`.

The machinery runs today, on nothing, and produces an empty register that says
why. Eight refusals stand between this repository and a fabricated review:
`RESPONSE_IS_THE_TEMPLATE`, `HUMAN_REQUIRED_FIELD_REMAINS`,
`REVIEWER_NOT_IDENTIFIED`, `NOT_SIGNED`,
`CONFLICT_OF_INTEREST_NOT_DECLARED`, `CONSENT_NOT_RECORDED`,
`NOTHING_ANSWERED`, `RELEASE_BINDING_ABSENT`. Run against the blank template,
six fire, the exit status is 3 and nothing is written — asserted end to end
through the command the submission procedure documents.

Two properties are structural rather than promised:

- **Every feedback item carries verbatim reviewer text and the JSON path it
  came from.** `extract_feedback_items` returns early on empty text, so there
  is no code path that produces an item nobody wrote.
- **The benchmark rerun decision fails towards rerunning.** An item whose
  impact or safety class is still undecided counts as requiring a rerun, so an
  undecided register cannot produce a decision not to re-measure.

Impact, safety and disposition are left `HUMAN_REQUIRED`. Inferring an impact
class from a reviewer's wording would put words in their mouth; inferring a
disposition would decide whether the project agrees with them.

All five dispositions are defined with what each commits the project to, and
`DISAGREED_WITH_RATIONALE` records the project's reasons **beside** the
reviewer's text, which is never removed.

## 7. B6 — the WP-C15 pre-final inventory

`data/closure/wp-c15/`.

Nineteen evidence artifacts, each with its hash, **what it establishes and
what it does not**. An inventory that only listed files would let a reader
assume each one proves something.

Five templates, all unsigned, each declaring itself a template in a field
rather than only in a filename: final gate report, Definition of Done, human
attestation packets, final release decision, and the THS-6 summary. Every
expert-dependent field is `HUMAN_REQUIRED`; no attestation packet carries a
signature and none invents a person.

The four forbidden values are read from WP-25's own artifacts and never
overridden here:

| | |
|---|---|
| `ths6_achieved` | **false** |
| `release_may_proceed` | **false** |
| Gates passing | **0 of 6** |
| Definition of Done | **1 of 15** |
| Signed attestations | **0 of 9** |

The builder refuses to write a `PRE-EXPERT` inventory over a state that claims
completion, and the guard is unit-tested by feeding it each forbidden value.

The THS-6 summary template records `ths6_achieved: false` rather than
`HUMAN_REQUIRED`, and says why: a blank could be completed by filling it in;
the honest current value is false.

## 8. B7 — status

Twenty-two checks, all passing, in
`data/closure/wave-05-status.json`. If any failed the status would narrow to
`AUTONOMOUS PREPARATION INCOMPLETE` rather than the check being removed.

Rebuild every Wave 5 artifact with:

```
python3 scripts/build_wave05_artifacts.py
```

The four builders have a dependency chain and no cycle; running them out of
order leaves a downstream artifact recording a stale upstream hash, which the
tests catch.

## 9. The exact human action still required

1. Recruit an external pharmacogenetics expert — clinical pharmacologist,
   clinical pharmacist, medical geneticist or pharmacogenomics scientist — who
   is not this project.
2. Send them `docs/expert-package/README.md` and the four JSON companions in
   `data/expert-package/`.
3. Have them complete the conflict-of-interest and consent forms **before**
   reading the scientific sections.
4. Have them answer the twelve reserved cases blind-first, recording their
   expectation before running anything.
5. Have them sign and date the review personally.
6. Import it:
   `python3 scripts/wp_c14b_intake.py --response <file> --reviewer-slug <name>`

Until step 6 succeeds with a real response, WP-C14B has nothing to correct and
WP-C15 cannot be final.

## 10. One residual this wave found and did not fix

`data/api/wp16-real-gate-status.json` no longer describes the tree. Its
`error_code_count` is 45; the API now declares 47, and its own note says the
verified `api_source_sha256` has changed. Wave 4B added the typed `ApiError`
handler and the runtime-track assertions and did not refresh it, and the
device VM cannot run the WP-16 suite - it has no fastapi - so nothing noticed.

It was **not** refreshed here, deliberately. Regenerating it on a host that
has the web stack flips `api_dependencies_available` and
`database_dependencies_available` from false to true, and both are probes that
`pgx/ths6/gate_matrix.py`, `pgx/ths6/claim_registry.py` and `pgx/ths6/demo.py`
read. A THS-6 gate result must not move as a side effect of which machine
happened to run a builder during a documentation wave.

What clears it: run `python -m apps.api.artifacts` on the host the project
actually deploys from, then evaluate what the two flipped probes do to Gate C
and Gate E and record that evaluation. It is a small job and it is a THS-6
job, not a Wave 5 one.

The same reasoning leaves `data/web/wp17-real-gate-status.json` alone. It
records `browser_runtime_available: false`, which is true of the device VM and
of the project owner's Mac, and false only of the session container that has
playwright installed. `data/deployment/wp24-runtime-asset-manifest.json`
checksums both files and is stale on that container for the same reason. Three
artifacts, one cause: a document that measures the machine is supposed to
differ between machines.

## 11. What Wave 5 deliberately did not do

- It did not author, simulate, summarise or anticipate an expert's judgment.
- It did not open or score the twelve reserved cases.
- It did not alter Mehmet Yetiş's H01 attestation or widen what it approved.
- It did not convert `ACCEPTED_FOR_CANDIDATE_USE` into governed approval;
  `permits_transition` is still false.
- It did not register the candidate release, touch a THS-6 gate, sign an
  attestation, or set any gate to pass.
- It did not create a reviewer account for a person who does not exist.

Completing the autonomous scope is the successful end of what could be done
without a person. It is not the end of the work.
