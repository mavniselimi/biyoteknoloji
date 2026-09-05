# WP-18 — Validation dataset architecture: curation versus holdout

## What this layer is

The machinery that makes three kinds of case structurally different, and makes
mixing them something the code refuses rather than something a document asks
people not to do.

```
a case is authored
  -> ValidationCaseMetadata   (publishable; no field for an answer)
  -> RestrictedPayload        (inputs; never committed beside the rules)
  -> canonical fingerprints   (content identity + derivation family)
  -> separation audit         (eight rules, reported together)
  -> public manifest          (identities and counts; no content)
```

It does **not** compute a metric. WP-21 owns that, and it cannot start honestly
until there is something to count.

## The three roles

| Role | May inform rule design? | Payload visible to authors? | Counts as evidence? |
| --- | --- | --- | --- |
| `DEVELOPMENT` | yes | yes | **no** |
| `INTERNAL_HOLDOUT` | no | no | yes |
| `EXPERT_HOLDOUT` | no | no — released only by WP-22's protocol | yes |

Exactly three members, and `pgx/validation/vocabulary.py` explains why it is
not WP-09's six-member `CaseRole`: `TRAINING`, `CALIBRATION` and
`INTER_CURATOR_EXERCISE` describe curation exercises rather than validation
partitions, and a dataset that accepted them would have three extra answers to
"which side of the line is this on". `CURATION_ROLE_EQUIVALENT` maps the three
onto WP-09's vocabulary and a test asserts the map is total, so the two cannot
drift.

## A case is two objects

`ValidationCaseMetadata` is publishable and **has no field for an expected
result**. `RestrictedPayload` carries the inputs and is never published.

The split is structural because a flag is not. One class with
`expected_result: Optional[...]` and `public: bool` publishes the expected
result the first time somebody serialises it without reading the flag, and that
mistake is invisible in review. Here `metadata.to_json()` is safe by
construction: there is nothing to leave out.

There is **no expected result anywhere in WP-18** — not in the metadata, not in
the payload, not in the schemas. What the correct output is, is a scientific
judgement recorded under WP-22's protocol by a named expert. A field for it
here would invite filling it, and an AI-authored expected answer is precisely
what this repository may not produce.

## Eight ways the partition breaks

`pgx/validation/separation.py`. Each rule catches something the previous one
does not:

1. **Role overlap** — one identifier, two roles. The obvious one.
2. **Content duplicate across partitions** — different identifiers, same
   canonical content. What copy-and-rename looks like.
3. **Content duplicate within a partition** — not a leak, but a denominator
   counting one case twice.
4. **Derivation family split** — different identifiers *and* different
   content, one source vignette, one method. Neither 1 nor 2 sees it, and it
   leaks: whoever wrote the development case has read the source.
5. **Holdout derived from development** — declared by the author, refused.
6. **Development relabelled as holdout** — invisible in a single snapshot, so
   the audit takes a previous `{case_id: role}` record.
7. **Holdout provenance missing** — independence that cannot be shown is not
   independence.
8. **Release compatibility conflict** — cases in one partition written against
   incompatible versions cannot be aggregated.

The audit **reads no payload**, so running it is not seeing a holdout and
anybody may run it — including a rule author, which is the point. A test
asserts that by reading the module's syntax tree.

## Fingerprints

Content identity is canonical over four normalisations, each removing a
difference that carries no scientific meaning: key order, order within
`observations` / `medications` / `source_citations`, Unicode form (NFC), and
surrounding whitespace.

The **opposite** direction is the more dangerous one and is tested separately.
A false distinction inflates a denominator; a false collapse *hides a case
entirely*. So order-insensitivity applies to three named fields rather than to
every list, display text has no vote at all, and changed phenotypes, genes,
medications and repeated observations each change the fingerprint.

`derivation_family_fingerprint` is the identity a content hash cannot see: one
source, one method, however different the resulting cases.

## Visibility and who-has-seen

`pgx/validation/access.py` decides, then records. Every attempt appends one
event — refusals too, because a log of successes answers "who read this" and
not "who tried".

**Nothing here is authenticated.** An `AccessContext` is a caller's claim about
itself; every event carries `actor_authenticated: false`, the published schema
pins that value with `const`, and no code path sets it true. WP-23 owns
identity.

**A refusal teaches nothing.** The decision never consults whether a payload
exists, the loader is not called when a read is refused, and the error carries
a coarse reason code and the case identifier. A caller who could distinguish
"denied, and there is an answer" from "denied, and there is not" would have
learned something from being refused.

The ledger exposes no way to replace or remove an entry, and each event carries
the digest of the one before it — so editing an old event breaks the chain from
that point on and `verify_chain()` says where.

## Restricted import

`pgx/validation/restricted_import.py` is the boundary WP-22 will bring an
expert payload through. Nothing has ever passed through it: there is no
restricted storage in this repository and no payload is committed.

Schema before persistence; role and provenance enforced; **hashes computed
here, never trusted from input**; traversal and symlink refused after
resolution rather than before; atomic write via a temporary file in the
destination directory, fsync, rename; every refusal before the rename so a
failed import leaves exactly what was there; controlled issue codes rather than
raw exceptions, because the exceptions underneath quote paths.

**No payload is ever logged** — not on success, not on failure, not in an
exception message. That is why the issue codes are coarse.

## Release compatibility

Four fields, separate because they move separately: `software_version`,
`dataset_public_id`, `ruleset_public_id`, `release_public_id` (plus the
manifest hash). A case must declare at least one — "compatible with anything"
is not a claim a validation run can check.

`resolved_against()` returns `UNKNOWN` rather than `MISMATCH` for anything the
deployment cannot supply. **A missing active release is not a mismatch**, and
nothing here activates or invents one.

## The real-data boundary

`PROHIBITED_CASE_FIELDS` refuses, at any nesting depth, in metadata and in
payloads: raw sequencing (VCF, FASTQ, BAM, CRAM), genotype-level input
(diplotype, star allele, activity score), laboratory reports and EHR extracts,
patient identifiers, diagnosis, indication, dose, free clinical text, arbitrary
uploads, and every name an expected answer could be given.

Public gene symbols are **not** refused. `CYP2C19` is published nomenclature
and governed vocabulary; refusing it would confuse the name of a gene with data
about a person, and would make the package unable to describe a case at all.

Real-patient ingestion is P2-03/P2-04 and is not implemented here. The gate
status reports `real_patient_case_count: 0` with the source
"structurally zero" — there is no path by which one could exist.

## Why P1–P6 are development

They demonstrated the same rules they would be measured against. Using them as
validation evidence would report memory as generalisation, which is what
`SAFETY-INV-009` names. The seven WP-17 cases are a **view** over
`data/demo/wp17-development-cases.json` rather than a copy — one source, no
drift — and `pgx/validation/catalog.py` refuses to build them if that file ever
stops declaring them development.

## Artifacts

`python -m pgx.application.validation_cli artifacts` regenerates five schemas
and four data documents, deterministically. Every generated document is
validated against its own published schema before it is returned: a generator
emitting something its schema rejects is publishing a constraint it does not
keep.
