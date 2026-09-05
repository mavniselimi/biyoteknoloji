# Pack integrity

**Result: PASS.** This says nothing about whether the programme achieved
anything.

## Two levels of hash

**Level one** is a SHA-256 per member: what each file in the pack is.

**Level two** is `pack_sha256`, a digest over the sorted `(path, digest)`
pairs: what the pack *as a whole* is.

Two levels rather than one because they answer different questions — "has this
document changed" and "is this the same pack" — and a single flat hash cannot
tell a reviewer which.

The level-two digest deliberately excludes sizes, timestamps and every other
observation. Two checkouts of the same commit on two machines produce the same
pack digest, and a difference in it means content differs rather than that
somebody ran the build on a different day.

## No self-hash

The manifest is a member of the pack, and a manifest containing a digest of
itself could never satisfy its own check: writing the digest changes the bytes
the digest describes.

So `manifest_self_hash` is `null` — by construction, and required to be null
by the schema — and the manifest's member list excludes itself. The pack's
identity is `pack_sha256`, which a verifier recomputes from the members.

This is not pedantry. A self-referential manifest is a check that always fails
or, worse, one somebody "fixes" by excluding the field from comparison, at
which point the manifest is covered by nothing.

## What the pack contains

Twelve artifacts under `data/ths6/`, twenty schemas under `schemas/wp25/`, and
twenty documents under `docs/ths6/final/`.

The documentation set is discovered rather than declared, because it is the
one part of the pack a human edits and a declared list would drift the first
time somebody added a page. The three directory roots are fixed; what is
inside them is measured.

The three preliminary WP-local notes in `docs/ths6/` are **not** pack members.

## Two scans over the rendered bytes

Both run after writing, not before, because the question is whether the
*rendered* documents leak and a check over the inputs would miss a path a
renderer introduced.

- **Absolute paths.** Zero found. A POSIX home directory, a Windows drive
  letter, a UNC path or a path under a system root would each be reported —
  by pattern name and line number, never by quoting the match, because a leak
  report that quoted the leak would be a second copy of it.
- **Credential-shaped content.** Zero found, using WP-23's classifier with its
  own allowlist and negative-fixture classification, so the deliberately
  seeded fixture strings that prove the scanner fires are not re-reported as
  findings.

## Two artifacts that measure, and nine that do not

Three of the twelve committed artifacts are pure declarations — the
contingency matrix, the demonstration manifest and the sign-off matrix — and
are registered with WP-19's reproducibility check for byte-for-byte
comparison between machines.

The other nine measure the working tree: they hash files, or read gate
statuses that are themselves environment-dependent. Comparing one of those
byte for byte between two machines would fail for everybody, which is the
fastest way to teach a team to ignore a reproducibility check. Each is listed
in `ENVIRONMENT_DEPENDENT` with a stated reason.

## The separation this whole page exists for

```
evidence_pack_integrity : true
ths6_achieved           : false
release_may_proceed     : false
```

`verify-pack` exits `0`. `status` exits `2`. Those are different questions
with different answers, they are separate fields in
`data/ths6/wp25-ths6-status.json`, and the schema refuses a document that
derives either from the other.
