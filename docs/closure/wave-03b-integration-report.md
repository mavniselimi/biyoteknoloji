# Wave 3B — core scientific integration

**Status: all ten integration gates PASS.** Every verdict below is computed
from the artifacts by `scripts/build_wave03b_manifest.py`, not asserted in
prose; the manifest it writes is `data/closure/wave-03b-integration-manifest.json`.

**What that does not mean.** Nothing here is externally reviewed, clinically
validated, independently validated, expert approved or production approved,
and this is not final THS-6 closure. The claim boundary the candidate path runs
under reports `is_approved` as **false**, and says so in every result it
produces.

## 1. The Wave 3 finding, and what was actually wrong

Wave 3 produced source-grounded science and then stopped beside the
application instead of inside it. Its own report said so. The reason it stopped
was concrete and is worth stating, because it explains every design decision
below: **`DEFAULT_CLAIM_BOUNDARY.is_approved` is `False`**, so
`AssessmentInput.require_permitted` refuses every assessment, and
`docs/architecture/intended-purpose.md` section 11 needs four named signatures
that do not exist. Faced with a locked front door, Wave 3 built a side entrance
— a second evaluator under `pgx/closure`. That was the defect.

Everything Wave 3 produced is preserved unchanged: its report, its manifest,
`PGX-CANDIDATE-EVIDENCE-WAVE03`, `PGX-CANDIDATE-RELEASE-WAVE03`, and the
rejection of `PGX-DATA-20260830-900`. Wave 3B supersedes by lineage.

## 2. The authority path — a new type, not a relaxed one

`is_approved` was **not** made permissive, and `pgx/domain/claims.py` was not
edited at all. The provisional boundary lives in a new module,
`pgx/domain/candidate_claims.py`, holding `ClaimBoundaryAuthority`, a
`CandidateClaimBoundary` subclass, and `P0_CANDIDATE_CLAIM_BOUNDARY` — identical
to P0 in every restriction.

**Why a new module.** The first version of this work put those additions inside
`claims.py`, which is a frozen WP-01 legacy baseline artifact pinned in
`data/legacy-baseline/manifest.json` with `mutable_legacy_state: false`;
`scripts/amend_legacy_manifest.py` refuses to amend a legacy entry at all. The
edit was caught by `tests/unit/test_manifest_amendment.py::test_every_legacy_
artifact_hash_still_matches_disk`, the guard that exists for exactly this. The
file was restored to its baseline bytes and the whole baseline — 64 legacy and
22 evidence artifacts — matches disk again.

**Why a distinct type, independent of that.** `ClaimBoundary.is_approved` is a
substring test for "DRAFT" and "AWAITING" over a free-text status, and the
candidate status `PROJECT_TEAM_PROVISIONAL / PENDING EXTERNAL EXPERT REVIEW`
contains neither — so a candidate boundary built as a plain `ClaimBoundary`
reported itself **approved**. A boundary signed by nobody claimed a human
approval. `CandidateClaimBoundary.is_approved` does not read the status; it
returns the constant `False`, so no wording can move it. The frozen class keeps
its WP-00 behaviour for every boundary that is not this one.

`permits_execution` cannot enable a mode the boundary does not already enable,
so a provisional boundary can never unlock `PILOT`. That needs the signatures.
`tests/unit/engine/test_wp14_boundaries.py` now admits a second boundary owner
and pays for it with a check that no boundary either owner ships is approved or
enables `PILOT`. `ADR 0001` records the decision, as `architecture.md`
section 23 requires.

## 3. Honest acquisition vocabulary

| Value | Where | Why not an existing member |
|---|---|---|
| `AcquisitionMode.AGENT_TARGETED_RETRIEVAL` | 24 chars, fits `String(32)` | `MANUAL_DOWNLOAD` and `PUBLICATION_TRANSCRIPTION` assert a human; `OFFICIAL_API` and `LICENSED_BULK_EXPORT` an agreed interface; `INTERNAL_DERIVATION` no external source; `NOT_DETERMINED` no decision |
| `SnapshotKind.TRANSCRIPTION_CAPTURE` | 21 chars, fits `String(24)` | `ACQUISITION`/`CACHE_REPLAY` claim a WP-04 run; `LEGACY_IMPORT` claims the frozen probe scripts |

