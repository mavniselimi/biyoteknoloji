# THS 6 Scientific Data Requirements

**Audit type:** read-only requirement derivation
**Audit date:** 2026-09-05 (UTC)
**Method:** requirements below are derived from the repository's own schemas,
domain enums, engine contracts and validation logic — not from a generic
biomedical checklist.

---

## 1. What the architecture actually demands

Four contracts in the repository determine every data requirement. Reading
them in order is the fastest way to understand what the platform needs.

### 1.1 `schemas/computable-rule.schema.json` — the hardest constraint

A rule is refused unless it carries **13 top-level required fields** and a
`provenance` block with **all 15** of:

```
interpretation_id              curation_work_item_id
curation_revision_id           curation_revision_hash
approval_envelope_hash         protocol_version
protocol_content_hash          dataset_public_id
canonical_build_key            canonical_build_content_hash
evidence_build_key             evidence_build_content_hash
source_policy_version          source_policy_content_hash
evidence_record_uuids
```

**Read what this means.** Three of those hashes only exist after a human
acts: `approval_envelope_hash` (a rule approval), `protocol_content_hash` (an
approved curation protocol), `source_policy_content_hash` (an approved source
policy). The data requirement is therefore not "get some guideline content" —
it is "get guideline content **through** an approval chain that produces
three specific hashes."

Rule condition shape: `{kind, gene_id, drug_id, phenotype}`.
Rule outcome shape: `{attention_level ∈ {NO_ACTIVE_ATTENTION, LOW, MEDIUM,
HIGH}, rationale_reference}`.

### 1.2 `pgx/domain/enums.py` — the closed vocabularies

| Enum | Values | Consequence for data |
|---|---|---|
| `Phenotype` | POOR, INTERMEDIATE, NORMAL, RAPID, ULTRARAPID, INDETERMINATE | Source phenotype terms must map onto exactly these six. RAPID ≠ ULTRARAPID (`SAFETY-INV-004`). |
| `AttentionLevel` | NOT_ASSESSED, NO_ACTIVE_ATTENTION, LOW, MEDIUM, HIGH | Every interpretation must land on one of five. `NOT_ASSESSED` is where missing data goes (`SAFETY-INV-001`). |
| `CoverageStatus` | FULL, PARTIAL, INSUFFICIENT, UNSUPPORTED_DRUG, UNSUPPORTED_PHENOTYPE, SOURCE_CONFLICT | Coverage is a first-class answer, not the absence of one. |
| `CoverageReasonCode` | 8 codes incl. `NO_VALIDATED_RULE_FOR_AXIS`, `VALIDATED_RULES_CONFLICT`, `SOME_AXES_NOT_COVERED` | Every gap must be attributable to a named reason. |
| `SourceRole` | PRIMARY_GUIDELINE, SUPPORTING_ANNOTATION, REFERENCE_ONLY, INTERNAL_SYSTEM | A source's role constrains what it may support. |
| `RuleStatus` / `RulesetStatus` / `DatasetStatus` / `ReleaseStatus` | 4 each | One-way lifecycles; nothing reopens. |

### 1.3 `pgx/engine/coverage_manifest.py` — the requirement people miss

> *"For each drug the manifest states which genes should have been considered
> — the expected scope — and separately which phenotype-specific axes are
> actually supported. Nothing can derive the first from the second. … They
> are governed scientific metadata and require a named human declaration."*

**This is a data requirement with no source.** It is not in CPIC, not in a
drug label, not derivable from evidence. Somebody must decide, per drug,
which genes a complete assessment must consider — and be willing to sign it.

Without it, coverage is meaningless: every drug looks fully covered by
whatever rules happen to exist.

### 1.4 `schemas/validation-case.schema.json` — the case boundary

Required: `schema_version, case_id, role, classification, visibility,
is_holdout, is_validation_evidence, content_fingerprint, no_pii_assertion,
created_at, provenance, compatibility`.

- `role ∈ {DEVELOPMENT, INTERNAL_HOLDOUT, EXPERT_HOLDOUT}` — non-overlapping
  by `SAFETY-INV-009`.
- `classification ∈ {SYNTHETIC, PUBLISHED_LITERATURE_DERIVED}` — **there is
  no value for real patient data**, and `SAFETY-INV-011` enforces that real
  patient or genomic data must not enter P0.
- `visibility ∈ {PUBLIC_METADATA, AUTHOR_VISIBLE, RESTRICTED}`.

**So P0 validation is, by design, synthetic or literature-derived.** Any plan
that assumes patient cases is a P2 plan.

---

## 2. Data requirements table

