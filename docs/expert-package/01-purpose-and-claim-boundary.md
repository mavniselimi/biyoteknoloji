# 1. Purpose and claim boundary

## What this is

A pharmacogenetic decision-support **candidate**: given a set of observed
metabolizer phenotypes, a list of medications and — where required — a care
setting, it returns an attention level per medication, the rule that produced
it, and the evidence lineage behind that rule. It runs in a browser over a
real database with authentication, authorisation and an audit trail.

It covers four drugs and two genes. Everything else is refused.

## What it claims

Exactly this, and the interface prints it on every page:

```
PROJECT_TEAM_PROVISIONAL
PENDING_EXTERNAL_EXPERT_REVIEW
```

An assessment is a **provisional interpretation of published guideline
material by one project**, executable for demonstration and validation. It is
not advice, not a recommendation, and not a finding about any person.

## What it refuses to claim

The claim boundary is a type in the code, not a paragraph in a document.
`CandidateClaimBoundary.is_approved` returns the constant `False` — it has no
branch that could return `True`, so no configuration, no environment variable
and no future edit to a data file can flip it. Approval requires a different
class.

Concretely, the software does not claim:

- that any output is clinically validated, or validated by anyone at all
  outside this project;
- that any output is a dose recommendation, a treatment selection, or a
  reason to change a prescription;
- that any source's guideline is being applied correctly — that judgement is
  what this package asks you for;
- that a `NO_ACTIVE_ATTENTION` result means a medication is safe. It means one
  rule matched and that rule records no active attention;
- that a refusal means low risk. A refusal means **nothing was evaluated**.

That last distinction is the one most likely to hurt someone, so it is
enforced in three places rather than described in one: the engine returns
`NOT_ASSESSED` rather than an attention level when it refuses, the page model
carries coverage and attention as separate fields, and the interface renders
them as a labelled pair. Section 15 lists where you should look for it
failing anyway.

## Intended use

Demonstration and internal validation. Two named modes, `DEMO` and
`VALIDATION`; `PILOT` is prohibited by the release manifest itself. No patient
data has ever been in this system, no genomic file format is supported, and
there is no EHR integration — not disabled, absent.

## What has been approved by a human, and by whom

One thing. On 6 September 2026 a pharmacist, Mehmet Yetiş, reviewed the
**source policy** package — which sources may be used, and how — and recorded
`APPROVED WITH CONDITIONS`. Section 4 sets out precisely what that covers and
the ten things it explicitly does not.

Nothing else in this project has been approved by anybody. No rule, no
interpretation, no phenotype mapping, no validation result and no release.
