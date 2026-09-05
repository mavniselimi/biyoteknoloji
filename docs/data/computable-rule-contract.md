# The computable rule contract

| Field | Value |
|---|---|
| Document ID | `DOC-DATA-011` |
| Work package | WP-11 — Computable Rule Specification and Validated Rule Registry |
| Schema versions | `pgx-computable-rule/1`, `pgx-rule-condition/1`, `pgx-ruleset-manifest/1` |

---

## 1. What a rule is

One rule is one sentence: *for this gene, this drug and these phenotypes, this
much attention is warranted, and here is the curated reasoning behind it.*

It is deliberately not a program. A reviewer has to be able to check a rule by
reading it, and everything below exists to keep that possible.

## 2. The condition language

```json
{
  "condition_schema_version": "pgx-rule-condition/1",
  "kind": "PGX_AXIS",
  "gene_id": "GENE:CYP2C19",
  "drug_id": "DRUG:clopidogrel",
  "phenotype": {"operator": "ONE_OF", "values": ["POOR", "INTERMEDIATE"]}
}
```

Two operators exist and no more:

| Operator | Means |
|---|---|
| `EXACT` | exactly one phenotype, named |
| `ONE_OF` | any one of the phenotypes explicitly listed |

Everything else is refused by name, with the reason attached to the refusal:
wildcards, `ANY`, `ALL`, `DEFAULT`, negation, regular expressions, ranges,
`LIKE`, expressions, `eval`, SQL fragments, template syntax, and nested
boolean operators. So are unknown keys, unknown genes and drugs, and any
condition referring to a patient or EHR field.

`RAPID` and `ULTRARAPID` are separate values and neither implies the other
(`SAFETY-INV-004`). Covering both requires writing both. `INDETERMINATE` is
not in the rule vocabulary at all: it is the absence of a determination, and a
rule keyed on it would fire on missing data (`SAFETY-INV-001`).

A canonical key must be exactly what WP-07 would allocate for its entity name.
`GENE:CYP2D6 or any hepatic gene` is refused not because a list of forbidden
phrases contains it, but because re-normalising `CYP2D6 or any hepatic gene`
does not reproduce that key. Whether the entity *exists* is a separate check,
made by the validator against the real canonical build.

## 3. The outcome

```json
{"attention_level": "MEDIUM", "rationale_reference": "CWI-0001/REV-000004"}
```

Four levels are authorable: `NO_ACTIVE_ATTENTION`, `LOW`, `MEDIUM`, `HIGH`.

`NOT_ASSESSED` is **not** one of them. It is what a downstream engine reports
when nothing matched; a rule asserting it in advance would be making a claim
about a case it has never seen.

The outcome carries nothing else. A dose, a dose adjustment, a recommendation,
an alternative drug, a treatment instruction, a safety declaration, a risk
score, a ranking and a priority are each refused by field name, in the model,
in the document schema and in the database. The system does not calculate
doses, choose medicines, rank options, or say that anything is safe.

## 4. Provenance: pinned twice

Every upstream dependency is named *and* hashed:

| Identity | Hash | Why both |
|---|---|---|
| `curation_revision_id` | `curation_revision_hash` | the revision could be edited under the rule |
| `protocol_version` | `protocol_content_hash` | the protocol in force could be amended |
| `canonical_build_key` | `canonical_build_content_hash` | the dataset could be rebuilt |
| `evidence_build_key` | `evidence_build_content_hash` | the citations resolve against a specific set of bytes |
| `source_policy_version` | `source_policy_content_hash` | what sources were permitted could change |

Plus `interpretation_id`, `curation_work_item_id`, `dataset_public_id`,
`approval_envelope_hash`, and at least one `evidence_record_uuid`
(`SAFETY-INV-006`).

## 5. The two hashes that bind a rule to its approval

The approval envelope names the rule's content hash. The rule names the
envelope's hash. If the rule's content hash also covered the envelope hash,
neither could be computed.

So `ComputableRuleDefinition.semantic_content()` excludes
`approval_envelope_hash`, and only that field. The binding is mutual and
acyclic: the envelope still pins exactly what was approved, and the rule still
records which approval covers it.

`created_by` and `created_at` are also outside the semantic hash. Two curators
writing the identical claim under identical provenance have made the same
claim; who wrote it and when is recorded and audited, and is not part of what
was claimed.

`metadata` is outside it too, so an editorial note cannot invalidate an
approval.

## 6. Versions, not edits

A rule is immutable from `VALIDATED` onwards. A correction is a new version in
the same `family_id`, naming its predecessor in `supersedes_rule_id`. Version
1 supersedes nothing and may not claim to; version 2 and above must name a
predecessor, or the lineage cannot be reconstructed. A rule may not supersede
itself.

A ruleset containing both a rule and the version that replaced it is a
detected conflict, not a resolved one.
