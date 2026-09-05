# Canonicalization policy (WP-07)

What a canonical build is, what it is not, and which decisions it is allowed to
make. Companion documents: [resolution-policy.md](resolution-policy.md),
[deduplication-policy.md](deduplication-policy.md),
[data-quality-contract.md](data-quality-contract.md).

## 1. What a canonical build is

One immutable directory holding what a single sealed raw snapshot yielded under
one stated set of rule versions:

| File | Contents |
| --- | --- |
| `manifest.json` | Which snapshot, which rules, which allocation, every file digest |
| `identity-allocation.json` | Canonical key to UUID map, reused on every rebuild |
| `genes.ndjson`, `drugs.ndjson` | Canonical entities, sorted by canonical key |
| `entity-membership.ndjson` | Which build produced which entity, with which UUID |
| `resolution-queue.ndjson` | Everything a human still has to look at |
| `duplicate-groups.ndjson` | Every duplicate group, with every member locator |
| `provenance.ndjson` | One row per entity-to-raw-locator link |
| `dq-report.json` | Metrics, reconciliations, findings, gate decision |
| `legacy-differences.json` | What changed relative to the legacy seed |
| `checksums.sha256` | SHA-256 of every file above |

## 2. What a canonical build is not

It is **not** an approval. Producing one says nothing about whether the data is
fit to publish. The dataset it describes stays `BUILDING`, the manifest says so
in a field and in a sentence, and no code path in `pgx/normalization` can
change it.

It carries **no interpretation**. There is no significance, polarity, score,
severity, risk level, phenotype-to-effect mapping, recommendation, alternative
drug or plain-language conclusion on a canonical record. Those columns exist in
the legacy CSVs, which is exactly why those CSVs are comparison inputs and not
evidence. A test reads the module ASTs and asserts none of those field names is
declared anywhere in the package.

## 3. Normalisation rules

`pgx-normalization/1`.

| Value | Rule | Deliberately not done |
| --- | --- | --- |
| Gene symbol | NFKC, trim, collapse internal whitespace, uppercase, validate against `^[A-Z0-9][A-Z0-9\-.@_]*$` | No fuzzy repair. A symbol that fails validation raises rather than being corrected. |
| Drug name | NFKC, trim, collapse, `casefold` | Salts, formulations and combinations are preserved. `metoprolol tartrate` and `metoprolol succinate` are different products; reducing both to `metoprolol` would be a scientific claim disguised as string cleaning. |
| Container name | NFKC, trim, collapse, `casefold` | Folds `variantAnnotation` and `VariantAnnotation`; does **not** fold `label` and `DrugLabel`, which are different names rather than case variants. |
| External identifier | Namespace case-folded and validated; value trimmed and shape-checked per namespace | A bare value is never compared across namespaces. A malformed value is *returned with its problem*, never discarded: a broken external reference must not look like an absent one. |

`casefold` rather than `lower`: the two disagree on the German sharp s and the
Greek final sigma, and the stronger fold is the correct one for identity.

## 4. Identity

`GeneId` and `DrugId` have no `derive()`, and WP-07 does not add one. A
scientific UUID computed from a name or an external ID would make two
independent curation runs that happened to observe the same string collapse
onto one row, and would let a source's spelling decide this project's identity.

Reproducibility is reconciled with that by writing the mapping down:

1. A build computes canonical keys (`GENE:CYP2C19`, `DRUG:clopidogrel`) — human
   readable, deterministic, and never used as an identity.
2. `allocate_identities` mints `uuid4` for keys that have none, **only** when
   the caller passes `allow_new=True`, and records the mapping in
   `identity-allocation.json`.
3. Every later build reads that artifact. `IdentityAllocation.uuid_for` raises
   on a missing key rather than minting one.

Nothing is ever reclaimed. A canonical key that disappears from a later
snapshot keeps its UUID, so a key that reappears gets the identity it had.
Unused entries are reported, not deleted.

The resolver mints nothing, the builder mints nothing, and tests assert that
neither module so much as references `uuid`.

## 5. Artifact roles

`pgx-artifact-roles/1`. Every artifact in the snapshot is classified, and the
classification decides whether it may contribute records.

| Role | Artifacts | Contributes records |
| --- | --- | --- |
| `ENTITY_CANDIDATE_INPUT` | `resolved_genes.json`, `resolved_chemicals.json` | yes |
| `RELATIONSHIP_REFERENCE_INPUT` | `pair_probe_raw.json` | yes |
| `RAW_ANNOTATION_INPUT` | `variant_annotation_filtered_raw.json` | yes |
| `DERIVED_LEGACY_COMPARISON` | `resolved_genes.csv`, `resolved_chemicals.csv`, `guideline_annotation_rows.csv`, `variant_annotation_filtered_rows.csv`, `pair_annotation_rows.csv` | no |
| `OUT_OF_SCOPE_P1_CANDIDATE_DATA` | `mvp_candidate_drug_gene_edges.{json,csv}` | no |
| `API_SCHEMA_REFERENCE` | `openapi_snapshot.json` | no |
| `UNRECOGNISED` | anything not in the map | no — reported by name and left unread |

**A JSON document and the CSV derived from it are never counted as two
independent records.** The claim that `resolved_genes.csv` is derived from
`resolved_genes.json` is not taken on trust: every build re-verifies that the
two share an identifier set exactly, and a mismatch is a blocking finding that
says the derivation reasoning has stopped holding.

**An unrecognised artifact is reported, never interpreted.** A build that
guessed at an unknown file would invent entities nobody put in the snapshot, so
an unmapped artifact is named, left unread, and blocks the quality gate.

**P1 candidate data is counted and excluded.** `mvp_candidate_drug_gene_edges`
and `candidate_alternatives.csv` describe drugs no reviewer selected. Their row
counts appear in the DQ report so the exclusion is visible and arguable; none
of their content enters the P0 dataset.

## 6. Aliases

An alternative name observed upstream is recorded as a **proposal**, status
`PENDING_REVIEW`, and resolves nothing. Only `APPROVED` participates in
resolution, an `APPROVED` alias must name the reviewer and the instant, and
there is no method, CLI flag or repository call that approves one.

Migration `0005` backfills every pre-existing `gene_aliases` and `drug_aliases`
row to `PENDING_REVIEW`, which is the honest reading: nobody reviewed them. The
practical effect on an existing database is that observed alternative names stop
being able to decide what an entity is. That is the intended correction.

## 7. Determinism and sealing

Given the same snapshot and the same identity allocation, two builds are
byte-identical apart from `manifest.json` (which records `built_at` and this
run's mint/reuse counts) and `checksums.sha256` (which covers it).
`pgx-normalize compare-builds` checks both halves — content hash equality and
byte equality — and reports them separately, because they break for different
reasons.

No wall-clock value enters a content hash. The DQ report carries no generation
timestamp at all, so the same build always evaluates to identical bytes.

Sealing assembles the build in a staging directory on the same filesystem and
moves it with `os.rename`, which fails rather than overwrites. `os.replace` is
deliberately not used. There is no `--force`: a canonical build that could be
rewritten would make every hash recorded against it a claim about nothing in
particular. To produce a competing build, write it elsewhere and compare.

## 8. What this policy will never permit

- Deriving a scientific UUID from a name or an external identifier.
- Approving an alias, deciding a queue item, or marking a dataset
  `QUALITY_CHECKED` without a named human and a recorded instant.
- Fuzzy, substring, phonetic, embedding, LLM or edit-distance matching.
- Reading an unclassified artifact.
- Importing candidate-onboarding data into the P0 dataset.
- Overwriting a sealed build.