Not `SOURCE_TRANSCRIPTION_CAPTURE`, at 28 characters, because the column is 24.
Migration `0012` widens both check constraints additively and **refuses to
downgrade** while any row still carries the new values, rather than deleting
provenance to satisfy a schema. `AGENT_TARGETED_RETRIEVAL` is excluded from
`AUTOMATED_ACQUISITION_MODES`: a mode describing a targeted read must never
become permission for an unattended one.

## 4. Capture, dataset and the data-quality decision

`data/raw/cpic-guideline-capture/PGX-DATA-20260906-001` is sealed through
`SnapshotManager`, `TRANSCRIPTION_CAPTURE`, four artifacts, a retrieval log
naming the four documents read, `complete: false`, and eight limitations. Its
four artifact names are new — `capture_genes.json`, `capture_chemicals.json`,
`capture_axes.json`, `capture_recommendation_rows.json` — with their own roles
and extraction handlers. Reusing `resolved_genes.json` and its siblings would
have been the misdescription: those names mean "this is what the ClinPGx
endpoint returned".

`PGX-DATA-20260906-001` is built through `build_canonical_dataset`: 2 genes,
4 drugs, 35 records, 0 duplicates, 0 findings.

**The data-quality gate did not pass, and the acceptance says so on its face.**
Two blocking issues remain and both are structural rather than defects:

- `SNAPSHOT_COMPLETENESS_UNKNOWN` — a capture cannot assert completeness
  relative to a corpus it did not crawl, and should not.
- `SOURCE_POLICY_NOT_APPROVED` — no human decision authorises
  `AGENT_TARGETED_RETRIEVAL`. H01's recorded outcome for `cpic.database`
  permits `MANUAL_DOWNLOAD` and `INTERNAL_DERIVATION` under the condition
  "manual review and citation only", and its prohibited list includes
  "expanding the approved source set by implication".

Both were declared in advance as a **closed** exception list in
`pgx/closure/candidate_dq_criteria.py`; any other blocking code fails the
criteria outright. The verdict is `ACCEPTED_FOR_CANDIDATE_USE`, a third ledger
value that does not permit the WP-07 transition and is spelled so it cannot be
skimmed as `APPROVED`.

`cpic.guideline-capture` is **registered, not approved**: `PENDING_REVIEW`,
`review: null`, three blocking reasons, and an interpretation attributed to a
process. Registering records what the project verified — the CC0-1.0 dedication
quoted from CPIC's own `LICENSE.md`, the robots directives, the unreadable API
terms — without extending a named pharmacist's decision past its scope.

### Two ledger corrections, both kept visible

The first candidate verdict was **`REJECTED`**, produced by a defect in my own
criteria evaluator: `CD-08` read the manifest's `source_observed_axes` as a
list of axis names when it is an object of counts, so all five axes appeared
missing. The dataset was never at fault.

The ledger refused a second verdict — correctly — and its own error text named
the answer: "record a superseding decision deliberately". That mechanism did
not exist, so it was built: an explicit `supersedes`/`supersedes_reason` pair,
refused unless it names a real, current, not-already-superseded decision. Both
rows remain and the renderer marks superseded ones.

The same mechanism then handled a second, unrelated correction: registering the
capture source changed the registry digest, which left Wave 3's rejection of
`PGX-DATA-20260830-900` stale-bound. The rejection was restated and re-bound;
the verdict never changed.

## 5. The scientific model

### Amitriptyline — a real joint rule, not a maximum

`JointRuleCondition` is a first-class condition type in the WP-11 grammar.
Every gene it names must be present and match. There is no partial evaluation,
no fallback to one gene, and no default for an absent axis. It is a distinct
class, so a caller that has not been taught about joint conditions cannot
evaluate one as though it were single-gene.

