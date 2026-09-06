# Cowork Prompt — Execution Wave 3

Copy everything below this line into Claude Cowork.

---

You are executing **EXECUTION WAVE 3 — CANDIDATE SCIENTIFIC BUILD** in:

`/Users/ferob/Projects/biyoteknoloji`

This is an implementation and execution wave. Do not stop at planning or review packets. The governing model is now:

```text
AUTONOMOUS PROJECT COMPLETION FIRST
→ COMPLETE CANDIDATE PROTOTYPE
→ FINAL EXTERNAL EXPERT EVALUATION LATER
```

## 1. Mandatory reading

Read completely before editing:

- `PGx_Platform_V2_Final_THS6_Closure_Architecture_WPs.md`
- `docs/closure/current-execution-policy.md`
- `docs/closure/remaining-execution-waves.md`
- `docs/closure/wave-01-execution-report.md`
- `docs/closure/wave-02-execution-report.md`
- `data/closure/wave-01-execution-manifest.json`
- `data/closure/wave-02-execution-manifest.json`
- every file in `docs/closure/checkpoints/H01-source-policy/`
- every file in `docs/closure/checkpoints/H02-curation-protocol/`
- every file in `docs/closure/checkpoints/H03-claims-boundary/`
- every file in `docs/closure/checkpoints/H04-dataset-quality-decision/`
- `data/closure/h01-source-policy-decision.json`
- `data/closure/wp-c05-acquisition-plan.json`
- `docs/closure/wp-c05-manual-acquisition-checklist.md`
- the current scientific, acquisition, dataset, evidence, curation, rule, release, validation and claims-boundary contracts referenced by the master plan.

Historical checkpoint packages and Wave 1/Wave 2 reports are evidence of what was true at the time. Do not rewrite them as if the new execution policy existed earlier.

## 2. Measured starting point

Verify rather than blindly trust these facts:

- Wave 1 commit: `9bff75c339c4133de9d025429c6be12f491d5c84`
- H01 commit: `708d6bf5b9752c806a28691c5867afdba4fc687a`
- Wave 2 commit: `9b0bd97b45f7a025bbd92545b355315a2e1e2a76`
- no Git remote and nothing is authorized to be pushed;
- H01 contains a genuine narrow pharmacist attestation by Mehmet Yetiş;
- the attestation does not approve curation, rules, claims or the project as a whole;
- the source registry currently validates zero usable sources;
- no new acquisition-backed dataset exists;
- the only existing scientific dataset/evidence build is legacy and quarantined;
- zero curated interpretations, rules, executable rulesets and active releases exist;
- WP-C06 decision mechanics now exist, including verdict, reviewer role, source-policy/DQ binding, immutable ledger, rejection and replay/stale refusal;
- no real dataset-quality decision exists;
- H02's seven-part clinical review table exists and amitriptyline remains in scope;
- the last recorded full profile passed 7,461 tests with 0 failures and 96 classified skips;
- WP-C01/WP-C02 still have package-index, psycopg, CI-pin, container, supply-chain-tooling and staging blockers.

The Git index may currently show tracked files as staged deletions while the working files still exist, and stale `.git/HEAD.lock` / `.git/index.lock` files may exist. Treat this as an index/lock defect, not as authorization to delete the repository.

Before any implementation:

1. inspect `HEAD`, refs, locks, index and working files read-only;
2. preserve every working-tree change;
3. if authorized and safe, remove only the two exact stale zero-byte lock files and rebuild the index with `git reset --mixed HEAD`;
4. never use `git reset --hard`, `git checkout --`, `git clean`, broad deletion or `git add .`;
5. verify the project-owner planning changes against the updated master plan;
6. commit the planning-policy revision separately before Wave 3 implementation if the diff is clean and attributable.

Print a concise `WAVE_3_PRE_EDIT_STATEMENT` with the measured repository, policy, source, dataset, curation, rule, release, validation and external-access state.

## 3. Authority model — mandatory

Missing intermediate external human approval is no longer a candidate-development blocker.

For pre-expert work use only:

```text
SOURCE_GROUNDED_INTERNAL_DECISION
PROJECT_TEAM_PROVISIONAL
PENDING_EXTERNAL_EXPERT_REVIEW
INTERNAL_VALIDATION
LITERATURE_DERIVED_VALIDATION
SOFTWARE_VERIFICATION
```

Do not use or imply:

