# WP-11 — computable rules and immutable rulesets

| Field | Value |
|---|---|
| Document ID | `DOC-ARCH-011` |
| Work package | WP-11 — Computable Rule Specification and Validated Rule Registry |
| Depends on | WP-07 canonical entities, WP-08 evidence build, WP-09 protocol, WP-10 workflow and approval envelope |
| Hands to | WP-12, which will evaluate rules; WP-11 evaluates nothing |

---

## 1. Where this sits

```
RawArtifact → Canonical Entity → EvidenceRecord → CuratedInterpretation
            → ComputableRule → RulesetVersion → (WP-12) AssessmentFinding
```

WP-11 owns the two boxes in the middle of that arrow and neither box on
either side of them. It says what may be executed. It executes nothing.

## 2. The package

| Module | What it holds |
|---|---|
| `pgx/rules/conditions.py` | the declarative condition grammar and its refusals |
| `pgx/rules/models.py` | rule, provenance, outcome, lifecycle record, ruleset, manifest |
| `pgx/rules/schema.py` | the rule document contract, field by field, with reasons |
| `pgx/rules/validator.py` | 56 issue codes across five layers |
| `pgx/rules/lifecycle.py` | what each transition requires, and who may make it |
| `pgx/rules/conflicts.py` | eight conflict kinds, all blocking, none resolved |
| `pgx/rules/builder.py` | deterministic composition of a frozen artifact |
| `pgx/rules/serialization.py` | canonical bytes, checksums, atomic publication |
| `pgx/rules/registry.py` | the engine-facing read surface |
| `pgx/rules/ports.py` | five protocols; the append-only ones declare no mutation |
| `pgx/rules/memory.py` | the reference implementation of those ports |
| `pgx/rules/legacy.py` | the legacy candidate inventory; promotes nothing |

`pgx/rules` is stdlib-only and imports `pgx.domain`, `pgx.curation` and
`pgx.normalization` — all layers beneath it. It imports no infrastructure, no
framework and no network client. `pgx/application` holds the two services that
drive the lifecycles, the CLI, the schema loader and the gate-status reader.

## 3. Two lifecycles

```
rule:     DRAFT ──→ CURATED ──→ VALIDATED ──→ DEPRECATED
ruleset:  BUILDING ──→ VALIDATED ──→ FROZEN ──→ RETIRED
                ↑          │
                └──────────┘   (reopen)
```

Only `VALIDATED` rules execute. Only `FROZEN` rulesets are served. There is no
`BUILDING → FROZEN` edge: validating and freezing are two audited acts, and
collapsing them would let a set become permanent without anybody deciding it
should. Nothing unfreezes — a frozen artifact may have been acted on, so the
way to change it is to publish a new version and retire this one.

Every transition is a guarded `UPDATE ... WHERE id AND status AND version`
returning an affected-row count. One means it happened; zero means somebody
else moved first.

## 4. Five validation layers

| Layer | Question | Owner of a failure |
|---|---|---|
| A | is the document well formed? | the author |
| B | do the things it names exist? | the dataset and evidence builds |
| C | may this actor make this transition now? | identity, and WP-23 |
| D | is the curated conclusion one a rule may encode? | the curator |
| E | can these rules be a ruleset together? | whoever assembled the set |

Layers are separate because the answers are owned by different people. Every
layer reports every issue it finds; an author fixing one problem per round
trip is an author who gives up.

`ValidationContext` is a pure value: the caller supplies every fact, so the
validator cannot reach a database and cannot decide anything about the real
world by accident. It fails closed — an empty catalogue means nothing is known
to exist, not that everything is fine.

## 5. Determinism

A ruleset's identity is its content. `manifest.json`, `rules.ndjson` and
`approval-list.json` are byte-identical for the same membership regardless of
input order, builder, clock, process, insertion order, database row order,
dictionary order or machine. `build-log.json` records who built it and when,
and is excluded from every hash — which is exactly what makes the rest
assertable.

The artifact carries `checksums.sha256` in `sha256sum` format. Publication is
atomic (staged beside the destination, verified, then `os.replace`) and
refuses to overwrite an existing artifact.

## 6. Conflicts are detected, never resolved

Eight kinds, every one blocking: exact duplicate, redundant overlap,
conflicting outcome, identity collision, version lineage error, dataset
boundary conflict, protocol boundary conflict, superseded member present.

There is no priority field, no rule ordering, no "most severe wins" and no
automatic resolution anywhere in this layer. A disagreement between two
approved rules is a question for the people who approved them
(`SAFETY-INV-008`).

## 7. The structural axes list is not coverage

`manifest.structural_axes` inventories the gene/drug/phenotype triples the
member rules are keyed on. The existence of a rule for an axis says nothing
about whether that axis is adequately covered. The manifest carries no
coverage, completeness, quality or confidence field, and the schema refuses
one.

## 8. What WP-11 does not do

It does not diagnose, infer genotype-to-phenotype relationships, implement
phenoconversion or drug-interaction adjustment, calculate or recommend doses,
choose or rank medicines, declare anything safe, generate treatment
instructions, infer rules from free text, or ask a language model to write a
condition or an outcome. It does not promote legacy rows, and it does not
approve anything.
