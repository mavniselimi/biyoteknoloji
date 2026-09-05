# Scientific source strategy

| Field | Value |
|---|---|
| Document ID | `DOC-SCI-001` |
| Work package | WP-05 - Scientific Source Strategy, Provenance and Licensing Policy |
| Companion documents | `provenance-policy.md`, `licensing-and-reuse-matrix.md`, `source-conflict-policy.md`, `source-review-checklist.md` |
| Machine-readable form | `config/scientific-sources.json` (schema: `schemas/scientific-source-registry.schema.json`) |
| Status | **Candidate registry. No source is approved.** |

> **Nothing in this document approves anything.** Every source listed here is
> `PENDING_REVIEW`. No official terms document has been retrieved, no licence
> identifier has been recorded, and no named human has reviewed any source. The
> project therefore publishes nothing, and that is the correct state rather
> than an unfinished one.
>
> WP-00 approval remains **BLOCKED**; WP-01's Git checkpoint remains
> **BLOCKED**; the WP-02 and WP-03 toolchain blockers are unchanged; the WP-03
> review findings are open in `docs/handoffs/wp03-open-items.md`. WP-05
> resolves none of them.

---

## 1. The question this work package answers

*May we use this source, for what, and who says so?*

The legacy CSVs answer none of that. `drug_gene_guidelines.csv` has a `source`
column holding the strings `CPIC`, `DPWG`, `RNPGx`, `AHA`, `AusNZ` and `CPNDS`,
and a `source_container` column holding provider-internal paths. Those are
labels. They record where a row was copied from; they record nothing about
whether copying it was permitted, how the source must be cited, which version
of the source it came from, or what kind of claim it is fit to support.

WP-05 does not add scientific meaning to those labels. It adds the governance
that has to sit around them before any of them may back published output.

## 2. Five things this project keeps apart

Collapsing these five into one field called "license" is how a project ends up
believing it has permission it never obtained. Each has its own home in
`config/scientific-sources.json`.

| # | Concept | Where it lives | Who authors it |
|---|---|---|---|
| 1 | What the source published | `evidence[]` - URL, retrieval instant, content hash, short factual summary | The source |
| 2 | The source's licensing or terms statements | The artefact at that URL. **Not copied into this repository.** | The source |
| 3 | This project's interpretation of those statements | `interpretation` - attributed, dated, explicitly not legal advice | A named person here |
| 4 | This project's approval decision | `review` - decision, reviewer name and role, instant, cited evidence, restrictions, expiry | A named human reviewer |
| 5 | The claim categories the source may support | `permitted_claim_categories` - empty unless approved | Decided at review |

A public webpage, an open API and a downloadable file prove that a thing is
*reachable*. They prove nothing about whether acquiring, storing, transforming
or redistributing it is permitted, and this project does not treat reachability
as permission.

## 3. Source roles

The role a source plays is separate from whether it is approved. Roles come
from the WP-02 domain vocabulary (`SourceRole`) and are unchanged here.

| Role | Meaning | Registered examples (all `PENDING_REVIEW`) |
|---|---|---|
| `PRIMARY_GUIDELINE` | Publishes prescribing guidance or regulator-approved labelling | `cpic.database`, `cpic.api`, `cpic.publications`, `dpwg.knmp`, `rnpgx.publications`, `cpnds.publications`, `aha.publications`, `ausnz.publications`, `druglabel.*` |
| `SUPPORTING_ANNOTATION` | Curated annotation supporting, but not itself constituting, guidance | `clinpgx.api`, `clinpgx.website` |
| `REFERENCE_ONLY` | Bibliographic reference; carries no interpretation | `pubmed.literature` |
| `INTERNAL_SYSTEM` | Technical bookkeeping produced by this project | `internal.legacy_mvp_seed`, `internal.legacy_probe_outputs`, `internal.manual_normalization` |

`INTERNAL_SYSTEM` can never be release-eligible and can never carry a
scientific claim category. That rule is enforced three times: in the WP-02
domain model, in the WP-05 policy record, and by a check constraint in
migration `0003`.

## 4. Why a provider is registered more than once

`cpic.database`, `cpic.api` and `cpic.publications` are three entries, not one.
So are `clinpgx.api` and `clinpgx.website`. A consortium is not a source: its
database, its programmatic interface and its journal articles can each carry
different conditions, and a publisher's reuse terms are not the consortium's.
Registering "CPIC" once would force a single answer onto three different
questions.