The guideline's 16 cells become **12 rules** using `ONE_OF`, which lists both
phenotypes explicitly — the grammar's own mechanism for "applies to both", and
the reason it refuses wildcards. All 20 expanded combinations are covered.

The freeze refuses if a drug carries both a joint rule and a single-gene rule,
if declared gene scope disagrees with what the rules cover, if a care-setting
drug has a rule without one, or if two rules match one observation.

### Clopidogrel — an explicit care setting, never inferred

`AssessmentInput` gained `care_setting`, a closed vocabulary of exactly one
member today. **It is not an `indication`**, which stays refused: an indication
is a clinical judgement about a patient, while a care setting selects which
column of a guideline table applies. The system never infers it. Absent,
clopidogrel returns `NOT_ASSESSED`. It enters the input hash, so two otherwise
identical requests are two different questions.

### The ruleset

26 rules (12 joint), 13 explicit refusals, `DEMO` and `VALIDATION` only.

| gene | drug | phenotypes answered |
|---|---|---|
| CYP2C19 | clopidogrel | ULTRARAPID, RAPID, NORMAL, INTERMEDIATE, POOR (ACS/PCI only) |
| CYP2C19 | omeprazole | ULTRARAPID, RAPID, NORMAL, INTERMEDIATE, POOR |
| CYP2C19 × CYP2D6 | amitriptyline | 20 combinations, jointly |
| CYP2D6 | codeine | ULTRARAPID, NORMAL, INTERMEDIATE, POOR |

CYP2D6 `RAPID` is refused for both CYP2D6 drugs: the project's vocabulary has
the member, CPIC's activity-score model has no such band, and an axis absent
from the evidence must not be shown as evidence-supported.

## 6. The runtime path

`ReleaseContextResolver` had **no production implementation** — only test
fixtures, with `apps/api/provider.py` raising `ACTIVE_RELEASE_UNAVAILABLE`.
There is one now. It reads the pointer once and refuses a non-`ACTIVE`
release, a moved manifest hash, a moved ruleset byte, a superseded
data-quality decision, and a ruleset rebuilt from code that no longer matches
the frozen artifact.

That last check fired during this work and was right to: removing
`attention_level` from the curation record changed every interpretation hash,
so the artifact and the code had genuinely drifted.

`PGX-CANDIDATE-REL-20260906-001` is `ACTIVE`, generation 1, binding the
dataset, the frozen ruleset, the capture snapshot, the source-policy digest and
the data-quality decision.

**On "one evaluation path".** `pgx/engine/candidate_evaluation.py` is a second
*artifact* path, not a second engine, and the distinction is load-bearing:
`assessment_service.py` executes a governed release and
`evaluate_axis_finding` verifies a WP-10 approval record for every rule; a
candidate rule carries none, by design, so it cannot go through that path and
must not be made to look as though it can. What is **not** duplicated is the
answer — the candidate path gets its attention level from
`risk_models.aggregate_attention`, the same function the governed path uses, so
the two cannot drift on the one question where drifting would matter.

## 7. Seven boundary guards fired; none was weakened

| Guard | What it caught | How it was answered |
|---|---|---|
| curation/rules layer purity | both new modules imported `pgx.closure.authority` | the vocabulary moved to `pgx/domain/authority.py`, where it belongs; closure re-exports it |
| curation computes no attention | `CandidateInterpretation` carried an `attention_level` | the field is gone; the mapping happens at rule-build time, in WP-11's layer |
| `data/rulesets` is empty | the candidate ruleset sat where `FrozenRulesetRegistry` scans | moved to `data/candidate-rulesets` |
| engine/application inventories | three unregistered modules | registered by name, with the WP-14 architecture note updated |
| artifact role map | a second snapshot family made "missing" meaningless for both | artifacts now name their family; missing is computed within it |
| WP-01 legacy baseline hashes | the candidate boundary had been added inside the frozen `pgx/domain/claims.py` | the file was restored to its baseline bytes; the boundary moved to `pgx/domain/candidate_claims.py` (section 2) |
| only one module constructs a `ClaimBoundary` | the new module is a second owner | the exemption is explicit and paid for by a check that no boundary either owner ships is approved or enables `PILOT` |

