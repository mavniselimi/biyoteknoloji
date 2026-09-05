# WP-11 handoff

| Field | Value |
|---|---|
| Document ID | `DOC-HANDOFF-011` |
| Work package | WP-11 — Computable Rule Specification and Validated Rule Registry |
| Status | **Offline scope complete. No real rule exists, none may be created, and the engine-facing registry is empty.** |
| Output for WP-12 | a condition language with exact semantics, two lifecycles, deterministic frozen artifacts, and a read surface that can only serve validated, frozen, verified rules |

> Read this before WP-12. Four items must not be presented as met.
> **A30**, real rules created from approved curations, is **BLOCKED** — no
> curation is approved, so no rule may be created. This is the expected result.
> **A26**, the migration applying under Alembic itself, is **BLOCKED** — Alembic
> cannot be installed here; rendered DDL was run against real PostgreSQL
> instead, and that is supplementary evidence, not a substitute.
> **A24** and **A25** from WP-10 remain blocked and were not touched.
> WP-09's **A21**–**A23** remain blocked and were not touched.

---

## 1. What exists now

| Artefact | What it is |
|---|---|
| `pgx/rules/conditions.py` | `pgx-rule-condition/1`; two operators, everything else refused by name |
| `pgx/rules/models.py` | rule, provenance, outcome, lifecycles, ruleset, manifest |
| `pgx/rules/schema.py` | the rule document contract, every field with its reason |
| `pgx/rules/validator.py` | 56 issue codes in five layers; a pure context |
| `pgx/rules/lifecycle.py` | transition requirements, declared as data |
| `pgx/rules/conflicts.py` | eight kinds, all blocking, none resolved |
| `pgx/rules/builder.py` | deterministic composition, filesystem-free |
| `pgx/rules/serialization.py` | canonical bytes, checksums, atomic publish |
| `pgx/rules/registry.py` | `list_executable` and `load`; nothing else |
| `pgx/rules/ports.py` | five protocols; append-only ones declare no mutation |
| `pgx/rules/memory.py` | the reference implementation |
| `pgx/rules/legacy.py` | the inventory; promotes nothing |
| `pgx/application/rule_service.py` | the one place a rule moves |
| `pgx/application/ruleset_service.py` | the one place a ruleset moves |
| `pgx/application/rule_gate_status.py` | why no real rule may exist |
| `pgx/application/rules_cli.py` | ten read-only commands, nine refused flags |
| `pgx/application/rules_schema.py` | the six published schema loaders |
| `migrations/versions/0008_...py` | 54 columns, 3 tables, 5 functions, 6 triggers |
| `schemas/*.schema.json` | six new published schemas |
| `data/rulesets/` | documentation and two gate reports; **no ruleset** |
| `data/migration/wp11/` | the legacy candidate inventory |

## 2. What WP-12 may rely on

- A rule's condition denotes exactly the gene/drug/phenotype axes it names.
  Nothing expands, defaults or falls through.
- `FrozenRulesetRegistry.load()` returns only fully verified frozen rulesets,
  or raises. There is no partial success.
- Every served rule is `VALIDATED`, pinned by content hash in the manifest,
  and accompanied by an approval list naming four separate people.
- A rule's outcome is one of four attention levels and carries no clinical
  instruction of any kind.
- Determinism: the same membership always produces the same bytes and the same
  semantic hash.

## 3. What WP-12 must not assume

- **That any of this is scientifically true.** Nothing here has been reviewed
  by a scientist. The registry is empty precisely because nothing has.
- That `NOT_ASSESSED` comes from a rule. It does not — it is what WP-12 must
  report when no rule matched, and no rule may assert it.
- That a phenotype with no matching rule is low risk. It is unassessed
  (`SAFETY-INV-001`).
- That conflicts have been resolved. They are detected and blocking; WP-11
  resolves none, and WP-12 must not invent a resolution either.
- That the people named in an approval record are real. WP-23 owns that.

## 4. Verification summary

| Check | Result |
|---|---|
| Full suite | 3,131 passed, 10 skipped, 0 failed |
| WP-11 tests added | 412 |
| Migration 0008 on PostgreSQL 16.13 | applied; 0007→0008→0007→0008 clean |
| Behavioural drill | 24 probes, every guard fired correctly |
| Downgrade with approved data | refused atomically; all objects retained |
| ORM ↔ database column parity | 7 tables, identical sets |
| Determinism | identical bytes under shuffled input, different builders and clocks |
| Real rules created | **0** |
| Real validated rules | **0** |
| Real frozen rulesets | **0** |
| Executable rulesets in the default registry | **0** |

## 5. The first thing WP-12 should read

`data/rulesets/wp11-real-gate-status.json`. It lists ten blockers, each with a
named human owner, and none of them can be cleared by writing code. Until they
are, WP-12 can be built and tested against synthetic fixtures and can assess
nobody.