```text
EXPERT_APPROVED
PHYSICIAN_APPROVED
CLINICALLY_VALIDATED
INDEPENDENTLY_VALIDATED
EXTERNAL_REVIEWED
```

Do not populate an existing external-human approver/signature field with an AI identity or silently redefine `APPROVED` to mean provisional.

Where current schemas or services hard-block candidate development on external-human semantics, implement the smallest backward-compatible candidate authority-state path. It must:

- preserve the old external-review semantics for final closure;
- bind decisions to source and artifact hashes;
- identify the author honestly as project team or automated research workflow;
- record rationale, uncertainty, conflict and fail-closed behavior;
- carry `PENDING_EXTERNAL_EXPERT_REVIEW`;
- enable only DEMO/VALIDATION candidate use;
- keep production/clinical use and final expert-reviewed gates fail-closed;
- support later supersession by real expert-reviewed decisions without erasing history.

Candidate readiness and final THS-6 closure must be separate evaluations. Do not force the existing final THS-6 gates to PASS.

## 4. Parallel execution

Use one master orchestrator. Run independent research, read-only inspection, validation-case preparation and operational checks concurrently. Serialize writes to shared schemas, databases, generated artifacts, Git and scientific records.

If one source or external service is blocked, continue every independent source and workstream. Do not rerun the entire 7,000+ test suite during iteration; use focused tests and run the full verification profile once at the end.

## 5. Workstream A — candidate authority-state bridge

Audit every hard gate that currently requires H02, H03, H04, curator, expected-scope, rule-approval or validation-owner human metadata.

Produce a requirement-to-code table showing:

- original external-human semantic;
- candidate internal semantic;
- final external semantic preserved;
- schema/model/service/gate affected;
- migration or compatibility action;
- tests proving no authority confusion.

Create versioned internal decision records for all decisions required by this wave. At minimum include:

- source-policy/interface selection;
- curation protocol and vocabulary;
- claims boundary and bilingual warning;
- dataset-quality decision;
- each curated interpretation;
- expected gene scope;
- every provisional rule and ruleset;
- internal validation reference judgments.

Do not create empty governance scaffolding. Every new field or record type must directly unblock an actual candidate artifact in this wave.

Preserve the real H01 pharmacist attestation exactly as narrow supporting evidence. Do not broaden it.

## 6. Workstream B — source grounding and permitted acquisition

The new policy removes the external source-approver dependency. It does not remove licensing, access, provenance or H01 restrictions.

For every first-release source/interface:

1. retrieve the strongest available authoritative primary evidence;
2. use official guideline/regulator/provider locations;
3. record URL, organization, version, access instant, content hash, terms/licence basis, citation requirements and reuse constraints;
4. compare multiple sources when legally and technically available;
5. record conflicts and absence explicitly;
6. create a `SOURCE_GROUNDED_INTERNAL_DECISION` for each usable interface;
7. leave every decision `PENDING_EXTERNAL_EXPERT_REVIEW`.

Hard prohibitions remain:

- no unknown-terms API access;
- no scraping or crawling;
- no bulk download;
- no bypass of robots, authentication, rate limits or access controls;
- no prohibited full-text storage or redistribution;
- no commercial/public reuse beyond recorded rights;
- no retrospective legitimization of legacy ClinPGx data.

Targeted one-document-at-a-time browser retrieval may be used only when the official public interface and recorded terms permit it. Classify it honestly as agent-assisted targeted retrieval, not as a human download and not as an API. If the policy does not permit that mode, do not retrieve it.

If a source permits citation/review but not local full-text storage, retain only the permitted citation, locator, version, checksum/evidence of the accessed public item, and normalized derived record where expressly allowed. Do not copy prohibited text into the repository.

The first candidate scope is fixed:

- genes: CYP2C19, CYP2D6;
- drugs: clopidogrel, codeine, omeprazole, amitriptyline;
- clopidogrel context: explicitly ACS/PCI only;
- amitriptyline: joint CYP2C19 + CYP2D6 decision representation;
- no CYP2D6 RAPID expectation;
- Likely/Indeterminate/unrepresentable activity-score states fail closed;
- an axis absent from regulator evidence must not be represented as regulator-supported.

Do not expand toward the future 40–50-drug vision.

## 7. Workstream C — WP-C05 clean dataset and evidence

Create the first legitimate candidate dataset from new, permitted acquisition evidence.

