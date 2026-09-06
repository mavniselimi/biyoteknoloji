# Execution Wave 3 — candidate scientific build

**Status.** A candidate scientific prototype exists. Nobody outside this
project has seen it. Every artifact this wave produced carries one of six
pre-expert authority states, and none of them claims expert approval,
physician approval, clinical validation, independent validation or external
review.

**What this document is not.** It is not a readiness assessment for THS-6.
Candidate readiness and THS-6 closure are separate evaluations, and Wave 3
did not write to the gate matrix, add a condition to it, or change any value
it reads. Every figure below is read from
`data/closure/wave-03-execution-manifest.json`, which is generated from the
artifacts rather than typed in.

---

## 1. The authority bridge (workstream A)

Twelve requirements that already exist in this repository were examined, and
each was answered with what a candidate artifact can honestly do about it.

| verdict | rows |
| --- | --- |
| `SATISFIED_BY_CANDIDATE_TRACK` | 4 |
| `BLOCKED_REQUIRES_EXTERNAL_HUMAN` | 4 |
| `BLOCKED_REQUIRES_SECOND_INTERNAL_HUMAN` | 2 |
| `NOT_APPLICABLE_TO_CANDIDATE_TRACK` | 2 |

The blocked rows are the useful ones. `AB-01` records that a rule cannot leave
`CURATED` without a WP-10 approval envelope separating creator, reviewer and
approver — and this is asserted against the code rather than against its own
prose: `RuleProvenance.approval_envelope_hash` is a required `sha256:` digest
with no default, and a test fails if that ever becomes optional. That single
field is why the candidate rules are their own type rather than
`ComputableRuleDefinition` instances: constructing one would have meant
inventing that digest.

Two vocabulary gaps were found and **not** closed, for the same reason twice.

`AB-07` — `AcquisitionMode` has six members and none describes what happened.
`MANUAL_DOWNLOAD` and `PUBLICATION_TRANSCRIPTION` both say a human did it,
`OFFICIAL_API` and `LICENSED_BULK_EXPORT` say an agreed interface did,
`INTERNAL_DERIVATION` says no external source was involved, `NOT_DETERMINED`
says nobody decided. The smallest honest change is additive — one new member,
deliberately excluded from `AUTOMATED_ACQUISITION_MODES`, at most 32
characters to fit the existing column, plus one migration widening
`ck_source_policies_acquisition_mode_enum`. Wave 3 did not make it. Widening
the production source vocabulary is a decision about what this project is
permitted to do, and that belongs to a person rather than to the wave that
wants the permission. `config/scientific-sources.json` is byte-identical to
where H01 left it.

The same shape appeared in `SnapshotKind`, and is recorded under workstream C.

## 2. Source grounding (workstream B)

Four CPIC guideline annotations were retrieved through ClinPGx's public web
interface, one document at a time, in the order a reader would open them.

| drug | genes | annotation | version | PMID | DOI |
| --- | --- | --- | --- | --- | --- |
| clopidogrel | CYP2C19 | PA166104948 | 2022 Update | 35034351 | 10.1002/cpt.2526 |
| omeprazole | CYP2C19 | PA166219103 | August 2020 | 32770672 | 10.1002/cpt.2015 |
| amitriptyline | CYP2C19, CYP2D6 | PA166105006 | 2016 Update + Oct 2019 CYP2D6 translation | 27997040 | 10.1002/cpt.597 |
| codeine | CYP2D6 | PA166104996 | December 2020 opioids | 33387367 | 10.1002/cpt.2149 |

**Permission basis.** CPIC's own `LICENSE.md` in `cpicpgx/cpic-data` states
that "All curated content published by CPIC is available free of restriction
under the CC0 1.0 Universal (CC0 1.0) Public Domain Dedication". That permits
storage, derivative works, redistribution and commercial use. It does not
permit any particular *manner* of acquisition, which is recorded separately.
`clinpgx.org/robots.txt` disallows only `/literature/`, and only for
`SiteimproveBot`; nothing disallows the guideline paths used here, and
`/literature/` was not fetched. The ClinPGx API at `api.clinpgx.org` remains
unusable: its terms could not be read, and an interface whose terms are unknown
is an interface this project may not call.

**How the retrieval is classified.** As `AGENT_ASSISTED_TARGETED_RETRIEVAL`.
Not a human download, not an API. Five limits are recorded in the artifact
itself rather than only here:

