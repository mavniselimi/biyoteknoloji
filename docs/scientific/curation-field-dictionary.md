# Curation field dictionary (WP-09)

| Field | Value |
|---|---|
| Document ID | `DOC-SCI-010` |
| Dictionary version | `pgx-curation-field-dictionary/1` |
| Status | **`DRAFT_AWAITING_EXPERT_REVIEW`** |
| Machine-readable form | [`config/curation/field-dictionary-v1.json`](../../config/curation/field-dictionary-v1.json) |
| Schema | [`schemas/curation-field-dictionary.schema.json`](../../schemas/curation-field-dictionary.schema.json) |

Every field a curation record carries, with **who owns it**, **what its absence
means**, and **what it may never be read as**.

The last two matter most.

**Null is not a value.** A missing origin source and an origin of "none" are
different facts. A dictionary that could not say which is which would let a
later stage read absence as a finding — which is the shape of
`SAFETY-INV-001`'s failure mode. Every entry states what null means.

**Prohibited interpretations are written down.** A field is misused most often
by being read as something adjacent: a source's significance flag read as the
curator's conclusion, an insufficiency read as a low risk, an eligibility flag
read as an approval. Naming the misuse is the only way a reviewer can check for
it, so a field defining none is refused at construction.

## Ownership

| Owner | Meaning | Count |
|---|---|---:|
| `SOURCE` | Copied unchanged from the evidence record. This project asserts nothing by carrying it. | 2 |
| `CURATOR` | A named human's judgement, argued in the rationale. | 16 |
| `SYSTEM` | Derived by tooling. Never a scientific claim. | 6 |

No field is owned by both `SOURCE` and `CURATOR` — a test enforces it, because
a shared field is exactly where a source's word would become this project's
claim without anyone deciding to.

---

### `record_id`

| | |
|---|---|
| Owner | **SYSTEM** |
| Type | `string` |
| Required | yes |
| Null means | Never null. A record without an identifier cannot be cited. |
| Validation | Non-empty; unique within a protocol version. |
| Provenance | Assigned by the tooling, not by a curator. |
| Human judgement | not required |
| May enter a rule | no |

**Must not be read as:**

- Not a scientific identifier and not stable across protocol versions.

### `protocol_version`

| | |
|---|---|
| Owner | **SYSTEM** |
| Type | `string` |
| Required | yes |
| Null means | Never null. A conclusion with no protocol version cannot be read under the rules it was made under. |
| Validation | Must match a published protocol version. |
| Provenance | Copied from the protocol document in force at authoring time. |
| Human judgement | not required |
| May enter a rule | yes |

**Must not be read as:**

- Not a data version and not a source version.

### `question`

| | |
|---|---|
| Owner | **CURATOR** |
| Type | `object` |
| Required | yes |
| Null means | Never null. A conclusion with no question answers nothing. |
| Validation | Gene and drug canonical keys, effect dimension, question text; phenotype scope and population optional. |
| Provenance | Gene and drug keys must exist in the canonical build. |
| Human judgement | required |
| May enter a rule | yes |

**Must not be read as:**

- Not a gene/drug pair key: a pair-level conclusion must not be applied to every annotation sharing that pair.

### `question.phenotype_scope`

| | |
|---|---|
| Owner | **CURATOR** |
| Type | `array<Phenotype>` |
| Required | no |
| Allowed values | `POOR`, `INTERMEDIATE`, `NORMAL`, `RAPID`, `ULTRARAPID`, `INDETERMINATE` |
| Null means | Empty means the conclusion is not scoped to a phenotype - not that it applies to every phenotype. |
| Validation | Exact Phenotype members; no aliases; RAPID and ULTRARAPID are distinct members and must both be listed to cover both. |
| Provenance | Normalization must be explained in the rationale. |
| Human judgement | required |
| May enter a rule | yes |

**Must not be read as:**

- An empty scope is not a wildcard.
- RAPID must never be read as covering ULTRARAPID (SAFETY-INV-004).

### `status`