- allocate a new dataset ID through the canonical mechanism;
- never reuse, rename, promote, copy-as-new or derive scientific truth from `PGX-DATA-20260830-900`;
- build one immutable raw snapshot per actual source when required by existing contracts;
- never label multiple sources as one false source key;
- record acquisition manifests, timestamps, URLs, operator class and hashes;
- seal and independently verify snapshots;
- canonicalize only unambiguous drug/gene entities;
- deduplicate deterministically;
- refuse ambiguous aliases rather than guess;
- generate the DQ report;
- build source-to-snapshot-to-canonical-to-evidence traceability;
- verify reproducibility from sealed input;
- keep source text only where storage is permitted.

If the existing one-source snapshot/dataset model cannot represent the required candidate evidence, prove the gap and implement only the smallest backward-compatible multi-source association. Do not redesign the backend or build a new knowledge platform.

Do not mark a partial citation collection as a complete sealed scientific dataset. If exact content is unavailable, preserve legitimate partial evidence, state the missing artifact and continue other workstreams.

## 8. Workstream D — WP-C06 provisional dataset-quality decision

Reuse the Wave 2 mechanism. Do not rebuild it.

Add only the minimum operator/service/persistence path required to record a real internal candidate decision against the new dataset.

The decision must contain:

- decision: `ACCEPTED` or `REJECTED`;
- authority state: `PROJECT_TEAM_PROVISIONAL`;
- review state: `PENDING_EXTERNAL_EXPERT_REVIEW`;
- honest project-team decision author;
- rationale;
- exact DQ artifact hash;
- exact source-policy/internal-decision hash;
- immutable audit record and timestamp.

An accepted decision may make the dataset candidate-release-eligible in DEMO/VALIDATION mode only. A rejection moves nothing. Stale hashes, replay, conflicting decisions and missing builds must fail closed.

Do not fill or fake H04's historical external approval form.

## 9. Workstream E — WP-C07 internal scientific curation

Do not wait for H02 external approval. Convert each H02 open question into a source-grounded project-team provisional decision.

For only the fixed candidate scope:

- build evidence bundles and side-by-side source comparisons;
- prepare normalized interpretations;
- record effect direction, clinical significance, metabolism/exposure/activation direction, rationale, uncertainty, conflicts and evidence references;
- perform an independent internal critical/source-comparison pass;
- record disagreements and provisional dispositions;
- produce governed `CuratedInterpretation` records with project-team provisional authority and pending-expert status.

Required conservative decisions:

- amitriptyline is represented through the joint CYP2C19 + CYP2D6 matrix supported by the source, never as two falsely independent recommendations;
- clopidogrel is limited to explicit ACS/PCI context;
- CYP2D6 RAPID is not expected;
- Likely, Indeterminate and unsupported activity-score cases refuse/fail closed;
- regulator absence is explicit rather than silently treated as support;
- current clopidogrel loss-of-function/structured-warning semantics are used only when that regulator source is actually in the permitted evidence set;
- the 13 legacy in-scope candidates are not evidence and must be curated anew from permitted sources.

An AI critical pass is not a second human curator, adjudicator or independent expert. Label it honestly.

## 10. Workstream F — WP-C08 candidate rules and ruleset

Transform only the governed provisional interpretations into deterministic candidate rules.

- preserve all required provenance hashes;
- create internal decision envelopes without writing fake human approval envelopes;
- declare provisional expected gene scope per drug from authoritative evidence;
- record scope rationale, uncertainty and pending-expert state;
- make missing expected genes produce explicit insufficient coverage;
- ensure no rule issues diagnosis, dosing, treatment selection or candidate-safety conclusions;
- keep coverage and attention separate;
- validate rule lifecycle and evidence links;
- target approximately 20–25 rules only where the evidence supports them;
- never pad the rule count by inventing unsupported phenotype cells;
- build, validate, freeze and register an executable candidate ruleset;
- restrict execution to DEMO/VALIDATION candidate mode.

If authoritative evidence supports fewer safe rules, record the real count and coverage gaps. Do not invent content to meet a target.

## 11. Workstream G — WP-C09 active candidate release

Build the first candidate release bundle:

```text
software version
+ provisionally accepted candidate dataset
+ frozen executable candidate ruleset
= candidate release bundle
```

- register exact content hashes and versions;
- validate the release bundle;
- activate it only in DEMO/VALIDATION mode;
- verify the assessment service resolves that exact bundle;
- verify every assessment/report carries release metadata and provisional authority labels;
- verify no mutable legacy path can bypass the release;
- verify rollback metadata;
- visibly expose `PENDING_EXTERNAL_EXPERT_REVIEW`.