- no byte-level hash of the served document exists — the retrieval tool
  returns rendered page text, not the HTTP response body;
- no per-request timestamp exists — each retrieval records the date it
  happened on and a measured instant it provably preceded, rather than a
  second-precision instant nobody measured;
- no full text of any guideline, supplement or publication is stored here;
- no source's programmatic interface was called and no page other than those
  named was fetched;
- the reading is this project's own, and none of the cited organizations has
  seen it.

The hash over the transcription is called `extraction_digest` and not
`content_hash`, because it pins what this project wrote down and would say
nothing about the upstream document changing.

## 3. What the sources say that this project cannot represent

Thirty recommendation rows were transcribed, **including the ones that cannot
cross into this project's vocabulary**. Seven cannot, and they are recorded and
marked rather than dropped:

- `CYP2C19 likely intermediate metabolizer` and `CYP2C19 likely poor
  metabolizer`, for clopidogrel and omeprazole. The phenotype vocabulary has
  five determinate members and no member for a likely assignment; mapping
  either to its determinate neighbour would assert a determination the
  guideline explicitly declined to make.
- `Indeterminate`, for clopidogrel, omeprazole and codeine. The source states
  "No recommendation", and the condition grammar refuses `INDETERMINATE` as a
  rule phenotype because it describes the input rather than a phenotype a rule
  is about.

Two further gaps have different causes and are recorded with different reason
codes, because collapsing them would lose the distinction:

- **CYP2D6 `RAPID` does not exist in the evidence.** CPIC's CYP2D6 model is an
  activity-score model whose bands are ultrarapid, normal, intermediate and
  poor. This project's vocabulary *does* have a `RAPID` member. Using it would
  present an answer the regulator evidence does not contain, so both CYP2D6
  drugs refuse it under `AXIS_ABSENT_FROM_SOURCE`.
- **The 2016 tricyclic guideline predates CPIC's likely labels**, so
  amitriptyline has no `likely` CYP2C19 row at all — a missing row, not an
  unrepresentable one, recorded as `SOURCE_ROW_ABSENT`.

Clopidogrel is transcribed from the ACS/PCI column only. The guideline's Table
1 carries two independent classification columns and a second table for
neurovascular indications, which answer differently; a row lifted out of its
column would apply to indications nobody scoped.

## 4. Internal curation (workstream E)

Each recommendation is mapped to an attention level individually, with its own
recorded reason, and an unmapped recommendation raises rather than defaulting.
Twenty-three curations: 9 `HIGH`, 2 `MEDIUM`, 5 `LOW`, 7 `NO_ACTIVE_ATTENTION`.

The line that took the most care is between `NO_ACTIVE_ATTENTION` and `LOW`.
`NO_ACTIVE_ATTENTION` is used only where the guideline asks for nothing at all.
Omeprazole's normal-metabolizer row says "initiate standard starting daily
dose" and then asks the prescriber to consider a 50–100% increase for
*H. pylori* infection and erosive oesophagitis; codeine's intermediate row
says label dosing and then "if no response, consider a non-tramadol opioid".
Both are `LOW`, because a reader who saw `NO_ACTIVE_ATTENTION` would not go
looking for the qualifier. This is `SAFETY-INV-001` applied at the boundary
where false reassurance actually happens.

The curator is named as a process — "automated curation pass (no human
curator)" — in every record. An AI pass is not a second human curator, and
nothing here pretends otherwise.

## 5. The candidate ruleset (workstream F)

**23 rules, 13 explicit refusals.** Coverage:

| gene | drug | phenotypes answered |
| --- | --- | --- |
| CYP2C19 | clopidogrel | ULTRARAPID, RAPID, NORMAL, INTERMEDIATE, POOR |
| CYP2C19 | omeprazole | ULTRARAPID, RAPID, NORMAL, INTERMEDIATE, POOR |
| CYP2C19 | amitriptyline | ULTRARAPID, RAPID, NORMAL, INTERMEDIATE, POOR |
| CYP2D6 | codeine | ULTRARAPID, NORMAL, INTERMEDIATE, POOR |
| CYP2D6 | amitriptyline | ULTRARAPID, NORMAL, INTERMEDIATE, POOR |

The rules reuse WP-11's condition grammar exactly — same `RuleCondition`, same
`PhenotypeMatch`, same refusal of wildcards, negation and implicit phenotype
expansion — but they are their own type, so a candidate rule cannot be passed
where a validated one is expected by a caller that forgot to check.

