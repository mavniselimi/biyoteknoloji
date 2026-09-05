# WP-11 legacy rule candidates

| Field | Value |
|---|---|
| Document ID | `DOC-MIG-005` |
| Work package | WP-11 — Computable Rule Specification and Validated Rule Registry |
| Artifact | `data/migration/wp11/legacy-rule-candidate-inventory.json` |
| Schema | `schemas/legacy-rule-candidate-inventory.schema.json` |
| Result | 1,559 candidates, **0 eligible**, **0 rules created** |

---

## 1. What this is

An inventory. It lists every legacy rule-like record the repository holds and
says what would have to be true before any of them could become a computable
rule. It creates no rule, grants no eligibility, and copies no legacy severity
or risk value into a rule outcome.

It is built from the WP-08 draft proposals and the WP-10 legacy work items,
both of which already carry source-file and row provenance. It does not read
`clinpgx_mvp_seed/` — the dependency-boundary test that forbids V2 modules
from reading the legacy seed still applies to `pgx/rules`.

## 2. The counts

| Count | Value |
|---|---|
| candidates | 1,559 |
| linked to an evidence record | 1,526 |
| unlinked | 33 |
| curation status `RAW` | 1,559 |
| eligible for rule creation | **0** |
| rules created | **0** |
| validated rules | **0** |
| frozen rulesets | **0** |

## 3. Why every one is ineligible

| Blocker | Candidates | Who can clear it |
|---|---|---|
| `PROTOCOL_NOT_APPROVED` | 1,559 | a named scientific expert |
| `DATASET_NOT_PUBLISHED` | 1,559 | the WP-07 publication process |
| `EVIDENCE_BUILD_QUARANTINED` | 1,559 | source-policy review, then a re-labelled build |
| `CURATION_NOT_CURATED` | 1,559 | scientific curators |
| `NO_APPROVED_REVISION` | 1,559 | a curator and an independent reviewer |
| `NO_APPROVAL_ENVELOPE` | 1,559 | a curator, a reviewer and an approver, acting separately |
| `LEGACY_SEVERITY_IS_NOT_AN_OUTCOME` | 1,512 | a curator deciding an attention level on the evidence |
| `NO_EVIDENCE_LINK` | 33 | curators selecting evidence during curation |

Not one of these is clearable by writing more code.

## 4. Legacy text stays legacy text

Every legacy clinical string is kept under a `raw_` prefix —
`raw_phenotype_text`, `raw_effect_text`, `raw_severity_text`,
`raw_significance_text` — and nothing reads them to decide anything. The
inventory schema has no field a legacy severity could be written into as an
outcome, and a candidate claiming eligibility while carrying blockers is
refused by the schema itself.

`raw_phenotype_text` values such as `other` and `unknown` are legacy
vocabulary. Nothing maps them onto `Phenotype`, because that mapping would be
a scientific judgement made by a string comparison.

## 5. If these counts ever change

They are asserted exactly in `tests/unit/rules/test_legacy_inventory.py`. A
change is either a real change to the data or a defect, and either way
somebody should look. The correct response to a failing count is never to
relax the assertion.
