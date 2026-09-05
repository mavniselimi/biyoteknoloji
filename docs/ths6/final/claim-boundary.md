# Claim boundary — what may and may not be said

**The claim boundary is not approved.** Its status in
`data/safety/wp20-real-gate-status.json` is
`DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW`, and only a named clinical
safety authority can change that.

Until it is approved, the safe reading of this section is: **no outward claim
about this system's pharmacogenomic output is authorised.**

## The twenty-four registered claims

Every claim the project might make is registered with the evidence that would
justify it and, where one exists, a probe naming a field in a committed
artifact whose value would refute it.

| Support | Count |
|---|---|
| SUPPORTED | 0 |
| PARTIALLY_SUPPORTED | 0 |
| UNSUPPORTED | 2 |
| CONTRADICTED | 22 |

**Zero claims are supported.** Twenty-two are refuted by this repository's own
artifacts — not merely unproven, but contradicted by a field somebody can open
and read.

## The difference between UNSUPPORTED and CONTRADICTED

`UNSUPPORTED` means nothing admissible was found. `CONTRADICTED` means
something was found and it says no.

`THS6-CLAIM-024` — *"A release has been validated and may proceed"* — is
CONTRADICTED, because `data/deployment/wp24-release-validation.json` records
`release_may_proceed: false`. That is a finished job that said no, not an
unfinished one, and reporting it as merely unsupported would lose the
distinction.

## The probes

Twenty-three probes are declared and all twenty-three resolve against the
committed tree. A probe that names a field its artifact does not have returns
"no verdict" silently — it looks like diligence and can never fire — so the
registry reports `unresolvable_probes` and the schema requires that list to be
empty.

This is not hypothetical. A probe naming `state` on an artifact whose field is
`dataset_lifecycle_state` did exactly that during development, and the claim
it guarded reported as UNSUPPORTED rather than CONTRADICTED until it was
found.

## Ten claims are marked outward-facing

Those are the ones that would be clinical or diagnostic statements if made
publicly: the representative workflow, determinism, traceable evidence,
missing-data handling, the fifty validation cases, the holdout set, CI safety,
the expert review, release-specific metrics, the audit record, the offline
demo, the claim boundary itself, and the release.

Every one of them is CONTRADICTED or UNSUPPORTED today. None may be made.

## What may be said

These statements are supported by this pack and may be made:

- The P0 software is implemented across twenty-five work packages, with 7,000+
  tests passing.
- The system refuses to compute from unapproved content, and this is
  structural rather than a policy somebody follows.
- Missing data is modelled as a coverage axis separate from risk, and the
  invariant is proven over fixtures.
- Real-patient, genotype and raw-sequencing fields are refused by the case
  model at any depth.
- No approved source, published dataset, executable ruleset, validation case,
  computed metric or completed expert review exists.
- No clinical validation of any kind has been performed on this repository.

## What may not be said

- Any statement implying a pharmacogenomic result has been produced,
  validated or reviewed.
- Any statement that "the system works" without the qualification that it has
  never been run against governed content.
- Any number from this repository presented as a validation metric,
  performance figure or accuracy result. Zero metrics have values.
- Any description of a local run as staging, a configured workflow as a CI
  run, a Dockerfile as an image, or a written runbook as an executed
  operation.
