# WP-09 handoff

| Field | Value |
|---|---|
| Document ID | `DOC-HANDOFF-009` |
| Work package | WP-09 - Scientific Curation Protocol |
| Status | **Offline scope complete. The protocol is not approved, no conclusion has been curated, and no legacy hint has been reviewed.** |
| Output for WP-10 | a versioned curation contract, a field dictionary, a deterministic 9-case inter-curator exercise awaiting two humans, and a 1,559-entry review queue in which nothing is reviewed |

> Read this before WP-10. Three items must not be presented as met.
> **A21**, expert approval of the protocol, is **BLOCKED** — no scientist has
> read it. **A22**, two named curators completing the exercise, is **BLOCKED**.
> **A23**, a real comparison and adjudication record, is **BLOCKED**.
> These were not fabricated and cannot be produced by code.

---

## 1. What exists now

| Artefact | What it is |
|---|---|
| `pgx/curation/vocabulary.py` | Eleven non-ordered vocabularies; `pgx-curation-vocabulary/1` |
| `pgx/curation/models.py` | Question, evidence selection, rationale, conflict, insufficiency, record; `pgx-curation-record/1` |
| `pgx/curation/protocol.py` | 25 requirements, 6 roles, case rules, approval model; `pgx-curation-protocol/1` |
| `pgx/curation/fields.py` | 24 field definitions; `pgx-curation-field-dictionary/1` |
| `pgx/curation/legacy_review.py` | The 1,559-entry review queue; `pgx-curation-legacy-review/1` |
| `pgx/curation/exercises.py` | Packet, templates, comparison, adjudication; `pgx-inter-curator-exercise/1` |
| `pgx/curation/validation.py` | 20 checks, 34 stable issue codes; `pgx-curation-validation/1` |
| `pgx/curation/errors.py` | Seven failure types |
| `pgx/application/curation_protocol_cli.py` | `pgx-curation-protocol`, seven read-only commands |
| `pgx/application/curation_schema.py` | Loads and applies the five published schemas |
| `config/curation/protocol-v1.json` | The protocol, generated from the code |
| `config/curation/field-dictionary-v1.json` | The dictionary, generated from the code |
| `data/curation/protocol-v1/legacy-hint-review-inventory.json` | 1,559 entries, all `NOT_REVIEWED` |
| `data/curation/protocol-v1/exercises/` | Manifest, 9 cases, two blank templates, pending comparison, adjudication template, status |
| `schemas/curation-*.schema.json`, `schemas/inter-curator-*.schema.json` | The five published contracts |
| `scripts/build_curation_artifacts.py` | Regenerates every artifact byte-identically |

Documents: [curation-protocol-v1](../scientific/curation-protocol-v1.md),
[curation-field-dictionary](../scientific/curation-field-dictionary.md),
[curation-review-checklist](../scientific/curation-review-checklist.md),
[conflict-and-insufficiency-guidance](../scientific/conflict-and-insufficiency-guidance.md),
[inter-curator-exercise](../scientific/inter-curator-exercise.md).
Migration: [wp09-manual-hint-review](../migration/wp09-manual-hint-review.md).
Evidence: [wp09-protocol-validation](../evidence/wp09-protocol-validation.md).

## 2. Protocol identity

```
version       pgx-curation-protocol/1
content hash  sha256:e0a76f45b0f606e4fd76d4c31829fcd61825278b01e407b71c13fc38298b56d6
status        AWAITING_EXPERT_REVIEW
requirements  25  (CUR-PROT-001 … CUR-PROT-025)
roles         6
fields        24
vocabularies  11
```

An approval must name this hash. An approval recorded against different content
is refused at construction, because an approval applies to what was read, not
to whatever the document later became.

## 3. The delta WP-10 must resolve

**`CurationStatus` spells `DRAFT` as `RAW`.**

| Protocol (`InterpretationStatus`) | Persisted (`CurationStatus`) |
|---|---|
| `DRAFT` | `RAW` |
| `UNDER_REVIEW` | `UNDER_REVIEW` |
| `CURATED` | `CURATED` |
| `REJECTED` | `REJECTED` |

