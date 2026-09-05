# P0 API contract

The complete surface, generated shape by shape from
`apps/api/routes.py` and `apps/api/contracts/spec.py`. Those two modules
are the only definition; this document, the OpenAPI artifact and the
published JSON Schemas are all derived from them.

## Routes

| Method | Path | Operation | Success | Access |
| --- | --- | --- | --- | --- |
| `POST` | `/api/v1/assessments` | `createAssessment` | 201 | ADMIN, DEMO_USER, EXPERT_REVIEWER |
| `GET` | `/api/v1/assessments/{assessment_id}` | `getAssessment` | 200 | ADMIN, DEMO_USER, EXPERT_REVIEWER |
| `GET` | `/api/v1/drugs` | `listDrugs` | 200 | ADMIN, DEMO_USER, EXPERT_REVIEWER |
| `GET` | `/api/v1/genes` | `listGenes` | 200 | ADMIN, DEMO_USER, EXPERT_REVIEWER |
| `GET` | `/api/v1/evidence/{evidence_id}` | `getEvidenceRecord` | 200 | ADMIN, DEMO_USER, EXPERT_REVIEWER |
| `GET` | `/api/v1/system/version` | `getSystemVersion` | 200 | public |
| `GET` | `/api/v1/expert-reviews` | `listExpertReviewAssignments` | 200 | EXPERT_REVIEWER |
| `GET` | `/api/v1/expert-reviews/{case_id}` | `getExpertReviewState` | 200 | EXPERT_REVIEWER |
| `POST` | `/api/v1/expert-reviews/{case_id}/expected` | `submitExpertReviewExpected` | 201 | EXPERT_REVIEWER |
| `POST` | `/api/v1/expert-reviews/{case_id}/reveal` | `revealExpertReviewResult` | 200 | EXPERT_REVIEWER |
| `POST` | `/api/v1/expert-reviews/{case_id}/complete` | `completeExpertReview` | 201 | EXPERT_REVIEWER |
| `POST` | `/api/v1/expert-reviews/{case_id}/corrections` | `appendExpertReviewCorrection` | 201 | EXPERT_REVIEWER |
| `GET` | `/health/live` | `getLiveness` | 200 | public |
| `GET` | `/health/ready` | `getReadiness` | 200 | public |

The list is closed. `tests/unit/api/test_openapi.py` asserts it is exactly
these fourteen operations, that no path contains `/admin`, `/debug`,
`/internal`, `/metrics`, `/shell` or `/sql`, and that no route generates a
report.

### The six expert-review routes

Three of these were 501 stubs until WP-22 and are now service-backed. **No
route in this API answers 501 any more**, and `EXPERT_REVIEW_NOT_IMPLEMENTED`
has left the error catalogue: a code for "not implemented" is a slot a
future half-built route would occupy.

The properties the stubs were written to preserve are preserved by the real
implementation rather than by doing nothing:

- **Role first, store second.** `require_access` runs before any handler
  body, so a caller without the exact `EXPERT_REVIEWER` role never reaches a
  lookup and the refusal cannot differ in timing by whether a case exists.
  `ADMIN` does not satisfy the check.
- **One refusal for three conditions.** An unknown case, a case that is not
  expert-holdout, and a case assigned to somebody else all return **404
  `EXPERT_REVIEW_NOT_ASSIGNED`** with an empty details map. Three
  distinguishable codes would be an enumeration tool for the holdout set.
- **No result before a reveal.** `ExpertReviewStateResponse` has no result
  field — not optional, not nullable. A hidden value is still disclosure, so
  the pre-reveal shape has nowhere to put one, and the result is never
  fetched before `reveal` is called.
- **Identity comes from the principal.** Actor, role, timestamps, status and
  every hash come from the authenticated principal and the stored assignment.
  A body supplying one is **refused** with 422
  `EXPERT_REVIEW_FORGED_FIELD` rather than having it stripped: a caller who
  tried to set their own timestamp has told you something.
- **Fail closed.** With no review service configured — this repository's
  state — every route answers **503 `EXPERT_REVIEW_NOT_AVAILABLE`** having
  consulted nothing.

The ordering the protocol depends on is enforced with 409s:
`EXPERT_REVIEW_EXPECTATION_REQUIRED` before a reveal,
`EXPERT_REVIEW_REVEAL_REQUIRED` before a completion,
`EXPERT_REVIEW_EXPECTATION_ALREADY_LOCKED`,
`EXPERT_REVIEW_RESULT_ALREADY_REVEALED` and
`EXPERT_REVIEW_ALREADY_COMPLETED` against repeats.

## Role matrix

| Operation | DEMO_USER | EXPERT_REVIEWER | ADMIN | Anonymous |
| --- | :-: | :-: | :-: | :-: |
| `createAssessment` | yes | yes | yes | — |
| `getAssessment` | yes | yes | yes | — |
| `listDrugs` | yes | yes | yes | — |
| `listGenes` | yes | yes | yes | — |
| `getEvidenceRecord` | yes | yes | yes | — |
| `getSystemVersion` | yes | yes | yes | yes |
| `submitExpertReviewExpected` | — | yes | — | — |
| `revealExpertReviewResult` | — | yes | — | — |
| `completeExpertReview` | — | yes | — | — |
| `getLiveness` | yes | yes | yes | yes |
| `getReadiness` | yes | yes | yes | yes |