| | |
|---|---|
| Owner | **CURATOR** |
| Type | `InterpretationStatus` |
| Required | yes |
| Allowed values | `DRAFT`, `UNDER_REVIEW`, `CURATED`, `REJECTED` |
| Null means | Never null. Defaults to DRAFT, which means nobody has reviewed it. |
| Validation | CURATED additionally requires rationale and a distinct named reviewer. |
| Provenance | Each transition records who made it and when. |
| Human judgement | required |
| May enter a rule | no |

**Must not be read as:**

- DRAFT is not a rejection.
- The persisted CurationStatus spells DRAFT as RAW; they are the same state under two names, not two states.

### `conclusion_state`

| | |
|---|---|
| Owner | **CURATOR** |
| Type | `ConclusionState` |
| Required | yes |
| Allowed values | `SUPPORTED`, `CONFLICTING`, `INSUFFICIENT`, `NOT_INTERPRETABLE`, `OUT_OF_SCOPE`, `NOT_APPLICABLE` |
| Null means | Never null. Absence of a conclusion is expressed as INSUFFICIENT, with a statement of what is missing. |
| Validation | INSUFFICIENT requires an insufficiency statement; CONFLICTING requires a recorded conflict. |
| Provenance | Must follow from the cited evidence via the rationale. |
| Human judgement | required |
| May enter a rule | yes |

**Must not be read as:**

- Not ordered: INSUFFICIENT is not a weak SUPPORTED.
- INSUFFICIENT is never low risk, no risk, no effect, safe, normal or negative evidence (SAFETY-INV-001).
- CONFLICTING does not mean the disagreement was resolved.

### `conclusion_text`

| | |
|---|---|
| Owner | **CURATOR** |
| Type | `string` |
| Required | yes |
| Null means | Never null. A state with no sentence cannot be reviewed. |
| Validation | Substantive text; screened for reassuring language when the state is INSUFFICIENT or CONFLICTING. |
| Provenance | Written by the named author. |
| Human judgement | required |
| May enter a rule | no |

**Must not be read as:**

- Not patient-facing text.
- Not a recommendation, and not advice.

### `applicability`

| | |
|---|---|
| Owner | **CURATOR** |
| Type | `Applicability` |
| Required | yes |
| Allowed values | `APPLICABLE`, `PARTIALLY_APPLICABLE`, `NOT_APPLICABLE`, `UNCLEAR` |
| Null means | Never null. UNCLEAR is the honest answer when the population is not established; it is not a null. |
| Validation | One controlled member. |
| Provenance | The population statement in the rationale must support it. |
| Human judgement | required |
| May enter a rule | yes |

**Must not be read as:**

- APPLICABLE does not mean applicable to every population - it means applicable to the one stated.

### `effect_dimension`

| | |
|---|---|
| Owner | **CURATOR** |
| Type | `EffectDimension` |
| Required | yes |
| Allowed values | `EXPOSURE`, `CLEARANCE`, `ACTIVATION`, `RESPONSE_ASSOCIATION`, `ADVERSE_EVENT_ASSOCIATION`, `FUNCTIONAL_ACTIVITY`, `OTHER`, `INSUFFICIENT_TO_CLASSIFY` |
| Null means | Never null. INSUFFICIENT_TO_CLASSIFY is the answer when the dimension is not established. |
| Validation | One controlled member. |
| Provenance | Normalization from the source's wording must be explained. |
| Human judgement | required |
| May enter a rule | yes |

**Must not be read as:**

- Not a treatment instruction.
- Not a direction of risk: ACTIVATION says what changed, not whether that is good or bad for a patient.

### `evidence`

| | |
|---|---|
| Owner | **CURATOR** |
| Type | `array<EvidenceSelection>` |
| Required | yes |
| Null means | Never empty. A conclusion with no evidence is untraceable. |
| Validation | At least one included record; no repeats; each with a written rationale. |
| Provenance | Every UUID must exist in the sealed evidence build. |
| Human judgement | required |
| May enter a rule | yes |

