# Remaining closure execution waves

**Policy source:** [`current-execution-policy.md`](current-execution-policy.md)  
**Historical baseline:** Wave 1 commit `9bff75c339c4133de9d025429c6be12f491d5c84`  
**Latest completed wave:** Wave 2 commit `9b0bd97`

This is the current sequencing document. Historical audit reports retain the dependency statements that were true when they were produced.

## Wave 3 — candidate scientific build

Runs the candidate-development critical path without waiting for intermediate external expert signatures:

```text
source-grounded internal decisions
→ permitted acquisition
→ new sealed dataset
→ project-team provisional DQ decision
→ production-eligible candidate evidence
→ project-team provisional curation
→ provisional computable rules
→ frozen executable candidate ruleset
→ active DEMO/VALIDATION candidate release
```

In parallel:

- close locally executable WP-C01/WP-C02 residuals;
- prepare and seal the internal validation catalogue and holdout separation;
- record every scientific decision as provisional and pending external expert review.

No external-human checkpoint stops this wave. Source licensing, prohibited acquisition modes, missing source access, infrastructure and unresolved safety ambiguity may still block an affected item.

## Wave 4 — internal validation and product completion

```text
active candidate release + sealed internal validation catalogue
→ benchmark and metrics
→ failure-mode and false-reassurance analysis
→ operational finalization
→ WP-C14A Product Surface & Demo UX Closure
→ WP-C14 Representative Candidate Demonstration
→ COMPLETE CANDIDATE PROJECT
```

All scientific results remain `PROJECT_TEAM_PROVISIONAL` and `PENDING_EXTERNAL_EXPERT_REVIEW`. The browser must expose real application state; labelled preview data may not contribute to validation or evidence.

## Wave 5 — external evaluation and final closure

```text
complete candidate project
→ WP-C12 Final External Expert Evaluation
→ feedback classification
→ WP-C14B Post-Expert Correction & Revalidation
→ regenerated validation, metrics and evidence
→ WP-C15 Final THS-6 Evidence Pack
→ FINAL SUBMISSION
```

If no real expert is available, the complete candidate project remains demonstrable, but claims must remain limited to a source-grounded, internally validated research prototype. External review and final post-review claims may not be fabricated.

## Authority-state boundary

| Stage | Permitted description | Not permitted |
| --- | --- | --- |
| Candidate scientific build | `SOURCE_GROUNDED_INTERNAL_DECISION`, `PROJECT_TEAM_PROVISIONAL` | expert-approved, clinically validated |
| Internal validation | internal validation, literature-derived validation, software verification | independent expert validation |
| External evaluation | exactly what the named expert actually reviewed and said | blanket approval inferred from limited comments |
| Post-review final | corrected and revalidated after recorded feedback | clinically validated unless the evidence genuinely supports that phrase |

## Wave 3B — core scientific integration (completion correction)

Inserted between Wave 3 and Wave 4, and required before Wave 4 begins.

Wave 3 produced source-grounded scientific content and left it in a parallel
subsystem under `pgx/closure`: no core evidence capture, no canonical candidate
dataset, curations and rules outside the governed lifecycle, a release with
`is_governed_release=false` that the assessment path did not consume, and
amitriptyline represented as two single-gene axes combined by maximum
attention. Its own execution report states all of this. Wave 3B does the
missing integration.

Three kinds of artifact must stay distinguishable, and no wave may blur them:

| | What it is | Where |
|---|---|---|
| Wave 3 standalone candidate artifacts | historical evidence, preserved unchanged | `data/closure/wave-03-candidate-*`, `docs/closure/wave-03-execution-report.md` |
| Wave 3B integrated candidate artifacts | in the core lifecycle, DEMO/VALIDATION only, `PENDING_EXTERNAL_EXPERT_REVIEW` | `data/raw/cpic-guideline-capture/`, `data/canonical/PGX-DATA-20260906-001/`, `data/candidate-rulesets/`, `data/releases/` |
| Final externally reviewed artifacts | **do not exist** | — |

The original Wave 3 acceptance criteria are **not** marked passed by Wave 3B.
Wave 3 built what it built; the parts of its own acceptance that depended on
integration were unmet, which is why this wave exists.

Wave 3B's own gate is G1-G10 in `docs/closure/wave-03b-integration-report.md`,
with the verdicts computed in `data/closure/wave-03b-integration-manifest.json`.