| Data requirement | Exists? | Source | Format | Approval needed? | Blocking what? |
|---|---|---|---|---|---|
| **Gene definitions** | PARTIAL — 5 canonical genes (CYP1A2, CYP2C9, CYP2C19, CYP2D6, CYP3A4) with UUIDs | Legacy `supported_genes.csv` → canonical build | `genes` + `gene_aliases` tables; identity-allocation JSON | YES — dataset quality decision | Gate A2; every rule `condition.gene_id` |
| **Drug definitions** | PARTIAL — 11 canonical drugs with UUIDs | Legacy `supported_drugs.csv` → canonical build | `drugs` + `drug_aliases` | YES — same | Gate A2; every rule `condition.drug_id` |
| **Phenotype definitions** | YES — 6-value closed enum, implemented and tested | `pgx/domain/enums.py` | Enum | NO (fixed by design) | Nothing — this is done |
| **Gene–drug relationships** | PARTIAL / UNTRUSTED — 13 pair-query records observed; 8,182 candidate edges **excluded** as out of P0 scope | Legacy ClinPGx probe output (quarantined) | Evidence entity links (1,946 gene, 2,338 drug) | YES — source approval + curation | Gates A5, B2 |
| **Phenotype–drug interpretations** | **NO — 0** | Would come from CPIC/DPWG guidelines | `curated_interpretations` table | YES — two named curators + adjudication | Gate B2; **this is the core missing scientific content** |
| **Recommendation evidence** | PARTIAL — 1,794 evidence records, 4,051 locators, 1,952 publication refs; **all quarantined, 0 production-eligible** | Legacy migration of `clinpgx_outputs_v2` | `evidence_records` + NDJSON | YES — evidence build approval for rules | Gate A5 |
| **Guideline versions** | **NO** | CPIC/DPWG publication versions | `version_policy` field per source — **null for all 20** | YES — source review | Gate A1; rule `provenance.source_policy_version` |
| **Provenance metadata** | YES (machinery) / NO (content) — the 15-field contract is implemented; no rule exists to carry it | Generated at curation time | Rule `provenance` block | Inherits every upstream approval | Gate B4 |
| **Coverage truth (expected gene scope per drug)** | **NO — 0 declarations** | **No external source. Human declaration only.** | `ruleset-coverage-manifest.schema.json` | **YES — named scientific declaration** | Gates C2/C3; P0-DOD-004 |
| **Source disagreement information** | Machinery YES / content NO — `SOURCE_CONFLICT` status, `VALIDATED_RULES_CONFLICT` reason, `conflicts: []` in the registry, `docs/scientific/source-conflict-policy.md` | Would emerge when ≥2 primary guidelines are curated for one axis | Registry `conflicts` array + coverage reason code | YES — adjudication | Gate B; `SAFETY-INV-008` completeness |

### Two requirements that are fully satisfied

Worth stating so effort is not spent re-doing them:

- **Phenotype vocabulary** — closed, exact-matching, RAPID/ULTRARAPID
  separated, 3 negative controls, `COMPLIANT`/`PASS`.
- **Provenance machinery** — the strictest part of the system, verified over
  fixtures, and the reason nothing ungoverned can be serialised.

---

## 3. What exists today, precisely

```
SOURCES               20 registered · 0 approved · 0 reviewed
                      0 licence identifiers · 17/20 acquisition NOT_DETERMINED
                      17 evidence entries, all NOT_OBTAINED

SNAPSHOT              1 · PGX-DATA-20260830-900 · QUARANTINED · LEGACY_IMPORT
                      12 artifacts · complete: false
                      → cannot become SEALED; needs a NEW dataset id

CANONICAL             16 entities: 11 drugs + 5 genes
                      1,822 distinct records · 3,466 observations
                      1,644 semantic duplicate groups · 29 RESOLVED, 0 unresolved
                      8,182 candidate edges EXCLUDED (P1 scope)
                      dataset_lifecycle_state: BUILDING · DQ passed: false

EVIDENCE              1,794 records · 4,051 locators · 3,432 text fragments
                      1,952 publication references · 1,797 identified publications
                      3,235 blocking issues of 3,486
                      production_eligible_record_count: 0
                      labels: QUARANTINED, LEGACY_MIGRATION, NOT_CURATED,
                              NOT_EXECUTABLE, NOT_PUBLICATION_ELIGIBLE

CURATION              0 interpretations · 0 approval envelopes
                      1,559 legacy proposals: 1,556 NOT_REVIEWED, 3 selected
                      1,526 linked · 33 UNLINKED
                      exercise: AWAITING_HUMAN_CURATORS, 0 curators assigned

RULES                 0 draft · 0 curated · 0 validated · 0 deprecated
                      0 frozen rulesets · 0 executable rulesets
                      real build attempt: REFUSED / NO_VALIDATED_RULES

COVERAGE              0 manifests · 0 executions · 0 supported axes
                      0 expected-gene declarations

ASSESSMENT            0 completed · 0 findings · 0 persisted · 0 reports
RELEASE               0 active

VALIDATION            7 DEVELOPMENT cases (6 migrated + 1 authored)
                      0 INTERNAL_HOLDOUT · 0 EXPERT_HOLDOUT
                      target 50 · shortfall 50
                      15 metric definitions · 0 computed values
                      0 reference judgments · 0 thresholds

EXPERT REVIEW         0 protocol signatories · 0 named reviewers
                      assigned/completed: null (no store inspected)
```

