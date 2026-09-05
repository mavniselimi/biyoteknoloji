# PGx Platform V2 - Intended Purpose and Claims Boundary

| Field | Value |
|---|---|
| Document ID | `DOC-IP-001` |
| Document version | `0.1.0-draft` |
| Status | **DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW** |
| Work package | WP-00 - Intended Purpose, Claims Boundary, and Safety Contract |
| Machine-readable counterpart | `pgx/domain/claims.py` (`P0_CLAIM_BOUNDARY`) |
| Companion document | `docs/risk-management/safety-contract.md` |
| Architecture source | `architecture.md` sections 2.1, 2.2, 2.3, 3, 19, 23 |
| Created | 2026-08-29 |
| Approved by | *(not approved - see section 11)* |

> **This document is not approved.** It was drafted by an implementation
> agent under WP-00. It records a *proposed* intended purpose. It does not
> constitute clinical, regulatory, or scientific approval, and nothing in
> it may be cited as evidence of expert review. Section 11 lists the
> signatures required before the status line may change.

---

## 1. Official intended-purpose statement

> PGx Platform V2 is a **research and prototype decision-support
> demonstrator**. It evaluates a **synthetic or protocol-defined CYP
> phenotype profile** together with a **medication list** against a
> **versioned, expert-governed pharmacogenetic ruleset**, and produces
> **deterministic, evidence-linked attention findings** plus a **separate
> coverage assessment**.
>
> The system is designed to demonstrate **traceable** pharmacogenetic
> assessment. **It is not a clinical decision-maker**, it is not a medical
> device, and it is not authorised for clinical, diagnostic, or patient-care
> use.

The purpose of the system is to make the *reasoning path* auditable: which
phenotype matched which validated rule, backed by which evidence record,
under which dataset, ruleset, and software version, and what was **not**
assessed and why.

Producing a broad set of findings is explicitly **not** the objective. A
narrow validated ruleset with an honest `INSUFFICIENT` coverage statement is
the preferred outcome (`architecture.md` section 24).

## 2. Target users

| User | Role in the system | What they may do | What they may not do |
|---|---|---|---|
| Demonstration user / jury evaluator | `DEMO_USER` | Run predefined synthetic demo profiles; read structured reports and their version metadata | Use output for any real patient |
| Clinician or pharmacist as *evaluator* | `DEMO_USER`, `EXPERT_REVIEWER` | Assess whether findings, coverage, and traceability are scientifically defensible | Apply output to care of a real patient |
| Pharmacogenetics / clinical pharmacology expert reviewer | `EXPERT_REVIEWER` | Perform blind holdout review under the approved protocol (WP-22) | See development cases before blind review |
| Scientific curator | `ADMIN` (curation scope) | Propose, review, and approve rules under WP-09/WP-10 | Approve their own rule without the recorded second reviewer |
| Platform administrator / developer | `ADMIN` | Manage releases, sources, users, and audit | Alter a calculated finding or an approval record |

The system has **no patient-facing user role** in P0. There is no public
signup (`architecture.md` section 13).

## 3. Data the system may use

**Permitted inputs (P0)** - enumerated as `PermittedInputKind` in
`pgx/domain/claims.py`:

| Input kind | Description |
|---|---|
| `SYNTHETIC_PHENOTYPE_PROFILE` | Fabricated CYP gene-to-phenotype maps created for demonstration |
| `PROTOCOL_DEFINED_PHENOTYPE_PROFILE` | Phenotype profiles defined by a written validation protocol |
| `PUBLIC_DEMO_PROFILE` | Published, non-identifiable demonstration profiles |
| `VERSIONED_VALIDATION_CASE` | Immutable validation cases with a recorded role, provenance, and no-PII assertion |
| `MEDICATION_NAME_LIST` | A list of medication names to be assessed |

Phenotypes are supplied as already-normalised values from the P0 phenotype
model (`POOR`, `INTERMEDIATE`, `NORMAL`, `RAPID`, `ULTRARAPID`,
`INDETERMINATE`). Matching is exact; the engine never infers phenotype
synonyms at runtime (`architecture.md` section 9.1).

**Prohibited inputs (P0)**

- real patient VCF, FASTQ, BAM, or any raw sequencing output;
- real genotype, diplotype, star-allele, or laboratory reports;
- EHR extracts, clinical narratives, or free-text case notes;
- direct or indirect patient identifiers of any kind;
- any data whose licence or provenance has not been recorded under WP-05.