Same four states, one different name. WP-09 did **not** rename the persisted
enum: that is a migration, and this work package adds none. WP-10 must either
rename it in migration 0007 or map the two explicitly — but must not treat them
as different states.

**Everything else in `CuratedInterpretation` is compatible and was not
weakened.** Its existing invariants — at least one evidence record, and
rationale plus named reviewer plus review instant for `CURATED` — are a subset
of what this protocol requires. A test asserts they are still there.

What the domain model cannot yet carry, and WP-10 will need:

| Protocol concept | Domain model today |
|---|---|
| `CurationQuestion` (gene, drug, phenotype scope, effect dimension, population) | only `normalized_phenotype` |
| Per-evidence relationship and exclusion reason | `evidence_record_ids` is a flat tuple |
| `ConflictAnalysis` | absent |
| `InsufficiencyStatement` | absent |
| Structured 11-part rationale | `rationale` is free text |
| `applicability` | absent |
| `SourceReportedValues` held apart | absent |

None of that is a defect in WP-02's model — it predates this protocol. It is
the shape of the additive change WP-10 will need, and doing it in WP-09 would
have meant persisting a contract nobody has approved.

## 4. What WP-10 inherits as open work

| # | Open item | Count | Why it is open |
|---|---|---:|---|
| 1 | Protocol expert approval | — | No scientist has read it. Status `AWAITING_EXPERT_REVIEW`. |
| 2 | Inter-curator exercise | 9 cases | Two named curators have not been assigned. |
| 3 | Comparison and adjudication | — | Requires those two responses first. |
| 4 | Legacy hints unreviewed | 1,559 | Each needs a human; three are selected for the exercise. |
| 5 | Unlinked legacy proposals | 33 | 11 keyed by gene+drug, 22 without a `PA` accession. |
| 6 | `DRAFT`/`RAW` naming delta | — | §3 above. |
| 7 | 1,572 vs 1,644 collisions | — | Inherited from WP-07. Still unresolved, still not forced. |
| 8 | No source policy approval | — | Inherited from WP-05/WP-08. |
| 9 | Evidence build quarantined | 1,794 records | Inherited from WP-08. Nothing in it is publishable. |

## 5. Defects this work package found and fixed

| What | How it was found |
|---|---|
| `PROHIBITED_CURATION_FIELDS` omitted five names WP-08 already refuses (`effect_direction`, `evidence_strength`, `normalized_effect`, `normalized_phenotype`, `normalized_phenotype_group`) | A test asserting the curation list is a superset of the evidence list |
| One exercise selector described a situation the corpus does not contain (no variant annotation cites more than one publication), silently yielding 7 cases | Case count came out lower than the selector count |
| Selection skewed to `DRUG_LABEL_ANNOTATION` because natural keys sort that way | Reviewing the generated packet: 4 of 7 cases were one type |
| The filesystem-mutation boundary test matched `str.replace` | Two false positives that would have had to be silenced |

## 6. What WP-10 must not assume

- **A structurally complete protocol is not an approved one.** The validator
  reports two verdicts for exactly this reason, and `technical_completeness:
  PASS` alongside `expert_approval: BLOCKED` is the current, correct state.
- **`SELECTED_FOR_EXERCISE` is not a review outcome.** It means a human is
  being asked to look.
- **`is_rule_eligible: true` is not approval.** It says a conclusion is
  complete, unconflicted and unqualified. WP-11 still requires its own review.
- **A blank response template is not a response.** The comparison refuses two
  of them rather than reporting perfect agreement.
- **Agreement between two curators is not correctness.** The comparison reports
  differences and produces no verdict; treating its agreement count as a
  validity measure would be the error the design is built to prevent.
- **No legacy value may become a conclusion.** Not by copying, not by
  acceptance, not by a curator seeing it before forming their own view.

## 7. Reproducing everything in this handoff

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -W error::ResourceWarning \
  -m unittest discover -s tests -p 'test_*.py' -t .

python3 scripts/curation_protocol.py validate --text
python3 scripts/curation_protocol.py approval-status --text
python3 scripts/curation_protocol.py legacy-inventory --limit 5 --text
python3 scripts/curation_protocol.py exercise --text

python3 scripts/build_curation_artifacts.py   # twice; the bytes match
```

No step needs the network or a database.