**Must not be read as:**

- Not a bibliography: each entry states a relationship to this conclusion.

### `evidence[].relationship`

| | |
|---|---|
| Owner | **CURATOR** |
| Type | `EvidenceRelationship` |
| Required | yes |
| Allowed values | `SUPPORTS`, `CONTRADICTS`, `CONTEXT_ONLY`, `EXCLUDED` |
| Null means | Never null. |
| Validation | EXCLUDED requires an exclusion_reason; every other value forbids one. |
| Provenance | The relationship is the curator's assessment, not the source's. |
| Human judgement | required |
| May enter a rule | yes |

**Must not be read as:**

- CONTRADICTS is not a reason to delete the record.
- CONTEXT_ONLY does not mean irrelevant.

### `evidence[].exclusion_reason`

| | |
|---|---|
| Owner | **CURATOR** |
| Type | `ExclusionReason` |
| Required | no |
| Allowed values | `WRONG_ENTITY`, `WRONG_PHENOTYPE_SCOPE`, `WRONG_POPULATION`, `DUPLICATE_SOURCE_RECORD`, `SUPERSEDED_SOURCE_VERSION`, `INSUFFICIENT_DETAIL`, `OUT_OF_SCOPE`, `UNRESOLVED_PROVENANCE`, `OTHER_WITH_RATIONALE` |
| Null means | Null means the record was not excluded. It never means excluded for an unstated reason. |
| Validation | Required exactly when relationship is EXCLUDED. |
| Provenance | Accompanied by written rationale in the same entry. |
| Human judgement | required |
| May enter a rule | no |

**Must not be read as:**

- Not a category that may be applied automatically: contradictory, older, other-organisation and unknown-version evidence must never be excluded by rule.

### `evidence[].trace_verified`

| | |
|---|---|
| Owner | **SYSTEM** |
| Type | `boolean` |
| Required | no |
| Null means | Null means the trace was not checked, which is different from a check that failed. Neither may be reported as verified. |
| Validation | Set only by a verification run against the sealed build. |
| Provenance | Derived from pgx-evidence verify. |
| Human judgement | not required |
| May enter a rule | yes |

**Must not be read as:**

- Null is not False and False is not 'probably fine'.

### `evidence[].source_version_status`

| | |
|---|---|
| Owner | **SOURCE** |
| Type | `string` |
| Required | yes |
| Null means | Never null. UNKNOWN_LEGACY records that a version existed and was lost; SOURCE_UNVERSIONED records that the source has none. |
| Validation | Copied verbatim from the evidence record. |
| Provenance | Comes from the evidence build, never from the curator. |
| Human judgement | not required |
| May enter a rule | yes |

**Must not be read as:**

- UNKNOWN_LEGACY must not be hidden behind a confidence label.
- An unknown version is not an old version.

### `source_reported`

| | |
|---|---|
| Owner | **SOURCE** |
| Type | `array<SourceReportedValues>` |
| Required | no |
| Null means | Empty means no source-reported value was recorded for comparison. It does not mean the source reported nothing. |
| Validation | Copied unchanged from the evidence record's own payload. |
| Provenance | Each entry names the evidence record it came from. |
| Human judgement | not required |
| May enter a rule | no |

**Must not be read as:**

- significance=yes is not ConclusionState.SUPPORTED.
- A ClinPGx score is not confidence, importance, strength or risk, and must not be mapped to any of them.
- polarity is not a direction of patient risk.

### `conflict`

| | |
|---|---|
| Owner | **CURATOR** |
| Type | `ConflictAnalysis` |
| Required | yes |
| Null means | Never null. NONE_IDENTIFIED means nobody found a conflict, not that none exists. |
| Validation | Any state other than NONE_IDENTIFIED requires at least two evidence records, a disputed field, materiality and analysis. |
| Provenance | Every conflicting record stays cited. |
| Human judgement | required |
| May enter a rule | yes |

**Must not be read as:**