No free-text clinical narrative may influence P0 risk calculation
(`architecture.md` section 9.4).

## 4. Operating modes

Defined in code as `OperationMode` in `pgx/domain/claims.py` and enforced by
`is_mode_enabled()` / `require_mode_enabled()`.

| Mode | Status in P0 | Allowed input | Intended use | Persistence | Claim language |
|---|---|---|---|---|---|
| `DEMO` | **Enabled** | Synthetic cases and public demo profiles | Jury demonstration and training | May persist | Research/prototype only |
| `VALIDATION` | **Enabled** | Versioned development, internal holdout, or expert holdout cases | Software and scientific validation | Must persist with case role and release bundle | Validation result only |
| `PILOT` | **DISABLED** | *(none - not implemented)* | Future protocol-defined pilot | Not implemented | P2 gate required |

### 4.1 `PILOT` is disabled in P0

`PILOT` exists in the enum so that the disabled state is **explicit,
testable, and auditable** rather than merely absent. `P0_ENABLED_MODES`
contains only `DEMO` and `VALIDATION`; requesting `PILOT` raises
`ModeNotEnabledError`, and `tests/unit/test_claims.py` asserts this.

`PILOT` may be enabled only after **all** of the following exist as recorded
artifacts, not intentions:

1. a formally expanded intended purpose approved by the named human owner
   and the named scientific advisor;
2. a privacy, consent, and ethics package appropriate to the jurisdiction
   and the operational partner (`architecture.md` P2-02, P2-03);
3. a security and data-protection assessment covering identifiable data;
4. completed independent validation with holdout and blind expert results
   (Gate D);
5. an Architecture Decision Record under `docs/architecture/decisions/`
   (`architecture.md` section 23).

Until then, `PILOT` remains a placeholder. Partial or informal satisfaction
of the list above does not open the gate.

## 5. Nature of the system output

The system output is a **deterministic, versioned, evidence-linked
structured assessment**, rendered as a deterministic report.

Each output:

- states an **attention level** (`NOT_ASSESSED`, `NO_ACTIVE_ATTENTION`,
  `LOW`, `MEDIUM`, `HIGH`) - deliberately named *attention*, not *risk
  score*, and `NOT_ASSESSED` is **not** ordered against the others;
- states a **coverage status** (`FULL`, `PARTIAL`, `INSUFFICIENT`,
  `UNSUPPORTED_DRUG`, `UNSUPPORTED_PHENOTYPE`, `SOURCE_CONFLICT`) with
  machine-readable reason codes, as a **separate first-class output**;
- cites the exact phenotype, the validated rule and rule version, and at
  least one traceable evidence reference for every calculated finding;
- carries the release bundle identity (software, dataset, ruleset) and the
  input/output hashes;
- carries the canonical warning text of section 6.

The deterministic report is the **final P0 report**. It works offline and
without an API key. An LLM rendering is optional, downstream, off by
default, and may never alter a calculated fact (`architecture.md`
sections 10.1, 10.3).

Attention findings are **observations that a documented pharmacogenetic
relationship exists for a phenotype-drug axis**. They are not clinical
conclusions about a person.

## 6. Canonical warning text

There is exactly one warning text per language. It lives in
`pgx/domain/claims.py` as `CANONICAL_CLINICAL_WARNING_TR` /
`CANONICAL_CLINICAL_WARNING_EN`, and is read through
`canonical_clinical_warning(language)`. API, UI, and reporting layers must
**not** author their own variant.

**Turkish (canonical):**

> Bu çıktı klinik karar, tanı, doz önerisi veya tedavi önerisi değildir.
> PGx Platform V2, araştırma/prototip amaçlı bir karar destek
> göstericisidir; sentetik veya protokolle tanımlanmış fenotip profillerini
> sürümlenmiş ve uzman yönetimli bir farmakogenetik kural kümesiyle
> karşılaştırarak izlenebilir dikkat bulguları ve bunlardan ayrı bir kapsam
> değerlendirmesi üretir. Eksik veri düşük risk anlamına gelmez. Doz, ilaç
> değişimi ve tedavi kararı yalnızca yetkili hekim tarafından; klinik tablo,
> endikasyon, laboratuvar sonuçları ve güncel kılavuzlar dikkate alınarak
> verilir.

**English (canonical):**