There is **no role hierarchy**. `ADMIN` does not implicitly satisfy an
`EXPERT_REVIEWER` check: every route names the exact set it permits, so
adding a role later cannot silently widen a gate that was written to mean
"only a reviewer".

## Request contract

`POST /api/v1/assessments` accepts exactly these fields, and refuses any
other by name:

- **`mode`** (enum, required) — Operation mode. Checked against the claim boundary before anything is read.
- **`input_kind`** (enum, required) — What kind of input this is. Checked against the claim boundary.
- **`case_id`** (string, optional) — Optional label for the run. Deliberately outside the semantic input hash.
- **`requested_release_public_id`** (string, optional) — Optional release to pin. It must be the active one; naming a different release is refused rather than honoured.
- **`profile`** (object, required) — The supplied phenotype profile.
- **`medications`** (array, required) — Canonical drug keys. Free text is not resolved here: turning a brand name into a canonical drug is WP-07's work, and a medication the pinned dataset does not contain is reported as unsupported rather than dropped.

The phenotype profile carries `input_contract_version`, an optional
`profile_id` and one to 64 observations, each a canonical gene key and a
phenotype token. A token this contract version does not recognise becomes
an observation recorded as uninterpretable — never a guess, never the
nearest match, never a lookup in an ungoverned synonym table.

Two observations naming the same gene are **refused**, not collapsed. A
client sending `POOR` and `NORMAL` for one gene would otherwise receive a
confident assessment of whichever happened to be last.

## Refused input

These 50 field names refuse the whole request, at any depth, and the
rejected value is never echoed in the error:

**Raw genetic data this system does not interpret**

`activity_score`, `allele`, `alleles`, `diplotype`, `genotype`, `star_allele`, `star_alleles`, `vcf`, `vcf_path`, `vcf_url`

**Identifiable or clinical text it has no reason to hold**

`clinical_notes`, `date_of_birth`, `diagnosis`, `dob`, `dosage`, `dose`, `ehr`, `ehr_id`, `indication`, `mrn`, `narrative`, `notes`, `patient_id`, `patient_name`, `patient_narrative`

**Answers only the server may determine**

`active_pointer_generation`, `actor`, `attention`, `attention_level`, `content_hash`, `coverage`, `coverage_reason_codes`, `coverage_result_hash`, `coverage_status`, `dataset_public_id`, `evidence_references`, `findings`, `input_hash`, `output_hash`, `overall_attention`, `overall_coverage`, `principal`, `release_manifest_hash`, `release_provenance`, `report_hash`, `role`, `rule_id`, `rule_version`, `ruleset_content_hash`, `software_version`

The third group is why a client cannot forge an actor, a role, an attention
level, a coverage status, a finding, a hash or a release provenance: those
are outputs, and a request that supplied one would be dictating an answer.
The full list with a reason for each is published in
`schemas/wp16/prohibited-request-fields.schema.json`.

## Limits

| Bound | Value |
| --- | --- |
| `default_page_size` | 25 |
| `max_body_bytes` | 65536 |
| `max_collection_items` | 200 |
| `max_cursor_length` | 512 |
| `max_detail_entries` | 20 |
| `max_identifier_length` | 64 |
| `max_medications` | 32 |
| `max_message_length` | 512 |
| `max_observations` | 64 |
| `max_page_size` | 100 |
| `max_reference_length` | 128 |
| `max_string_length` | 256 |

Every string is bounded, every collection is bounded, and control
characters (C0, C1 and the line/paragraph separators) are **rejected rather
than stripped**: stripping makes two different values equal, and a value
carrying an escape sequence was constructed on purpose.

An oversized page is refused rather than silently reduced — a client that
asked for 5000 and received 100 without being told has no way to know its
list is incomplete.

## Pagination

Catalogue cursors are opaque tokens carrying the release, dataset and
coverage-manifest identity they were produced against, plus the key they
stopped at. A cursor is **refused against any other release** with 409
`CURSOR_RELEASE_MISMATCH`.

Without that, a client could fetch page one against release A, have a
release activated underneath them, and receive page two from release B —
one list assembled from two coverage manifests with nothing marking the
seam. Ordering is by canonical key and resumes strictly after the last key
returned, so no item is skipped or repeated.

## Ordering is never a ranking

Catalogues are ordered by canonical key and the only thing that order means
is alphabetical. There is no score, no ranking, no suitability verdict and
no ordering by attention anywhere in this API (SAFETY-INV-005). A drug's
coverage is reported as counts and identities read from the governed
manifest — `supported_axis_count`, `verified_axis_count`, the declaration
id — never as a judgement.

## Response guarantee

`POST /api/v1/assessments` returns **201** with a `Location` header and the
complete assessment. A subsequent `GET` of that assessment returns
semantically identical governed facts: both are built by the same
serialiser, one from the executed result and one from the stored rows.

Attention and coverage travel together as one `status` object at every
level — overall and per medication — so no serialisation of this contract
can carry one without the other (SAFETY-INV-001). `NOT_ASSESSED`,
`SOURCE_CONFLICT` and `UNSUPPORTED_DRUG` survive verbatim; a medication the
pinned dataset does not contain is reported with a governed reason code
rather than dropped.

Every response carries the canonical clinical warning from
`pgx/domain/claims.py`. It is not duplicated in any API module: a second
copy would be a second thing to update, and the stale copy would be the one
users read.

