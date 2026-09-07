# External expert evaluation package

**Status: PRE-EXPERT / NOT FINAL. Nobody outside this project has reviewed
anything in it.**

This is the material an external pharmacogenetics expert needs in order to
criticise a candidate pharmacogenetic decision-support build. It is the thing
to be reviewed, not the record of a review. There is no expert judgment in it,
no approval, and no signature.

## What you are being asked for

Criticism. Not sign-off. The project's own view of its scientific work is that
it was assembled by one process, checked against expectations that same
process wrote, and has never been read by a pharmacogenetics specialist. That
is the gap this package exists to close, and the useful outcome is a list of
things that are wrong.

Twelve reserved cases carry a question and no expected answer, because writing
one would have invented the judgment you are being asked for.

## What is frozen

| | |
|---|---|
| Release | `PGX-CANDIDATE-REL-20260906-001` |
| Combined artifact hash | `sha256:0f444d60…f1184` — see `data/closure/wave-05-frozen-candidate-version.json` |
| Ruleset | `PGX-CANDIDATE-RULESET-WAVE03B` |
| Dataset | `PGX-DATA-20260906-001` |
| Authority | `PROJECT_TEAM_PROVISIONAL` |
| Review state | `PENDING_EXTERNAL_EXPERT_REVIEW` |
| Claim boundary approved | **false** |

Fifty-eight artifacts are hashed in that record. If any of them changes, the
combined hash changes, and what you reviewed stops being what the repository
holds. `data/expert-package/package-manifest.json` hashes this package's own
files the same way.

## Read in this order

| | |
|---|---|
| [1. Purpose and claim boundary](01-purpose-and-claim-boundary.md) | what this software claims to be, and what it refuses to claim |
| [2. DEMO and VALIDATION only](02-demo-and-validation-only-scope.md) | the two execution modes, and why PILOT is prohibited |
| [3. Scientific source strategy](03-scientific-source-strategy.md) | which sources, chosen how |
| [4. The H01 decision and its limits](04-h01-decision-and-its-limits.md) | the one human approval that exists, and the eight things it does not cover |
| [5. Dataset provenance and the DQ decision](05-dataset-provenance-and-dq-decision.md) | where the data came from and why its quality gate fails |
| [6. Four drugs, two genes](06-four-drugs-two-genes.md) | the entire scope, and everything outside it |
| [7. Curation methodology](07-curation-methodology.md) | how a guideline row became a rule |
| [8. Amitriptyline as one joint decision](08-amitriptyline-joint-representation.md) | the twelve-cell table, and why it is not two axes |
| [9. Clopidogrel and the ACS/PCI restriction](09-clopidogrel-acs-pci-restriction.md) | the care setting that is never inferred |
| [10. Phenotype and activity-score refusals](10-phenotype-and-activity-score-refusals.md) | the thirteen things curation refused to encode |
| [11. Rule and release lineage](11-rule-and-release-lineage.md) | capture → dataset → interpretation → rule → ruleset → release → assessment |
| [12. Internal validation methodology](12-internal-validation-methodology.md) | 67 cases, 55 scored, what each metric means |
| [13. The non-independence limitation](13-non-independence-limitation.md) | why the metrics in section 12 are weaker than they look |
| [14. The representative demonstration](14-representative-demonstration.md) | what a person driving the interface sees |
| [15. Known limitations](15-known-limitations.md) | scientific, operational and product, listed rather than summarised |
| [16. Questions for you](16-questions-for-the-expert.md) | the twelve areas where criticism is wanted |

## The reviewer workflow

| | |
|---|---|
| [Instructions](reviewer/00-reviewer-instructions.md) | how the review runs, start to finish |
| [Qualification and identity](reviewer/01-qualification-and-identity.md) | who you are, in your own words |
| [Conflict of interest](reviewer/02-conflict-of-interest.md) | to be declared before anything else |
| [Consent and data handling](reviewer/03-consent-and-data-handling.md) | what is stored, where, and for how long |
| [Blind-first case workflow](reviewer/04-blind-first-workflow.md) | your expectation is recorded before the software's answer is shown |
| [Review questionnaire](reviewer/05-review-questionnaire.md) | the twelve questions, with room to disagree |
| [Submission](reviewer/06-submission-procedure.md) | exactly how a completed review comes back |

Machine-readable companions, for whoever imports your review:
`data/expert-package/expert-reserved-worksheet.json`,
`data/expert-package/reviewer-response-template.json`,
`data/expert-package/expert-reserved-seal.json`.

## What this package cannot become on its own

Completing it is a scientific review. It is not approval for clinical use, not
independent validation, and not a release decision. The candidate release
stays `PROJECT_TEAM_PROVISIONAL` whatever the review concludes; changing that
is a separate, human, governed act that this repository provides no way to
perform from a review form.