The baseline guard fired late — during Wave 4, not Wave 3B — because the suite
that carries it, `tests/unit/test_manifest_amendment.py`, sits at the top level
of `tests/unit` and was not in the per-package sweep Wave 3B ran. It is in the
sweep now. Nothing about the finding was environmental: the amendment tool
refuses to amend a legacy entry at all, so there was never a sanctioned way to
bless the edit, only a wrong one and a right one.

Adding `care_setting` to `semantic_content` also broke 63 application tests,
because `build_input_snapshot` builds the hashed document separately. Both
sides carry it now, and so does the published schema.

## 8. The gate

| | Requirement | Verdict |
|---|---|---|
| G1 | Core evidence capture with honest retrieval semantics | **PASS** |
| G2 | Canonical candidate dataset sealed and deterministic | **PASS** |
| G3 | Project-team provisional DQ decision accepts that exact dataset | **PASS** |
| G4 | Core curation records with complete provenance | **PASS** |
| G5 | Amitriptyline represented by an actual joint two-gene rule model | **PASS** |
| G6 | Core candidate ruleset frozen and executable | **PASS** |
| G7 | Candidate release ACTIVE through the release service | **PASS** |
| G8 | Main assessment service consumes that active release | **PASS** |
| G9 | Required safety and fail-closed tests pass | **PASS** |
| G10 | No external approval or final THS-6 claim fabricated | **PASS** |

27 tests in `tests/unit/closure/test_wave03b_assessment.py` assert G5, G8 and
G9 directly: clopidogrel refuses without a care setting and resolves with one;
amitriptyline needs both genes and never falls back; CYP2D6 `RAPID` refuses; an
indeterminate observation cannot even be constructed; `PILOT` is rejected;
`DEMO` and `VALIDATION` work; a missing, non-active, pointer-mismatched or
tampered release fails closed; and a refusal is never reported as
`NO_ACTIVE_ATTENTION`.

## 9. What remains blocked, unchanged by this wave

`OR-01` to `OR-07` remain blocked on network egress neither environment has.

`OR-10` is now measured rather than described. WP-19's verification artifacts
were last rebuilt in Wave 2 (`9b0bd97`) and were already stale at this brief's
baseline `505b787`, which was missing three Wave 3 closure suites. Wave 3B and
Wave 4 added two more and changed six, so the committed inventory reads 274
suites and 7,461 tests against 277 and 7,562 on disk. A rebuild on the device
VM drops `tests.unit.expert_review.test_persistence` and
`tests.unit.security.test_persistence` into `load_failures` — `sqlalchemy` is
absent and no package index is reachable — which replaces a stale artifact with
a wrong one; the cloud container has `sqlalchemy` but not the repository. The
artifacts were left stale and the guards that detect the staleness were left
failing.

The remaining test failures fall in exactly two pre-existing categories:
`sqlalchemy` and the API extras are absent from this host (deployment, security,
expert-review, one API route test, `wp16-real-gate-status.json`), and WP-19
staleness (`ths6`, `verification`).

## 10. What Wave 3B deliberately did not do

- did not approve the intended-purpose claim boundary, or fabricate a
  signature for it;
- did not extend H01 beyond its recorded scope, and did not synthesise a
  `ReviewRecord` — whose docstring says every field is "a thing a forged
  approval would have to invent";
- did not make `approval_envelope_hash` optional, or weaken any WP-10
  invariant;
- did not touch `pgx.expert_review`, the WP-13 governed active-release pointer,
  or the THS-6 gate matrix;
- did not rewrite `PGX-CANDIDATE-RELEASE-WAVE03` into something it never was;
- did not begin WP-C12 or WP-C14B, and claims no final THS-6 closure;
- did not weaken a single guard. Every one that fired was answered by fixing
  the design or by replacing an assertion that had become false.
