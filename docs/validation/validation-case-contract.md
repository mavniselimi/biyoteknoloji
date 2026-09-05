# WP-18 — What a validation case is

## Two objects, not one

| | `ValidationCaseMetadata` | `RestrictedPayload` |
| --- | --- | --- |
| Published in manifests | yes | never |
| Committed to this repository | yes | never |
| Holds an expected answer | **no field for one** | **no field for one** |
| Holds inputs | no | yes |

A case is split rather than flagged. A single class with a visibility boolean
publishes its restricted half the first time somebody serialises it without
reading the flag.

## Required of every case

| Field | Why it is required |
| --- | --- |
| `case_id` | A `PGX-VAL-…` type, not a string. A plain string compares equal to any other string spelled the same. |
| `role` | One of three, for the case's lifetime. Not mutable, not widenable. |
| `classification` | `SYNTHETIC` or `PUBLISHED_LITERATURE_DERIVED`. There is no third member and in particular none meaning "real patient". |
| `provenance` | Source identity, derivation method, and whether it came from development. |
| `content_fingerprint` | Canonical identity of the case's content. |
| `no_pii_assertion` | Stated in the author's own words, at least 16 characters. An empty assertion is not one. |
| `created_at` | UTC. |
| `compatibility` | At least one declared version constraint. |
| `visibility` | Defaulted from the role, and a holdout may not be constructed author-visible. |

Optional: `payload_hash`, `payload_reference`, `title`, `notes`, `extra`.
`extra` is walked against the prohibited list like everything else, so it is
not a back door.

## Provenance

`derived_from_development` is a **boolean the author states**, not something
inferred. A case built by editing a demo profile is not independent however
much it has been changed, and only its author knows. Inferring it would mean a
rename could defeat the check.

A holdout must additionally carry a `source_digest` **or** a `citation`.
Independence that cannot be shown is not independence, and the constructor
refuses rather than warning.

## Fingerprints

**Content fingerprint** — canonical identity. Ignores key order, order within
`observations`, `medications` and `source_citations`, Unicode form, and
surrounding whitespace. Sensitive to every scientific difference: a changed
phenotype, a changed gene, an added observation, a changed medication, a
repeated observation.

Display text is not part of it. Two cases with near-identical titles are the
same case only if their content is the same, and different if it is not.

**Derivation family fingerprint** — `(source_identity, derivation_method)`,
case-folded and NFC-normalised. Two cases from one vignette by one hand are one
family even when their content differs. That is the pair a content hash cannot
catch, and the pair a partition must still refuse to split.

**Payload hash** — the digest of the payload as stored. A reformatted payload
keeps its fingerprint and changes its hash; both questions get asked.

## What a case may never contain

At any depth, in metadata or payload:

- **Real-patient data** — patient names and identifiers, MRN, date of birth,
  EHR extracts, encounters, laboratory and pathology reports, clinical notes,
  free text, diagnosis, indication, dose.
- **Genotype-level input** — genotype, diplotype, haplotype, star allele,
  activity score, variants, zygosity, rsID, VCF, FASTQ, BAM, CRAM, SAM, raw
  sequence.
- **Expected answers** — expected result, attention or coverage, gold
  standard, ground truth, reference answer, answer key, score, grade,
  concordance, accuracy, pass rate, rank.
- **Arbitrary uploads** — upload, uploaded file, attachment, file content,
  blob.

Refused by name, case-insensitively, with padding stripped, at any nesting
depth. The refusal names the **location** and never the value: an error raised
over a genotype must not carry the genotype into a log.

## What a case may contain

Public gene symbols and published scientific identifiers. `CYP2C19` is
governed vocabulary. A gene's name is not data about a person, and refusing it
would leave the package unable to describe a case.

## Release compatibility

Four independent fields — software version, dataset public id, ruleset public
id, release public id (plus the manifest hash) — because they move
independently. At least one must be declared.

Comparing a declaration with a deployment returns `NOT_DECLARED`, `UNKNOWN`,
`MATCH` or `MISMATCH` per field. **A missing active release yields `UNKNOWN`,
never `MISMATCH`**: "there is no release to compare against" and "the release
is the wrong one" are different facts and only the second is an error.

Nothing in WP-18 activates, registers or invents a release.
