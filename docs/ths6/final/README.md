# WP-25 THS 6 evidence pack

This directory is the final evidence pack for the P0 programme. It answers one
question: **does the evidence this repository holds support a THS 6 claim?**

The answer is no, and every document here exists to make that answer checkable
rather than to soften it.

## What this pack is

A machine-readable inventory of every artifact produced between WP-00 and
WP-24, with each one hashed, classified and validated against its own schema;
gates A to F rebuilt from those artifacts by strict conjunction; all fifteen
P0 Definition of Done items evaluated separately; a preflight for the final
demonstration that stops at the first unmet precondition; and a manifest that
hashes the whole pack so a reader can tell whether it still describes the tree
it claims to describe.

## What this pack is not

It is not clinical validation, scientific validation or expert review. It is
not a certification. It does not approve a source, publish a dataset, freeze a
ruleset, complete a review, deploy anything or sign anything, and it contains
no code path that could.

**An intact pack is not an achieved standard.** Those are two separate results
with two separate fields — `evidence_pack_integrity` and `ths6_achieved` — and
neither is ever derived from the other.

## The headline result

| Field | Value |
|---|---|
| WP-25 implementation | IMPLEMENTED |
| Evidence pack integrity | PASS |
| Gates A–F | all BLOCKED |
| Definition of Done | 1 of 15 satisfied |
| Representative demonstration | not executed; preflight stops at DEMO-02 |
| Human sign-offs | 0 of 9 |
| `ths6_achieved` | **false** |
| `release_may_proceed` | **false** |

## Reading order

1. [`executive-summary.md`](executive-summary.md) — Türkçe özet
2. [`limitations-and-scope.md`](limitations-and-scope.md) — what this pack does not cover
3. [`gate-a-scientific-data.md`](gate-a-scientific-data.md) … [`gate-f-ths6.md`](gate-f-ths6.md)
4. [`definition-of-done.md`](definition-of-done.md)
5. [`open-blockers.md`](open-blockers.md) and [`what-remains.md`](what-remains.md)
6. [`verification-instructions.md`](verification-instructions.md) — how to check all of the above yourself

## Authority

Where this prose and the artifacts under `data/ths6/` disagree, **the
artifacts are authoritative.** They are generated from the source gate
statuses; this prose is written by hand and can go stale. `pgx-ths6
verify-pack` tells you whether the pack still matches the tree.

## The preliminary documents in the parent directory

`docs/ths6/` contains three files that predate this pack:
`wp02-foundation-evidence.md`, `wp03-release-evidence.md` and
`wp04-ingestion-evidence.md`. They are preliminary, WP-local technical notes
written by their own work packages. They are preserved unchanged, they are
inventoried here as `DOCUMENT_ONLY` evidence, and they are **not** part of
this pack. WP-24's closing prose stated that no `docs/ths6/` directory
existed; that statement was false and is recorded as a finding.