- NONE_IDENTIFIED is not a finding of agreement.
- There is no precedence field, and adding one would be a change to this project's scientific position.

### `conflict.material`

| | |
|---|---|
| Owner | **CURATOR** |
| Type | `boolean` |
| Required | no |
| Null means | Null is refused on a recorded conflict: undetermined materiality is expressed as UNRESOLVED with material=False and an explanation. |
| Validation | Required whenever state is not NONE_IDENTIFIED. |
| Provenance | Judged by a named curator. |
| Human judgement | required |
| May enter a rule | yes |

**Must not be read as:**

- Immaterial does not mean absent.
- Materiality is not severity.

### `insufficiency`

| | |
|---|---|
| Owner | **CURATOR** |
| Type | `InsufficiencyStatement` |
| Required | no |
| Null means | Null means the conclusion is not INSUFFICIENT. It never means sufficiency was established. |
| Validation | Required exactly when conclusion_state is INSUFFICIENT; screened for reassuring language. |
| Provenance | Must list the evidence actually reviewed. |
| Human judgement | required |
| May enter a rule | no |

**Must not be read as:**

- Not a low-risk finding.
- Not a negative result: nothing was ruled out.

### `rationale`

| | |
|---|---|
| Owner | **CURATOR** |
| Type | `Rationale` |
| Required | no |
| Null means | Null means the conclusion has not been argued, so it cannot be CURATED. |
| Validation | Eleven named parts, each substantive; placeholder and circular text refused. |
| Provenance | Names the author, and the reviewer once reviewed. |
| Human judgement | required |
| May enter a rule | no |

**Must not be read as:**

- Not a summary of the conclusion.
- A source's own wording quoted here is not an argument for the conclusion.

### `rationale.authored_by`

| | |
|---|---|
| Owner | **CURATOR** |
| Type | `ReviewSignature` |
| Required | no |
| Null means | Null means unauthored. An unauthored conclusion is not reviewable. |
| Validation | Named person, scientific role, UTC instant, written reason. |
| Provenance | The person is accountable for the conclusion. |
| Human judgement | required |
| May enter a rule | no |

**Must not be read as:**

- A team name, a role name or a system name is not an author.

### `rationale.reviewed_by`

| | |
|---|---|
| Owner | **CURATOR** |
| Type | `ReviewSignature` |
| Required | no |
| Null means | Null means not independently reviewed, which blocks CURATED. |
| Validation | Must be a different person from the author, in a reviewing role. |
| Provenance | Recorded with instant and reason. |
| Human judgement | required |
| May enter a rule | no |

**Must not be read as:**

- The author re-reading their own work is not an independent review.

### `unresolved_references`

| | |
|---|---|
| Owner | **SYSTEM** |
| Type | `array<string>` |
| Required | no |
| Null means | Empty means nothing was left dangling, not that everything resolved successfully. |
| Validation | Populated from the evidence build's unresolved references. |
| Provenance | Carried forward from WP-07's resolution queue. |
| Human judgement | not required |
| May enter a rule | yes |

**Must not be read as:**

- An unresolved reference is not a resolved-to-nothing reference.

### `content_hash`

| | |
|---|---|
| Owner | **SYSTEM** |
| Type | `string` |
| Required | yes |
| Null means | Never null. |
| Validation | sha256 over the record's content identity, excluding operational timestamps. |
| Provenance | Deterministic; two identical records hash alike. |
| Human judgement | not required |
| May enter a rule | no |

**Must not be read as:**

- Not a signature and not an approval.

### `is_rule_eligible`

| | |
|---|---|
| Owner | **SYSTEM** |
| Type | `boolean` |
| Required | yes |
| Null means | Never null. False is the default and the safe answer. |
| Validation | True only for a CURATED, SUPPORTED conclusion with no blocking conflict, no insufficiency and no unresolved reference. |
| Provenance | Derived, never set by a curator. |
| Human judgement | not required |
| May enter a rule | yes |

**Must not be read as:**

- Eligibility is not approval: WP-11 still requires its own review before a rule exists.