Do not call the candidate clinically validated, externally reviewed or production-approved.

## 12. Workstream H — WP-C10 validation preparation in parallel

As soon as provisional expected scope is stable:

- create 50+ synthetic or published-literature-derived candidate cases;
- create at least 20 sealed INTERNAL_HOLDOUT cases;
- reserve at least 10 cases for final external expert evaluation;
- give internally scored cases source-grounded provisional reference judgments;
- do not invent expert judgments for reserved cases;
- fingerprint cases and enforce separation;
- create an access ledger and leakage detectors;
- prevent rules/content workstreams from seeing sealed internal-holdout answers before benchmark execution;
- label all results internal or literature-derived.

Do not execute the full WP-C11 benchmark in this wave unless every Wave 3 scientific dependency is complete and doing so cannot compromise holdout separation. Wave 4 owns final internal benchmark closure.

## 13. Workstream I — operations residuals

Continue WP-C01/WP-C02 only when it does not delay the scientific critical path:

- `uv.lock` through the real resolver;
- wheel/sdist through the configured backend;
- real application-to-PostgreSQL and audit-chain execution;
- CI action-pin resolution and local CI equivalent;
- container build, SBOM and vulnerability scan;
- staging/TLS only with an authorized destination.

Do not hand-author a lock, substitute a build backend, create/push a remote, or call localhost real staging. Report external blockers precisely and continue candidate work.

## 14. Testing and evidence

Use focused tests during implementation. At the end:

1. run schema/generated-artifact checks;
2. verify snapshots, canonical builds, evidence, decisions, interpretations, rulesets and release hashes;
3. run source-policy and claim-boundary safety checks;
4. run secret and absolute-path scans;
5. run the full verification profile once;
6. rebuild and verify the THS-6 evidence pack without forcing final gates.

Every completion claim needs command, exit result, UTC timestamp, environment fingerprint, artifact path and SHA-256 where supported.

Create:

- `docs/closure/wave-03-execution-report.md`;
- `data/closure/wave-03-execution-manifest.json`;
- canonical internal-decision records;
- a candidate-readiness result separate from final THS-6 status.

Historical evidence remains historical. Regenerate current aggregate artifacts through canonical producers; do not hand-edit counts or statuses.

## 15. Stop conditions

Do not stop merely because H02, H03 or H04 lacks an external signature.

Stop only when:

- every autonomous candidate-scientific task in this wave is completed or blocked by a precise source/access/safety/infrastructure condition;
- all independent work has been exhausted;
- no partial dataset/ruleset/release is misrepresented as complete;
- candidate and final-expert authority states remain distinct;
- every blocker has an exact owner, required input and continuation command;
- focused tests pass and one final full run has been attempted;
- the Wave 3 report and manifest are complete.

Do not begin WP-C14A, WP-C14, WP-C12 final external evaluation, WP-C14B or WP-C15.

## 16. Required final response

Return these exact sections:

```text
WAVE_3_PRE_EDIT_STATEMENT
PLANNING_POLICY_COMMIT
COMPLETED
PARTIALLY_COMPLETED
FAILED
BLOCKED_BY_SOURCE_ACCESS_OR_TERMS
BLOCKED_BY_EXTERNAL_ACCESS
NEWLY_DISCOVERED_BLOCKERS
AUTHORITY_STATE_BRIDGE_RESULT
SOURCE_GROUNDED_DECISION_MATRIX
NEW_DATASET_AND_EVIDENCE_RESULT
PROVISIONAL_DQ_DECISION_RESULT
INTERNAL_CURATION_RESULT
CANDIDATE_RULESET_AND_COVERAGE_RESULT
ACTIVE_CANDIDATE_RELEASE_RESULT
VALIDATION_CATALOGUE_RESULT
OPERATIONAL_RESIDUAL_RESULT
FILES_CREATED_OR_MODIFIED
COMMANDS_EXECUTED
TEST_AND_GATE_RESULTS
EVIDENCE_GENERATED_WITH_SHA256
GIT_FINAL_STATE
RECOMMENDED_WAVE_4
```

In `RECOMMENDED_WAVE_4`, state whether the active candidate release, internal holdout, operational environment and browser application are ready for internal benchmark and Product Surface / Demo UX closure.

Do not ask for intermediate expert approval. Do not begin Wave 4.