The freeze refuses to proceed on three conditions. Two are ordinary
(duplicate rules, understated joint cells). The third earned its keep during
this wave: **every phenotype in scope must be either ruled or refused**, and
the first run of the freeze failed because `CYP2C19 / amitriptyline /
INDETERMINATE` was neither. The refusal records had recorded "no project
phenotype carries this label", which is true of a *rule* phenotype and false
of an *input* — `INDETERMINATE` is a real input the system can receive and
must refuse. A rule set and a refusal list maintained independently drift, and
the combination that falls out of both is the one answered by accident.

### The joint table the grammar cannot express

Amitriptyline's guideline carries a two-dimensional CYP2C19 × CYP2D6 table
that is **not** the pointwise combination of its two single-gene tables. The
WP-11 grammar has one gene per condition and cannot carry a cell of it.

Rather than approximate it, the build checks against it. All 20 expanded
combinations are evaluated: for each, the precedence maximum of the two
single-gene candidate rules is compared with the level implied by the
guideline's own joint answer, and the freeze aborts if any combination would
come out **weaker**. None does. The check runs on every build, and a test
asserts that the detector is capable of firing, because a detector that never
fires proves nothing about the table.

## 6. Dataset and evidence (workstreams C and D)

**No raw snapshot was written, and that is the finding.** `SnapshotKind` has
three members: `ACQUISITION` and `CACHE_REPLAY` both assert a WP-04
acquisition run with full retrieval metadata behind the bytes, and
`LEGACY_IMPORT` asserts the files predate the adapter and came from the frozen
legacy probe scripts. Wave 3's retrieval is none of those, and neither
execution environment available to this project can reach the publisher to
perform an acquisition — `pypi.org`, `api.github.com` and `clinpgx.org` all
return HTTP 403 through the proxy, and the device VM has no egress at all.

So the transcription is sealed under its own identity —
`PGX-CANDIDATE-EVIDENCE-WAVE03`, 10 artifacts, per-file digests, a content
hash over the set — with the same integrity discipline and none of the claims.
It is written outside `data/raw/` and `data/canonical/` on purpose: a directory
in either tree is read by tooling entitled to assume things this content
cannot support. Its manifest carries `is_raw_snapshot: false` and
`is_canonical_dataset: false` as fields, not as prose.

**The first dataset-quality decision was recorded, and it is a rejection.**
The WP-C06 ledger held zero rows after Wave 2, which was correct — a mechanism
for recording a decision is not a decision. It now holds one:
`PGX-DATA-20260830-900`, `REJECTED`. The dataset's own `dq-report.json`
reports `passed: false` with three blocking codes — `SNAPSHOT_NOT_ACQUIRED`,
`SNAPSHOT_QUARANTINED` and `SOURCE_POLICY_MISSING` — and WP-C00 separately
established that all 33 of its legacy rule candidates name no upstream record
at all. An empty ledger and a recorded rejection look identical to a gate and
completely different to a person.

The reviewer fields carry a process identifier that cannot be read as a name.
This surfaced a defect in Wave 2's own output: `render_review_record` told the
reader that every row was "one named person's verdict", which became false the
moment an automated pass recorded one. The header now tells the reader to
check the reviewer column.

The Wave 2 test asserting an empty ledger was **replaced, not deleted**. The
property that mattered was never "the ledger is empty" but "no row claims more
than happened", so it now asserts that no committed decision approves a
dataset, that any automated reviewer says so in its own name, and that every
committed decision still describes the build it was bound to.

## 7. Candidate release and validation (workstreams G and H)

`PGX-CANDIDATE-RELEASE-WAVE03`, executable in `DEMO` and `VALIDATION` and
nowhere else. `is_governed_release: false`. Not registered with WP-13.

The evaluator refuses when any named axis has no rule, rather than answering
from the axes that did match, and a refusal is never reported as
`NO_ACTIVE_ATTENTION`. `ReleaseCompatibility`'s `ruleset_public_id` and
`release_public_id` are left unset: both are format-checked against the
governed identifier shapes, and minting one would make the candidate
indistinguishable from a registered artifact everywhere the field is printed.

**56 cases in three partitions, derived from different parts of the
evidence.**

| partition | count | derived from |
| --- | --- | --- |
| `DEVELOPMENT` | 23 | the single-axis tables the rules encode |
| `INTERNAL_HOLDOUT` | 20 | the joint two-gene table no rule encodes |
| `EXPERT_HOLDOUT` | 13 | the refusal surface, sealed and not evaluated |

