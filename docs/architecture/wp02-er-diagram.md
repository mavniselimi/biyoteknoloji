# WP-02 - Foundation Entity-Relationship Diagram

| Field | Value |
|---|---|
| Document ID | `DOC-ARCH-003` |
| Migration revision | `0001_wp02_foundation` |
| Tables created | 11 |
| Companion document | `docs/architecture/wp02-domain-and-db.md` |

The diagram shows only what `0001_wp02_foundation` creates. Tables belonging to
WP-03 and later are listed in section 3 and are deliberately absent from the
schema.

---

## 1. Created by WP-02

```mermaid
erDiagram
    SOURCE_REGISTRY ||--o{ EVIDENCE_RECORDS : "supplies"
    DATASET_VERSIONS ||--o{ EVIDENCE_RECORDS : "contains"
    GENES ||--o{ GENE_ALIASES : "has"
    GENES ||--o{ EVIDENCE_RECORDS : "referenced by"
    DRUGS ||--o{ DRUG_ALIASES : "has"
    DRUGS ||--o{ EVIDENCE_RECORDS : "referenced by"
    EVIDENCE_RECORDS ||--o{ INTERPRETATION_EVIDENCE : "cited by"
    CURATED_INTERPRETATIONS ||--o{ INTERPRETATION_EVIDENCE : "cites"
    CURATED_INTERPRETATIONS ||--o{ COMPUTABLE_RULES : "backs"
    COMPUTABLE_RULES ||--o{ RULE_EVIDENCE : "cites"
    EVIDENCE_RECORDS ||--o{ RULE_EVIDENCE : "cited by"

    SOURCE_REGISTRY {
        uuid id PK
        varchar source_key UK "unique"
        varchar display_name
        varchar role "PRIMARY_GUIDELINE|SUPPORTING_ANNOTATION|REFERENCE_ONLY|INTERNAL_SYSTEM"
        varchar version_policy
        varchar license_policy
        varchar citation_policy
        boolean release_eligible "false when role=INTERNAL_SYSTEM"
        boolean active
        timestamptz created_at
        varchar legacy_id "nullable"
    }

    DATASET_VERSIONS {
        uuid id PK
        varchar public_id UK "PGX-DATA-YYYYMMDD-NNN"
        varchar status "BUILDING|QUALITY_CHECKED|PUBLISHED|RETIRED"
        varchar manifest_hash "sha256:<64 hex>"
        varchar dq_report_path "nullable"
        timestamptz created_at
        varchar approved_by "required when PUBLISHED"
        timestamptz approved_at "required when PUBLISHED"
        varchar legacy_id "nullable"
    }

    GENES {
        uuid id PK
        varchar normalized_symbol UK "upper(trim())"
        varchar preferred_name
        jsonb external_ids
        timestamptz created_at
        varchar legacy_id "nullable"
    }

    GENE_ALIASES {
        uuid gene_id PK_FK
        varchar normalized_alias PK "unique within a gene only"
        varchar display_alias
    }

    DRUGS {
        uuid id PK
        varchar normalized_name UK "lower(trim())"
        varchar preferred_name
        jsonb external_ids
        timestamptz created_at
        varchar legacy_id "nullable"
    }

    DRUG_ALIASES {
        uuid drug_id PK_FK
        varchar normalized_alias PK "unique within a drug only"
        varchar display_alias
    }

    EVIDENCE_RECORDS {
        uuid id PK
        uuid source_registry_id FK
        uuid dataset_version_id FK
        varchar source_record_id
        varchar source_record_version
        uuid gene_id FK "nullable"
        uuid drug_id FK "nullable"
        varchar raw_hash "sha256:<64 hex>"
        text source_text "nullable"
        jsonb evidence_metadata
        jsonb publication_metadata
        timestamptz created_at
        varchar legacy_id "nullable"
    }

    CURATED_INTERPRETATIONS {
        uuid id PK
        varchar status "RAW|UNDER_REVIEW|CURATED|REJECTED"
        varchar normalized_phenotype "nullable; RAPID and ULTRARAPID are distinct"
        varchar normalized_effect
        varchar significance
        text rationale "required when CURATED"
        varchar created_by
        varchar reviewed_by "required when CURATED"
        timestamptz created_at
        timestamptz reviewed_at "required when CURATED"
        varchar legacy_id "nullable"
    }

    INTERPRETATION_EVIDENCE {
        uuid interpretation_id PK_FK
        uuid evidence_record_id PK_FK
    }

    COMPUTABLE_RULES {
        uuid id PK
        uuid interpretation_id FK "NOT NULL"
        jsonb condition_json "declarative data, never code"
        varchar attention_level "NOT_ASSESSED|NO_ACTIVE_ATTENTION|LOW|MEDIUM|HIGH"
        varchar status "DRAFT|CURATED|VALIDATED|DEPRECATED"
        integer rule_version ">= 1"
        varchar created_by
        varchar approved_by "required when VALIDATED"
        timestamptz created_at
        timestamptz approved_at "required when VALIDATED"
        varchar legacy_id "nullable"
    }

    RULE_EVIDENCE {
        uuid rule_id PK_FK
        uuid evidence_record_id PK_FK
    }
```