> This output is not a clinical decision, a diagnosis, a dose
> recommendation, or a treatment recommendation. PGx Platform V2 is a
> research/prototype decision-support demonstrator: it compares synthetic or
> protocol-defined phenotype profiles against a versioned, expert-governed
> pharmacogenetic ruleset and produces traceable attention findings plus a
> separate coverage assessment. Missing data does not mean low risk. Dose,
> medication change, and treatment decisions are made only by a qualified
> physician, considering the clinical picture, indication, laboratory
> results, and current guidelines.

## 7. DOES NOT list

The system **DOES NOT**, and must never be described as if it does:

| # | The system DOES NOT | Category in `pgx/domain/claims.py` |
|---|---|---|
| 1 | **diagnose** a condition, or state that a person has a disease | `DIAGNOSIS` |
| 2 | **prescribe** a medication | `PRESCRIPTION` |
| 3 | **calculate, recommend, or adjust a dose** | `DOSING` |
| 4 | tell anyone to **stop, start, replace, or change a medication** | `MEDICATION_CHANGE` |
| 5 | **select a treatment** | `TREATMENT_SELECTION` |
| 6 | **declare** a drug, phenotype, combination, or candidate **safe** | `SAFETY_ASSURANCE` |
| 7 | label a candidate **safer, preferred, suitable, or clinically equivalent** | `CANDIDATE_PREFERENCE` |
| 8 | treat **missing data or missing evidence as low or no risk** | `FALSE_REASSURANCE` |
| 9 | **process real VCF, EHR, genotype, diplotype, or laboratory data**, or infer a real patient's phenotype, in P0 | `REAL_PATIENT_DATA` |
| 10 | **replace or act as a clinical decision-maker** | `CLINICAL_DECISION_SUBSTITUTION` |
| 11 | present demo/development cases as **independent clinical validation, approval, or certification**; present rule-row counts as clinical evidence counts | `VALIDATION_OVERCLAIM` |

Each category carries a canonical `DOES NOT` sentence in both languages
(`prohibited_claim_statements()`), so that UI, API, and report text reuse one
wording instead of re-inventing it.

Two further prohibitions are architectural rather than textual, and are
carried by the safety contract rather than the scanner:

- an **LLM must not modify** a calculated finding, coverage status, evidence
  reference, or version identifier (`SAFETY-INV-002`);
- **development/curation cases and independent holdout cases must not be
  mixed** (`SAFETY-INV-009`).

## 8. Claim boundaries by phase

### 8.1 P0 - what may be claimed

**May be claimed:**

- the system deterministically reproduces the same structured assessment for
  the same input and the same release bundle;
- every calculated finding cites at least one traceable evidence reference;
- coverage is reported separately from attention, with explicit reason codes;
- exact phenotype matching is enforced; `RAPID` and `ULTRARAPID` are distinct;
- only `VALIDATED` rules from the active immutable ruleset execute;
- dataset, ruleset, and software versions are independently identified and
  rollback is demonstrable;
- results were produced on synthetic or protocol-defined cases;
- validation results are reported separately for development and holdout
  roles.

**May not be claimed in P0:**

- clinical accuracy, clinical utility, clinical safety, or patient benefit;
- diagnostic performance (sensitivity/specificity/PPV/NPV) for patient care;
- readiness for clinical use, regulatory approval, CE marking, or medical
  device status;
- coverage of any drug-gene axis that the ruleset coverage manifest does not
  declare;
- that the ruleset is complete, current, or exhaustive relative to CPIC,
  DPWG, ClinPGx, or any guideline body;
- that candidate drugs were compared for safety;
- any real-world genomic data handling capability.

### 8.2 P1 - conditional extensions

P1 features are optional and off by default. Enabling one does **not** widen
the intended purpose.

| P1 capability | Additional claim allowed | Still prohibited |
|---|---|---|
| Minimal knowledge graph (`P1-01`) | Structural context between drugs exists and is traversable | Any clinical equivalence claim |
| Candidate exploration (`P1-02`) | Candidates share a therapeutic context and their **coverage/attention data status** is displayed | Safer / preferred / suitable labelling; any 0-100 suitability score (removed under `LEGACY-BUG-009`) |
| Source conflict v1 (`P1-03`) | Conflicting sources are detected and surfaced | Silent resolution, or collapsing a conflict into a reassuring result |
| Phenoconversion (`P1-04`) | A documented phenoconversion rule was applied and is traceable | Clinical dosing implication |
| Multi-drug context (`P1-05`) | Multiple medications share a pharmacogenetic axis | A drug-drug interaction claim |
| Safe LLM explanation (`P1-06`) | The text is a rendering of the structured report | Any new fact, drug, dose, or safety statement; any alteration of a calculated fact |

