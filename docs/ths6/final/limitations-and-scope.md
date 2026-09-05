# Limitations and scope

## What WP-25 did

Read what WP-00 through WP-24 committed, hashed it, classified it, validated
it against its own schemas, rebuilt the gates from it, and reported the
result. That is the whole of it.

## What WP-25 did not do, and could not

- It did not run a scientific computation, approve a source, curate an
  interpretation, validate a rule or freeze a ruleset.
- It did not author a validation case, build a holdout set, compute a metric
  or complete an expert review.
- It did not start a database, apply a migration, verify an audit chain, take
  a backup, build an image, run a CI job or deploy anything.
- It did not sign anything. There is no command, flag, fixture or helper in
  this repository that records a signature.
- It did not modify another work package's artifact, and specifically did not
  repair the WP-17 defect it found.

## The two source documents that could not be read

The WP-25 brief named two requirement documents held outside this repository.
Neither was readable from the environment this pack was built in: the folder
containing them is not connected to the session, so no bytes of either
document reached this work.

Requirements were therefore taken from `architecture.md`, which is in the
repository and is hashed as `EV-WP00-001`. Nothing about the unread documents
is inferred, quoted or summarised anywhere in this pack. If they contain
requirements `architecture.md` does not, this pack does not evaluate them, and
the gap is recorded as `THS6_SOURCE_DOCUMENT_UNAVAILABLE` with the work
package author as its owner.

## What the evidence classification does not tell you

`REAL_EXECUTED` means a real operation ran and its result was recorded. It
does **not** mean the result was correct, reviewed or scientifically
meaningful. Seventeen artifacts in this pack are admissible under that
definition; every one of them measures software behaviour, a legacy
comparison, or the filesystem. None of them is a pharmacogenomic result.

`IMPLEMENTATION_TEST` covers twenty-three artifacts. This repository's test
suite passes. That is a statement about software doing what its authors
intended, and it is not evidence about pharmacogenomics, operations or human
review. No gate in this pack accepts it as such.

## What "coverage" is not measured here

No test-coverage percentage appears anywhere in this pack. No coverage tool
is installed in the environment it was built in, so WP-19 reports the
coverage summary as blocked and this pack repeats that rather than
substituting an estimate.

## Freshness

Every number in the machine-readable artifacts was read from a committed
artifact or measured from the working tree at build time. Three artifacts are
classified `STALE` because they record values their own sources have since
changed; a stale artifact supports no claim here.

The prose documents in this directory are hand-written and can drift. Run
`pgx-ths6 verify-pack` to find out whether the pack still describes this
tree.
