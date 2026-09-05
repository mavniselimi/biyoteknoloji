# Evidence index

145 artifacts are declared, hashed and classified. The machine-readable
inventory is `data/ths6/wp25-evidence-registry.json`; this page explains how
to read it.

## Classification

| Type | Count | What it means |
|---|---|---|
| `REAL_EXECUTED` | 16 | a real operation ran and its result was recorded |
| `REAL_OBSERVED` | 1 | a real system was watched behaving |
| `IMPLEMENTATION_TEST` | 23 | a test passed; a statement about software only |
| `CONFIGURED_NOT_EXECUTED` | 19 | a workflow, image definition or policy exists; nothing ran it |
| `DOCUMENT_ONLY` | 53 | prose: a runbook, protocol, policy or contract |
| `TEST_ONLY_REHEARSAL` | 3 | machinery exercised against labelled fixtures |
| `SCIENTIFIC_PENDING` | 12 | blocked on an approved source, curated rule or metric |
| `HUMAN_PENDING` | 7 | blocked on a named person acting |
| `OPERATIONAL_PENDING` | 6 | blocked on a database, runtime, CI provider or host |
| `STALE` | 3 | records values its own source has since changed |
| `INVALID` | 1 | fails its own published schema |
| `UNAVAILABLE` | 1 | named by a document, not present in the tree |

**Only `REAL_EXECUTED` and `REAL_OBSERVED` may support a THS 6 claim** — 17
of 145. That ratio is the honest shape of this programme: a great deal of
implementation, very little executed result.

## The seventeen admissible artifacts, and what they are not

Every one of them measures software behaviour, a comparison against the legacy
prototype, or the filesystem. The legacy baseline reproduction, the phenotype
and coverage regression reports, the runtime asset manifest, the secret scan,
the separation audit over seven development cases, the reproducibility report.

**None of them is a pharmacogenomic result computed from approved content**,
because no approved content exists. Admissible means "a real event happened
and was recorded"; it does not mean the event was scientifically meaningful.

## Per-item fields

Each entry carries: a stable identifier encoding its work package; a title;
the evidence type; a repository-relative path; a SHA-256 digest (null when
absent); a media type; the schema it declares, when it has one; what generated
it; whether it records a real observation; whether it is test-only; whether it
asserts a number that could be quoted outward; the claims and gates it feeds;
what would make it stale; its schema validation verdict; its limitations; and
who owns each unresolved gap.

## Refusals applied during resolution

- **Absolute paths** are refused at construction. A pack recording
  `/Users/<somebody>/…` describes the machine it was built on and discloses
  whoever built it.
- **Symlinks** are refused rather than followed. A symlinked artifact's digest
  would describe content this repository does not contain.
- **Credential-shaped content** is scanned for with WP-23's classifier before
  any digest is recorded. A positive finding makes the item `INVALID`.

## Schema validation

47 artifacts validated cleanly. One validated with vendor annotations
skipped: WP-16 and WP-17 publish route tables and forbidden-property lists as
`x-pgx-*` keys, which this project's validator refuses because an unchecked
published constraint is a false assurance. WP-25 strips those keys and records
the verdict as `VALID_ANNOTATIONS_SKIPPED` rather than `VALID`, so nobody can
read this pack as having checked them.

One artifact is `INVALID`. See
[`findings-and-discrepancies.md`](findings-and-discrepancies.md).

## The three preliminary documents

`docs/ths6/wp02-foundation-evidence.md`,
`docs/ths6/wp03-release-evidence.md` and
`docs/ths6/wp04-ingestion-evidence.md` predate this pack. They are preserved
unchanged, inventoried as `DOCUMENT_ONLY`, and are not pack members.