---

## 4. The minimum first validated release

### 4.1 Design principle

The goal is **not** coverage. It is the smallest scope that exercises every
governed mechanism at least once, with enough scientific seriousness that a
reviewer would not dismiss it.

Concretely, the minimum scope must force all of these to fire at least once:

- a `FULL` coverage result,
- a `PARTIAL` coverage result (some axes covered, some not),
- an `INSUFFICIENT` / `NOT_ASSESSED` result (`SAFETY-INV-001`),
- a `RAPID` vs `ULTRARAPID` distinction (`SAFETY-INV-004`),
- at least one axis where two primary guidelines could disagree
  (`SAFETY-INV-008`),
- at least one `UNSUPPORTED_DRUG` refusal.

A scope that only produces `FULL` results proves nothing about the refusal
machinery, which is most of what this platform is.

### 4.2 Recommended minimum scope

| Element | Recommended | Why |
|---|---|---|
| **Genes** | **2** — CYP2C19, CYP2D6 | Both already canonical with UUIDs. CYP2D6 is the only gene in the vocabulary where `ULTRARAPID` is clinically routine, so it is the only one that exercises `SAFETY-INV-004` honestly. CYP2C19 has the cleanest CPIC/DPWG coverage. |
| **Drugs** | **4** — clopidogrel, codeine, omeprazole, amitriptyline | All four are already canonical entities. clopidogrel→CYP2C19 and codeine→CYP2D6 are the two most heavily guidelined pairs in existence; omeprazole→CYP2C19 gives a second, differently-shaped CYP2C19 axis; amitriptyline is the one pair that legitimately spans **both** genes, which is what produces a `PARTIAL` coverage result when only one gene is declared. |
| **Phenotypes** | **5 of 6** — POOR, INTERMEDIATE, NORMAL, RAPID, ULTRARAPID | `INDETERMINATE` is exercised by the refusal path rather than by a rule. RAPID and ULTRARAPID must both appear so their separation is demonstrated, not asserted. |
| **Gene–drug pairs** | **5** — clopidogrel×CYP2C19, codeine×CYP2D6, omeprazole×CYP2C19, amitriptyline×CYP2C19, amitriptyline×CYP2D6 | Five pairs, not four, because amitriptyline contributes two axes — and that is exactly what makes coverage visible. |
| **Validated rules** | **~20–25** | 5 pairs × ~5 phenotypes, minus combinations no guideline addresses. Each rule needs its own 15-field provenance block. |
| **Validation cases** | **50** (P0 target; 100+ preferred) | Not negotiable — `p0_target_case_count: 50` is in the artifact. Split as ~30 DEVELOPMENT + 20 INTERNAL_HOLDOUT is **wrong**: development cases must not count. See below. |
| **Holdout cases** | **≥20 INTERNAL_HOLDOUT + ≥10 EXPERT_HOLDOUT** | The 50 must be validation evidence. Development cases are contractually excluded, so 50 means 50 *beyond* the existing 7. |
| **Expert cases** | **≥10** | Enough for 4 Likert dimensions to produce a non-trivial distribution across at least 2 reviewers. |

### 4.3 Per-element justification

**CYP2C19 + CYP2D6, not five genes.**
- *Included because:* both are already canonical entities with allocated
  UUIDs, both appear in the 5-gene legacy set, and between them they cover
  the four recommended drugs.
- *Source support:* CPIC has dedicated guidelines for both;
  DPWG/KNMP publishes recommendations for both; multiple drug labels
  (FDA, EMA, TITCK) carry PGx statements for clopidogrel and codeine.
- *Existing repository logic:* `pgx/engine/phenotype.py` matches exactly on
  the 6-value enum; `phenotype_normalization.py` maps source spellings.
  Nothing gene-specific is hard-coded, so 2 genes cost the same as 5 in code.
- *Still missing:* an approved source, a curated interpretation per axis, and
  the expected-gene-scope declaration.