### 8.3 P2 - out of scope, gated

`P2` capabilities are architecture placeholders and must not appear as
incidental additions (`architecture.md` section 19): pilot gateway,
operational clinical pilot, privacy/consent expansion, EHR/VCF/genotype
ingestion, and advanced knowledge graphs. Each requires its own gate, its own
expanded intended purpose, and an ADR.

## 9. No real patient data

P0 processes **only synthetic or validation-protocol data** and stores **no
direct patient identifiers** (`architecture.md` section 13).

- Every validation case must carry a synthetic/public status and an explicit
  prohibited-PII assertion (`architecture.md` section 12.2).
- The demonstration profiles in `clinpgx_mvp_seed/` are fabricated
  demonstration profiles, not de-identified patient records.
- If real patient data ever enters scope, it is a P2 change requiring an ADR,
  a privacy and consent model, and re-validation (`P2-03`, `P2-04`).

Any statement that the system "analysed a patient's genome" is false and is
flagged by the `REAL_PATIENT_DATA` category of the claim scanner.

## 10. Points requiring scientific and expert approval

The following are **open** and must not be described as settled. An
implementation agent may build the mechanism; only a named human may record
the approval.

| # | Item | Owning WP | Gate |
|---|---|---|---|
| SR-01 | Approval of this intended-purpose statement | WP-00 | Human + scientific advisor |
| SR-02 | Approval of the safety contract and invariant registry | WP-00 | Human + scientific advisor |
| SR-03 | Scientific source selection, roles, and licence permissions | WP-05 | Gate A |
| SR-04 | Curation protocol and evidence-strength criteria | WP-09 | Gate B |
| SR-05 | Rule approval governance and reviewer independence | WP-10 | Gate B |
| SR-06 | Content of the validated ruleset (every rule) | WP-11 | Gate B |
| SR-07 | Coverage manifest: which axes may be claimed as evaluable | WP-13 | Gate C |
| SR-08 | Validation case provenance and development/holdout separation | WP-18 | Gate D |
| SR-09 | Blind expert validation protocol and its results | WP-22 | Gate D |
| SR-10 | Whether any THS 6 claim is supported by its artifact | WP-25 | Gate F |

Legacy `MANUAL_EFFECT_HINTS` content is imported as **unapproved draft
curation proposals** and never auto-validated (`LEGACY-BUG-006`).

## 11. Approval record

This document is in **DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW**. The
status line at the top may be changed only when every row below is completed
by the named person themselves.

| Role | Name | Affiliation | Decision | Date | Signature / record reference |
|---|---|---|---|---|---|
| Product / technical owner | *(pending)* | | *(pending)* | | |
| Scientific advisor (pharmacogenetics / clinical pharmacology) | *(pending)* | | *(pending)* | | |
| Clinical reviewer (optional but recommended) | *(pending)* | | *(pending)* | | |
| Risk management owner | *(pending)* | | *(pending)* | | |

**Reviewer checklist** (each must be answered before signing):

- [ ] The intended-purpose statement in section 1 matches what the software
      actually does today, not what is planned.
- [ ] The target users in section 2 are correct and no patient-facing use is
      implied anywhere in the product.
- [ ] The permitted input list in section 3 is complete, and no real patient
      data path exists.
- [ ] `PILOT` is disabled in code and the gate conditions in section 4.1 are
      acceptable.
- [ ] The `DOES NOT` list in section 7 is complete for this product.
- [ ] The P0 claim boundary in section 8.1 contains no claim that current
      evidence cannot support.
- [ ] Section 10 lists every item that still requires scientific approval.
- [ ] The canonical warning text in section 6 is scientifically and
      linguistically acceptable in both languages.

## 12. Change control

Any change to the intended purpose, the prohibited-claim list, the operating
modes, the P0/P1/P2 boundary, or the use of real patient data requires an
Architecture Decision Record under `docs/architecture/decisions/` recording
context, decision, alternatives, consequences, safety impact, migration
impact, validation impact, approvers, and effective release
(`architecture.md` section 23). Changing `pgx/domain/claims.py` without the
corresponding ADR and an update to this document is a governance defect.
