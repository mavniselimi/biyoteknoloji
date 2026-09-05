# Deduplication policy (WP-07)

What counts as a duplicate, what does not, and why nothing is ever discarded.

## 1. A gene/drug pair is never a dedup key

Several distinct annotations legitimately describe the same pair — a CPIC
guideline and a DPWG guideline for CYP2C19 and clopidogrel are two records, not
one seen twice. Deduplicating by pair would delete real science.

Every dedup key here is per record type and is anchored on the **source's own
record identity**: `(record_type, semantic_key, source_record_id)`.

| Record type | `semantic_key` | Identity |
| --- | --- | --- |
| `pair_container_record` | `<pair key>|<case-folded container family>` | the record's own `id` |
| `variant_annotation` | the gene the annotation was retrieved for | the record's own `id` |

`pgx-dedup/1`. The version is recorded on every group, so a group produced under
an older key definition is never silently compared with a newer one.

## 2. Identifiers are strings or integers

This source spells identifiers two ways: accession strings such as
`PA166104948` for guideline annotations and labels, and plain integers such as
`981351915` for variant annotations. Both are identities and both are read; an
integer is rendered in its exact decimal form and never reformatted. A reader
that only accepted strings would have reported 3,348 of 3,466 real records as
anonymous — and the fix for *that* would have looked like a data-quality
problem in the source.

Booleans are refused (`True` is an `int` in Python and would become the record
ID `"1"`), and floats are refused rather than coerced.

## 3. Three relationships, kept apart

| Class | Condition | Blocking |
| --- | --- | --- |
| `EXACT` | one source record, one payload, several locators | no |
| `SEMANTIC` | one source record, one payload, several **container spellings** | no |
| `CONFLICTING_IDENTITY` | one source record identity, **different payloads** | **always** |

`SEMANTIC` is `LEGACY-BUG-004`: the pair endpoint returns the same list under
`variantAnnotation` and `VariantAnnotation`, and the legacy flattening wrote one
row per container member, counting both.

`CONFLICTING_IDENTITY` is not a duplicate in any useful sense. Two records
claiming one identity while disagreeing about content mean one of them is
wrong, and discarding either would hide which. Such a group is always blocking,
is never merged, and must state what differs. The database enforces both:
`ck_duplicate_groups_conflict_blocks` refuses a non-blocking conflict and
refuses one with an empty `differences` array.

## 4. Nothing is discarded

Choosing a representative is a **storage convenience**: the smallest digest,
chosen for determinism rather than for quality. Every member's locator survives
in the group, `duplicate_group_members` gives each one its own row, and a test
asserts that choosing a representative never drops one.

That is what makes the collapse reversible and the count checkable.

## 5. A record without a source identity is never merged

Two payloads that happen to be equal are not evidence that they are the same
record, and merging on content alone would silently collapse independent
observations. Such records go to `unidentified`, are counted separately from
duplicates, and block the quality gate — the absence of an identity is the
reason a duplicate finding *could not be made*, which is a different fact from
a duplicate finding.

## 6. Case variants are folded; different names are not

`variantAnnotation` and `VariantAnnotation` fold to one container family.
`label` and `DrugLabel` do **not**: those are different names, and folding them
would be a synonym claim, which this package does not make.

Instead, records reaching one pair query through differently *named* containers
are reported as a `CONTAINER_SYNONYM_UNREVIEWED` finding, with counts and
examples, and the containers stay separate. Whether the two denote the same
thing is a review question, not a string question. On the real snapshot this is
29 records under `label` / `DrugLabel`.

## 7. Determinism

Groups are ordered by key, members by locator, and the representative is the
smallest digest. Two runs over the same observations produce byte-identical
output whatever order the observations arrived in, and a test runs the same set
forwards and backwards to prove it.

Payload comparison uses the project's one canonical JSON encoding, so key order
and incidental whitespace cannot make two identical records look different —
which is precisely what a case-variant container would otherwise do.

## 8. Counts on the real snapshot

Measured from `data/raw/clinpgx-legacy-v2/PGX-DATA-20260830-900`, derived from
the canonical artifacts rather than maintained by hand:

| Measurement | Value |
| --- | --- |
| Total record observations | 3,466 |
| Distinct records | 1,822 |
| Duplicate observations (beyond the first in each group) | 1,644 |
| Duplicate groups | 1,644 |
| — of which `SEMANTIC` (case-variant containers) | 1,644 |
| — of which `EXACT` | 0 |
| — of which `CONFLICTING_IDENTITY` | 0 |
| Records with no source identity | 0 |
| Records reaching one pair query under two container *names* | 29 |

`pair_annotation_rows.csv`, the legacy flattening, holds 3,346 rows — exactly
the number of pair container members, case variants included. That is
`LEGACY-BUG-004` visible in the legacy artifact itself.

**The documented figure of 1,572 is not reproducible.** See
[../migration/wp07-legacy-differences.md](../migration/wp07-legacy-differences.md)
for every alternative measurement that was tried and what each yields. The
dedup key was not reshaped to reach it.