## 2. Cardinality and delete behaviour

| Relationship | Cardinality | On delete | Why |
|---|---|---|---|
| `source_registry` → `evidence_records` | 1 : 0..N | `RESTRICT` | A source with evidence cannot vanish |
| `dataset_versions` → `evidence_records` | 1 : 0..N | `RESTRICT` | A dataset build is immutable once it has content |
| `genes` → `gene_aliases` | 1 : 0..N | `CASCADE` | An alias has no life without its gene |
| `drugs` → `drug_aliases` | 1 : 0..N | `CASCADE` | Same |
| `genes`/`drugs` → `evidence_records` | 1 : 0..N (nullable) | `RESTRICT` | Evidence may be gene- or drug-agnostic, but a referenced entity is protected |
| `curated_interpretations` ↔ `evidence_records` | M : N via `interpretation_evidence` | `CASCADE` from interpretation, `RESTRICT` from evidence | Dropping an interpretation drops its links; evidence stays protected |
| `curated_interpretations` → `computable_rules` | 1 : 0..N | `RESTRICT` | A rule's basis cannot be deleted underneath it |
| `computable_rules` ↔ `evidence_records` | M : N via `rule_evidence` | `CASCADE` from rule, `RESTRICT` from evidence | `SAFETY-INV-006` |

Both link tables use a composite primary key, which makes a duplicate
association impossible and an orphan row unreachable.

**Alias ambiguity is intentional.** `gene_aliases` and `drug_aliases` are unique
only *within* one entity. The same alias may point at two genes; that is real
ambiguity, and it is preserved for a WP-07 resolution queue rather than being
collapsed to whichever row was inserted first.

## 3. Deliberately absent — later work packages

```mermaid
erDiagram
    RELEASE_BUNDLES ||--o{ ASSESSMENTS : "WP-03 / WP-14"
    RULESET_VERSIONS ||--o{ RULESET_MEMBERSHIP : "WP-03 / WP-11"
    ASSESSMENTS ||--o{ ASSESSMENT_FINDINGS : "WP-14"

    RELEASE_BUNDLES {
        uuid id PK "NOT CREATED IN WP-02"
        varchar public_id "PGX-REL-YYYYMMDD-NNN"
        uuid dataset_version_id FK
        uuid ruleset_version_id FK
        varchar software_version
        varchar status
    }
    RULESET_VERSIONS {
        uuid id PK "NOT CREATED IN WP-02"
        varchar public_id "PGX-RULESET-YYYYMMDD-NNN"
        varchar status
    }
    RULESET_MEMBERSHIP {
        uuid ruleset_version_id PK_FK "NOT CREATED IN WP-02"
        uuid rule_id PK_FK
    }
    ASSESSMENTS {
        uuid id PK "NOT CREATED IN WP-02"
        uuid release_bundle_id FK "mandatory - SAFETY-INV-007"
        varchar input_hash
        varchar output_hash
    }
    ASSESSMENT_FINDINGS {
        uuid assessment_id PK_FK "NOT CREATED IN WP-02"
        uuid rule_id FK
    }
```

| Table | Introduced by |
|---|---|
| `software_versions`, `ruleset_versions`, `ruleset_membership`, `release_bundles`, `active_release` | WP-03 |
| `ingestion_runs`, `raw_artifacts` | WP-04, WP-06 |
| `assessments`, `assessment_findings` | WP-14 |
| `validation_cases`, `expert_reviews` | WP-18, WP-22 |
| `users`, `sessions`, `audit_events` | WP-23 |

An assessment table cannot precede a release identity: persisting an assessment
without one would violate `SAFETY-INV-007`, so WP-02 creates neither.