**CYP1A2, CYP2C9, CYP3A4 deliberately excluded from the first release.**
CYP2C9 (warfarin) is scientifically important but warfarin dosing brings
dose-algorithm expectations that P0's `AttentionLevel` model deliberately
does not represent — including it invites a claim the system cannot make.
CYP1A2 and CYP3A4 have thinner actionable guideline coverage. Excluding them
also gives the first release a genuine `UNSUPPORTED_DRUG` /
`SOME_AXES_NOT_COVERED` path with real content behind it.

**Four drugs, not eleven.**
- *Included because:* each is already canonical, and each contributes a
  distinct coverage shape (single-gene clean, single-gene with an
  ultrarapid phenotype, second single-gene axis, two-gene spanning).
- *Source support:* CPIC guidelines exist for clopidogrel–CYP2C19,
  codeine–CYP2D6, amitriptyline–CYP2C19/CYP2D6; DPWG covers omeprazole–CYP2C19.
- *Existing repository logic:* `coverage.py` already computes per-axis
  status; `risk.py` already emits `NOT_ASSESSED`; the report renderer already
  separates coverage from attention.
- *Still missing:* the interpretations, the rules and the declared scope.

**Why not tamoxifen.** It is canonical and heavily guidelined, but the
tamoxifen–CYP2D6 evidence base is genuinely contested. That makes it an
excellent *second*-release case for `SOURCE_CONFLICT`, and a poor first-release
case, because the first release should demonstrate the mechanism rather than
litigate a controversy.

### 4.4 What the first release does **not** include

- No real patient data — structurally impossible in P0.
- No LLM narration — P1-06.
- No candidate exploration or alternative ranking — P1, and
  `SAFETY-INV-005` records the surface as `NOT_PRESENT`.
- No dose recommendations of any kind. The outcome vocabulary is
  `AttentionLevel`, not a dose.

---

## 5. Required sources and evidence types for that scope

| Source | Role | Needed for | Approval blocker |
|---|---|---|---|
| `cpic.publications` / `cpic.api` / `cpic.database` | PRIMARY_GUIDELINE | All 5 axes | Licence terms not retrieved; acquisition mode NOT_DETERMINED |
| `dpwg.knmp` | PRIMARY_GUIDELINE | omeprazole, second opinion on clopidogrel/codeine | Same |
| `druglabel.fda` | PRIMARY_GUIDELINE | Regulatory statement for clopidogrel, codeine | Same |
| `druglabel.titck` | PRIMARY_GUIDELINE | Turkish SmPC — relevant because the report's default locale is `tr` | Same |
| `clinpgx.api` | SUPPORTING_ANNOTATION | Allele/phenotype annotation | Same |
| `pubmed.literature` | REFERENCE_ONLY | Citations behind the above; source of `PUBLISHED_LITERATURE_DERIVED` validation cases | Same |

**Minimum viable source set: 3** — one CPIC entry, `dpwg.knmp`, and
`clinpgx.api`. Adding `druglabel.fda` and `druglabel.titck` is what makes the
release defensible rather than merely functional, because it gives at least
one axis two independent primary sources and therefore a real chance of
exercising `SOURCE_CONFLICT`.

### Evidence types required per axis

Derived from the `EvidenceRecord` contract and the rule provenance block:

1. A **locator** — the exact document, section and version the statement came
   from (`evidence-provenance.ndjson` shape; 4,051 already exist for legacy
   content).
2. A **text fragment** — the verbatim statement (3,432 already exist).
3. A **publication reference** where the guideline cites primary literature
   (1,952 already exist).
4. A **guideline version** — currently `null` for all 20 sources. **This is
   the single most commonly forgotten field**, and rule provenance requires
   `source_policy_version`, which depends on it.

---

## 6. Effort shape, stated honestly

Assumption stated explicitly: this is a rough order-of-magnitude sketch to
support planning, not an estimate anyone should commit to.

| Work | Who | Rough shape |
|---|---|---|
| Retrieve + interpret licence terms for 3–6 sources | AI drafts, human decides | days of human reading, not weeks |
| Approve the curation protocol | 1 domain expert | one review cycle |
| New acquisition run + sealed snapshot + canonical build | AI, given network | hours of compute |
| Curate ~25 interpretations under protocol, 2 curators + adjudication | 2 curators + 1 adjudicator | **this is the long pole** |
| Declare expected gene scope for 4 drugs | 1 scientific declaration | hours, but blocked on the protocol |
| Author 50 validation cases + 30 holdout | AI drafts candidates, validation owner approves | weeks |
| Blind-first expert review of ≥10 expert-holdout cases | ≥2 named experts | scheduling-bound |
| Database, CI, image, staging, backup/restore, performance | platform owner + AI | days, given infrastructure |

The critical path is **not** engineering. It is: source approval → protocol
approval → curation → scope declaration → validation authoring → expert
review. Five of those six steps are gated on named people.
