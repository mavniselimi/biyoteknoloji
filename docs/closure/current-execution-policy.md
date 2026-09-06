# Current closure execution policy

**Effective date:** 2026-09-06  
**Authority:** project execution policy  
**Supersedes for future execution:** the intermediate-human-approval sequencing described in the original closure plan and historical H00–H04 checkpoint packages

## Operating model

```text
AUTONOMOUS PROJECT COMPLETION FIRST
→ COMPLETE CANDIDATE PROTOTYPE
→ FINAL EXTERNAL EXPERT EVALUATION
→ CORRECTION AND REVALIDATION
→ FINAL SUBMISSION
```

The project is run by a high-school research team without continuous access to a clinical pharmacogenomics expert, physician, pharmacist, curator or scientific review board. Repeated external-human approval is therefore not a prerequisite for constructing and internally validating the candidate prototype.

This policy changes execution sequencing. It does not convert project-team or AI-assisted decisions into external expert evidence.

## Pre-expert authority states

All scientific and governance decisions used to build the candidate must carry one of these transparent authority states:

- `SOURCE_GROUNDED_INTERNAL_DECISION` — a decision supported by versioned authoritative sources, recorded provenance, rationale, uncertainty and conflicts;
- `PROJECT_TEAM_PROVISIONAL` — a research-design or quality decision adopted by the project team for the candidate prototype;
- `PENDING_EXTERNAL_EXPERT_REVIEW` — an explicit statement that the decision has not yet received final external expert evaluation.

A record may carry both a decision state and `PENDING_EXTERNAL_EXPERT_REVIEW`. The latter is a limitation, not a reason to stop candidate development.

Existing fields that specifically mean a real human approval or signature keep that meaning. Candidate execution must use a separate backward-compatible authority-state path; it must not write an AI/project-team value into an external-approver field or silently redefine `APPROVED`. Candidate readiness and final expert-reviewed closure remain separate evaluations.

Before real external review, the repository must not use or imply:

- `EXPERT_APPROVED`,
- `PHYSICIAN_APPROVED`,
- `CLINICALLY_VALIDATED`,
- `INDEPENDENTLY_VALIDATED`,
- `EXTERNAL_REVIEWED`.

No agent or project member may fabricate an expert identity, credential, comment, score, signature, approval or review date.

## What may proceed provisionally

Subject to source access, licensing, provenance and safety constraints, the project team may make replaceable internal decisions for:

- first-release scope,
- source selection and permitted use,
- terminology and phenotype mapping,
- conservative representations of ambiguity,
- curation protocol and provisional interpretations,
- dataset-quality disposition,
- expected gene scope and coverage,
- provisional computable rules and candidate rulesets,
- internal validation cases, reference judgments and holdout assignments,
- project-level claim language and fail-closed behavior.

Each decision must cite the strongest available authoritative evidence, preserve source versions and provenance, expose conflicts and uncertainty, explain the chosen representation, fail closed where uncertainty cannot be represented safely, and remain replaceable after expert feedback.

Licence, access-control and redistribution restrictions remain hard constraints. This policy does not authorize scraping, unknown-terms API use, bulk acquisition, restricted full-text redistribution, real patient data or any action prohibited by the source policy.

## Validation terminology

Before external expert evaluation, evidence may be described only as:

- internal validation,
- literature-derived validation,
- software verification,
- deterministic/reproducibility testing.

It must not be described as independent expert validation or clinical validation.

## Candidate completion and final closure

The candidate project is functionally complete when it has a clean source-grounded dataset, traceable evidence, provisional interpretations and rules, an executable candidate ruleset and release, internal validation and metrics, operational evidence, a jury-ready browser surface, and a representative candidate demonstration.

Candidate completion is not final THS-6 closure. Final closure additionally requires:

1. genuine whole-project external expert evaluation;
2. preservation of the expert's original response;
3. classification of every feedback item as `ACCEPTED`, `ACCEPTED_WITH_MODIFICATION`, `NOT_APPLICABLE`, `DISAGREED_WITH_RATIONALE` or `REQUIRES_FUTURE_WORK`;
4. implementation of required scientific, rule, data, report or UX corrections;
5. version increment and rerun of affected tests, validation, metrics and evidence generation;
6. final claims calibrated to what the expert actually evaluated.

## Historical checkpoint packages

`docs/closure/checkpoints/H00-*` through `H04-*`, the Wave 1 and Wave 2 reports, and their machine-readable manifests are preserved as historical/audit evidence. They record the policy and state that existed when those waves ran.

Their blank approval forms must not be filled by an agent. Their earlier `BLOCKED_BY_HUMAN` language no longer blocks candidate construction; open questions are inputs to source-grounded internal decision records and remain final claims/evidence limitations until real external review.

The recorded Mehmet Yetiş H01 pharmacist attestation remains genuine evidence of the narrow source-policy review he actually performed. It must not be broadened into curation, rule, clinical-validation or whole-project approval.

## Remaining execution waves

No more than three major waves remain:

1. **Wave 3 — candidate scientific build:** authority-state bridge, permitted acquisition, sealed dataset, provisional DQ decision, internal curation, provisional rules, frozen candidate ruleset and active candidate release; validation catalogue preparation proceeds in parallel.
2. **Wave 4 — internal validation and product completion:** internal holdout closure, benchmark and metrics, remaining operational evidence, Product Surface & Demo UX closure, and the representative candidate demonstration.
3. **Wave 5 — external evaluation and final closure:** whole-project expert evaluation, feedback disposition, correction and revalidation loop, final evidence pack and truthful final claims.