43 evaluated, 43 passed, 0 separation issues, 0 expert payloads read, access
chain intact. The access ledger records that the expert partition was listed
and never opened, so that claim can be checked rather than believed.

**What this does not establish.** One process authored the rules, the cases
and the expected answers. No partition here is independent of the build it
tests, and a passing separation audit says the partitions do not leak into
each other — not that any of them is independent evidence. The catalogue says
this in its own artifact, because a clean separation audit is exactly what
somebody would otherwise quote as independence. An external expert should
bring their own cases: a catalogue this project wrote cannot tell this project
what it failed to think of.

## 8. Operational residuals (workstream I)

Nine residuals, each re-measured in this wave rather than carried forward.
Seven are blocked on network egress neither environment has.

`uv lock --offline` was attempted and reported no solution — "Because alembic
was not found in the cache and your project depends on alembic>=1.13.1,<2.0" —
with an empty uv cache. That blocks the lockfile, and the lockfile blocks the
rest: CI installs with `uv sync --frozen`, so **the lockfile is the linter
pin**, and narrowing the `ruff` and `mypy` ranges in `pyproject.toml` would
look like a repair while leaving the gate exactly as non-reproducible. Every
`uses:` line in the workflow still carries an all-zero SHA marked
`UNRESOLVED`, which only `api.github.com` can resolve.

Two residuals are observed and not repaired: a working-copy `.venv` pointing
at a missing `python3.14`, and the two zero-byte git lock files that cannot be
unlinked from this shell — which is why this wave's commits were made with an
explicit index file and by writing `.git/refs/heads/main` directly. The
commits themselves are ordinary; only the mechanism was unusual.

## 9. A blocker this wave caused and cannot fix

Wave 3 added 92 test functions in three new modules. That legitimately
invalidated WP-19's verification artifacts, and the guards that detect it are
now failing — correctly.

`data/verification/wp19-test-inventory.json` records 7,461 discovered tests
across 274 suites with zero load failures, produced on a host where everything
imported. A fresh build was run on this host and **compared rather than
assumed about**: 7,481 discovered, 275 suites, and **two load failures** —
`tests.unit.expert_review.test_persistence` and
`tests.unit.security.test_persistence`, both `ImportError` on the absent
`sqlalchemy`. Committing that would record two import failures that do not
exist on a properly provisioned host.

The cloud container has the missing dependencies, but WP-19 records are
host-fingerprinted by design — an attestation does not travel — so a
cloud-produced record is correctly rejected here. Neither environment can
produce an honest replacement.

So the artifacts were left alone and the failing guards were left failing:

- `tests/unit/ths6/test_gates_and_dod.py::test_the_stale_test_count_disagreement_is_resolved`
- four staleness and reproducibility checks in `tests/unit/verification/`

Editing either the artifacts or the guards would have made the red disappear
without making the statement true. The guards are doing their job; what they
are reporting is real, and it is recorded as `OR-10` rather than silenced.

A separate group of failures on this host is environmental and predates this
wave: eight `deployment` errors, one `api` error, two `test_persistence`
import errors and the `wp16-real-gate-status.json` staleness all trace to
`sqlalchemy` and the API extras being absent from the device VM. Regenerating
`wp16-real-gate-status.json` here would flip `api_dependencies_available` from
true to false, which is a fact about this host and not about the repository.

## 10. What Wave 3 deliberately did not do

- did not begin WP-C14A, WP-C14, WP-C12's final external evaluation, WP-C14B
  or WP-C15;
- did not fabricate an expert identity, credential, comment, score, signature,
  approval or review date, and did not touch `pgx.expert_review` at all;
- did not populate an external-human approver or signature field, and did not
  redefine `APPROVED`;
- did not force any THS-6 gate to `PASS`, or write to the gate matrix;
- did not modify `config/scientific-sources.json`;
- did not widen `AcquisitionMode` or `SnapshotKind`;
- did not hand-author a lock, substitute a build backend, create a remote, or
  call a localhost process staging;
- did not weaken a single existing guard. Three failed during this wave — the
  freeze's completeness check, the visibility type's refusal to relabel a
  development case as a holdout, and Wave 2's own empty-ledger assertion — and
  each was answered by fixing the artifact or by replacing an assertion that
  had become false, never by loosening the check.