Drug labels are registered per jurisdiction for the same reason and one more: a
label statement is authoritative only where its regulator has authority. A US
FDA statement is not a Turkish one. `druglabel.titck` exists because this
project is being built in Türkiye and the difference must not be glossed over.

## 5. Acquisition is a separate question from use

`AcquisitionMode` records how records may be obtained, independently of what
may be done with them. A source may permit reuse of data a human downloaded by
hand while prohibiting the automated crawl that would have produced the same
bytes.

| Mode | Meaning |
|---|---|
| `NOT_DETERMINED` | No decision. The default. Blocks automated acquisition. |
| `MANUAL_DOWNLOAD` | A human downloads a published file and records where it came from. |
| `OFFICIAL_API` | An interface the source publishes and documents for programmatic use. |
| `LICENSED_BULK_EXPORT` | A bulk export obtained under a specific written licence. |
| `PUBLICATION_TRANSCRIPTION` | Facts transcribed by a human from a publication, cited by DOI or PMID. |
| `INTERNAL_DERIVATION` | Produced by this project from its own records. |

There is deliberately no scraping mode. Scraping is not an acquisition
mechanism this project offers, whatever a source's terms might permit.

## 6. What is blocked, and why

Every entry in the registry carries `blocking_reasons`. Today they are the same
five for every external source:

1. No official terms, licence or use-conditions document has been retrieved.
2. No project interpretation of this source's terms has been written.
3. No named human reviewer has made a decision.
4. Every reuse dimension is `UNKNOWN`.
5. No acquisition mode has been decided.

For `clinpgx.api` and `clinpgx.website` there is a sixth fact on file: a single
retrieval attempt was made and refused at the network layer
(`URLError <urlopen error Tunnel connection failed: 403 Forbidden>`). That is
recorded as a `BLOCKED` evidence reference with the reason attached. **A failed
retrieval is an outstanding obligation, never an approval**, and the record is
shaped so it cannot be read as one: a `BLOCKED` reference is not official
evidence, and the source still reports `MISSING_OFFICIAL_EVIDENCE`.

## 7. What WP-05 does not do

- It does not interpret pharmacogenomic guidance, or rank the scientific
  quality of two sources.
- It does not resolve disagreements between sources. See
  `source-conflict-policy.md`.
- It makes no legal conclusions. A project interpretation is recorded as an
  interpretation, by name.
- It contacts nobody. No email is sent to a source owner, and no terms page is
  fetched by any tool in this repository.
- It does not acquire data. WP-04 built the ClinPGx adapter and made no live
  call; that adapter stays unused until a source is approved.
- It does not build or publish a dataset. WP-06 owns snapshots and dataset
  builds.

## 8. How this is enforced in code

| Rule | Enforced by |
|---|---|
| A configuration file cannot approve a source | `SourcePolicyRecord.__post_init__` raises without an approving `ReviewRecord`; `ck_source_policies_approving_needs_review` in migration `0003` |
| An approving review must cite evidence | `ReviewRecord.__post_init__`; `ck_source_policy_reviews_approval_needs_evidence` |
| An unapproved source names no claim categories | `SourcePolicyRecord.__post_init__`; `ck_source_policies_categories_need_approval` |
| An unanswered reuse question blocks | `ReuseMatrix` materialises every dimension as `UNKNOWN`; `PolicyIssueCode.REUSE_PERMISSION_UNKNOWN` |
| An unregistered source has no permissions | `SourcePolicyRegistry.require`, `UnknownSourceError`, `PolicyIssueCode.SOURCE_UNREGISTERED` |
| `release_eligible` alone cannot publish | `ReleaseService._check_source_policy`, compatibility codes `EVIDENCE_SOURCE_POLICY_*` |
| A policy file that will not load blocks | `CompatibilityCode.SOURCE_POLICY_UNAVAILABLE` |
| A review decision cannot be edited afterwards | `trg_source_policy_reviews_append_only` |

## 9. Operating the registry

```
pgx-source-policy validate                 # every finding, exit 1 while any blocks
pgx-source-policy show cpic.database        # one source and what is outstanding
pgx-source-policy review-checklist          # the steps a human works through
pgx-source-policy evaluate-publication --dataset D --source cpic.database
pgx-source-policy inventory-legacy --check  # are the generated artefacts current
```

There is no `approve` subcommand, and there is no flag that sets a status. That
absence is the contract, and a test asserts it.
