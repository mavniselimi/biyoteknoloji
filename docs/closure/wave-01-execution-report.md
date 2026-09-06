# Execution Wave 1 — report

Baseline freeze, governance launch, source research, runtime closure.
Work packages **WP-C00**, **WP-C01**, **WP-C03**, **WP-C04**. No later
closure work package was started.

Machine-readable companion: `data/closure/wave-01-execution-manifest.json`.

**THS-6 is not achieved and no gate passes.** That is the honest result of
this wave and it is what the artifacts say.

## What this wave changed, in one paragraph

The repository had no commit; it now has a baseline commit, a tag and a
recorded identity. Thirty-three legacy rule candidates were unlinked with no
stated reason; each now carries exactly one disposition and a named next
action. Four decisions that only people can make were scattered across code
comments and prose; they are now four review packages with evidence tables,
proposed decisions and blank approval forms. Eight scientific sources were
read against their own primary documents, and what was found includes two
licence conflicts and five places where the sources do not fit the scope this
project has described. The platform's migrations ran against a real
PostgreSQL server, the ASGI runtime was executed rather than assumed, and the
full verification profile was run once and passes.

## Two environments, and why it matters

Everything below was produced in one of two places, and the report says which,
because several artifacts are only true of the machine that made them.

| | The repository host | The development container |
| --- | --- | --- |
| What it is | the Linux VM this session reaches the repository through | an ephemeral cloud container holding a byte-identical copy |
| Python | 3.10.12, aarch64 | 3.11.15, x86_64 |
| Network | none | package index unreachable; some hosts reachable |
| FastAPI, SQLAlchemy, Alembic | absent | present |
| PostgreSQL | absent | server 16.13 present, no Python driver |
| Long commands | capped at 120 s | uncapped |

Neither is the maintainer's own machine. The trees were compared file by file
before any run: 1,430 files, and after reconciling four that had drifted, the
only difference left was a `.DS_Store`. Where an artifact depends on the
environment, it was produced in the container, because that is the one with
the dependencies the committed artifacts were originally built with — the
repository host would have degraded them, and did once before this was
noticed. `data/api/wp16-real-gate-status.json` regenerated on the repository
host reported `api_dependencies_available: false` and null versions for every
package. That is a true statement about a machine with no dependencies and a
false one about this project.

## WP-C00 — baseline freeze

**Baseline commit** `f95b467320b9dcab787b4abed76544ffc7ef3641`, tree
`39581eab87e4c75f4a70e4cbab88294ab0139d76`, tag
`baseline/pre-closure-v0.2.0.dev0`, 1,370 files, branch `main`, no remote.
The commit was built from an explicit 1,370-entry pathspec — never
`git add .` — and the staged set was scanned for secrets (clean, 0 findings,
31 classified) and probed for absolute paths before it was written.

### The 33 unlinked legacy candidates

All 33 are dispositioned, each exactly once, in
`data/closure/wp-c00-legacy-candidate-dispositions.json`:

| Disposition | Count |
| --- | ---: |
| `MECHANICALLY_LINKABLE` | 0 |
| `MALFORMED_OR_UNRESOLVABLE_MIGRATION_RECORD` | 0 |
| `DUPLICATE_OR_SUPERSEDED_MIGRATION_ITEM` | 0 |
| `OUTSIDE_FIRST_RELEASE_SCOPE` | 20 |
| `MISSING_EVIDENCE_REQUIRES_CURATOR` | 13 |

The reason none is linkable was measured rather than assumed. Every one of
the 1,526 linked proposals names an upstream ClinPGx accession in its
subject; **none of the 33 does**. Twenty-two sit on legacy CSV rows whose
`annotation_id` column is empty and whose `source_container` is the old
project's own manual normalization; eleven are entries of a hand-written
effect-hint dictionary. There is no identifier to look up, and attaching them
to the nearest record with a matching gene and drug is the "plausible
neighbour" the WP-10 migration already refused to guess.

Nothing is malformed: all 33 origin pointers resolve and all 33 origin files
still match the content hash the migration recorded. `OUTSIDE_FIRST_RELEASE_SCOPE`
is a scope decision, not a scientific rejection; those 20 keep every blocker
they had.

**An earlier reading was wrong and was corrected before anything was
written.** A first pass mapped legacy CSV rows one line off and appeared to
show ten candidates naming a resolvable accession, one of them pointing at a
record for a different gene and drug entirely. Re-deriving the row convention
against all 1,512 CSV-origin proposals showed the offset was mine. The
correct reading is the one above.

### The WP-17 vocabulary defect, repaired

WP-25 found `data/web/wp17-real-gate-status.json` recording
`screenshot_evidence_status: "CAPTURED"` while the schema WP-17 published in
the same run admitted only `"NONE"` and `"BROWSER_CAPTURED"`. Producer, tests
and schema had never been compared with each other, so it survived from WP-17
to WP-24.

Fixed at the level of the class rather than the instance. The vocabulary now
has one home, `apps.web.gate_status.SCREENSHOT_EVIDENCE_STATUSES`, read by
the producer, by the published schema and by the tests; and
`tests/unit/web/test_snapshots.py` now validates the committed artifact
against the committed schema on every run — the comparison nobody had been
making. `pgx-ths6 inventory` exits 0, no artifact is typed `INVALID`, and the
`THS6_EVIDENCE_INVALID` finding is retired. The WP-25 documents that recorded
the finding keep their original text and carry a dated resolution note, so
what WP-17 had at that time is still readable.

### The full verification profile, run once and passing

Run in the development container, recorded in
`data/verification/wp19-verification-run.json`:

| | |
| --- | ---: |
| discovered | **7,390** |
| executed | **7,390** |
| passed | **7,294** |
| failed | **0** |
| errored | **0** |
| skipped | **96** (unexplained: **0**) |
| outcome | **PASS** |

Every skip is classified. The 72 PostgreSQL integration skips are a declared
environment dependency — no Python driver could be installed — and the
category is reported `BLOCKED`, which is not a pass. The remaining 24 are
declared inverted or capability skips.

Reaching that took four earlier runs, and each one found something real:
two new test modules were uncategorised and the inventory refused to run
rather than count them silently; the committed inventory was stale by 66
tests; a WP-25 test pinned a test-count disagreement that this wave resolved;
one of this wave's own modules named a legacy seed file in a string constant
and tripped the legacy-isolation boundary. The counts above are from the run
after those were fixed, and none of the earlier numbers were carried forward.

`data/verification/wp19-real-gate-status.json` now reports execution
`PASS`, run evidence `VERIFIED`, ASGI runtime `PASS`, browser E2E `PASS`,
7,390 discovered — and `release_may_proceed: false`, with four honest
blockers: the claim boundary is unapproved, coverage was not measured,
PostgreSQL was not exercised, and the WP-20 safety gate does not pass.

## WP-C01 — runtime and database closure

### A real PostgreSQL, and what it did not prove

PostgreSQL 16.13 was initialised and started in the development container,
and all eleven migrations ran to head (`0011_wp23_auth_audit`). The
application configuration requires the `postgresql+psycopg` driver, which is
not installable in either environment, so the migrations were rendered with
`alembic upgrade head --sql` and executed by `psql`. The DDL is Alembic's own
and every statement ran; the rendered SQL is byte-identical under both
copies of the migration set, so this is not an artefact of one tree.

Measured: **64 tables** plus `alembic_version`, **816 columns**, 225 indexes,
344 check / 82 foreign-key / 65 primary-key / 69 unique constraints. All 44
tables the ORM metadata declares are present, and all 537 declared columns
are present. Full record in `data/closure/wp-c01-database-verification.json`.

**Finding: the ORM metadata describes two thirds of the schema.** Twenty
tables — WP-05 source policy, WP-06 raw snapshots, WP-07 canonicalization and
the WP-08 evidence store — exist only in hand-authored migrations, with no
ORM module anywhere in `pgx/infrastructure/db/`. Twenty-two further columns
were added to three mapped tables by later migrations without updating the
model. **`alembic revision --autogenerate` run against this schema would
propose dropping 20 tables and 22 columns.** `migrations/env.py` names this
exact hazard in its own comment and says WP-22's and WP-23's tables were
added to the metadata list because of it; WP-05 through WP-08 were not.
Reported, not repaired: writing twenty table definitions is new architecture.

Not verified, and listed rather than omitted: the application connecting
through SQLAlchemy, audit-chain persistence against a real database,
transaction paths through the unit of work, and any behaviour of the running
API against this database. All four need the driver.

### ASGI runtime verification, executed

`python -m apps.api.runtime_verification` ran in the development container
and all five required checks passed: the framework imports, the application
composes, the served OpenAPI document is identical to the committed artifact,
the liveness probe answers 200, and the ASGI suite ran 28 tests with 1 skip
and no failures.

The record is host-bound by design — the module fingerprints the interpreter,
architecture and package versions, on the stated principle that an
attestation must not travel. It is committed, and on the repository host it
is correctly rejected as `STALE_EVIDENCE_REJECTED`, so `asgi_runtime_tests_executed`
stays `false` there. It cannot manufacture a pass on a machine that did not
run it. To make it count locally, run that command there.

### `uv.lock` — not produced

Neither environment can reach a package index. A lock file records a
resolution; hand-writing one would be inventing the resolution it exists to
record. `BLOCKED_BY_EXTERNAL_ACCESS`.

## WP-C03 — governance checkpoints

Four review packages under `docs/closure/checkpoints/`, each with the same
seven files. Every row in every `proposed-decisions.csv` reads
`PENDING_REVIEW`, because those files record what the project proposed rather
than what was decided. A decision lives in the checkpoint's approval form,
and the producer will not overwrite a form a reviewer has filled in.

**One of the four has since been decided.** A pharmacist reviewed H01 and
returned an attestation, recorded in
`data/closure/h01-source-policy-decision.json` and in that checkpoint's
approval form, bound to the digests of the exact evidence table and proposed
decisions they read. H00, H02 and H03 remain undecided and their forms are
still blank. The H01 decision approves four sources for manual, private,
non-commercial review, citation and normalized internal derivation, and it
did **not** change `config/scientific-sources.json` — see below.

| Checkpoint | Decides | Blocks |
| --- | --- | --- |
| `H00-repository-identity` | is this the identity and baseline the project meant, and where may it be published | release versioning, any push |
| `H01-source-policy` | which sources may be used, on what terms | all acquisition, and everything downstream |
| `H02-curation-protocol` | how a source statement becomes a curated interpretation | every curated interpretation |
| `H03-claims-boundary` | what the platform is permitted to say | report issuance, the security gate |

## WP-C04 — source research

Eight of the twenty registered sources were read against primary documents —
licence files, providers' own terms, regulators' own labelling. No row rests
on a search-result snippet. Twelve were not researched because the first
release does not need them, and that is recorded as
`NOT_RESEARCHED_THIS_WAVE` rather than left looking like an absence of
findings. **No source moved out of `PENDING_REVIEW`.**

| Source | Licence as read | Proposal |
| --- | --- | --- |
| `cpic.database` | CC0-1.0 | approve, subject to named conditions |
| `cpic.api` | CC0-1.0 (content); service terms not found | approve, subject to named conditions |
| `cpic.publications` | UNKNOWN | research further |
| `clinpgx.website` | CC-BY-SA-4.0 **with a contradictory overlay** | escalate |
| `clinpgx.api` | UNKNOWN | escalate |
| `dpwg.knmp` | UNKNOWN — none published | escalate |
| `druglabel.fda` | CC0 for the API, UNKNOWN for the label text | escalate |
| `druglabel.titck` | UNKNOWN — unreachable | escalate |
| the other twelve | not researched | defer, outside first-release scope |

Four findings a reviewer should not have to dig for:

- **ClinPGx's statement contradicts itself.** It names CC-BY-SA-4.0 and, in
  the same statement, restricts use to research and forbids sale. CC-BY-SA
  permits commercial use and forbids adding restrictions. Both halves cannot
  be honoured, and choosing is not a maintainer's call.
- **The evidence build already in this repository was acquired through
  `clinpgx.api`**, whose terms nobody established. The question is
  retrospective as well as prospective.
- **DPWG publishes no terms at all.** Silence is not permission, and the
  structured form of the same recommendations is licensed commercially
  through the G-Standaard and forbids reproduction.
- **TITCK could not be reached.** Every attempt failed before any document
  was read — the robots policy itself returned a server error or timed out —
  so there is currently no robots-compliant automated route to the one
  regulator a Turkish deployment would be expected to carry.

### Five places the sources do not fit the declared scope

These go to H02 and are questions for the clinical reviewer, not decisions
this wave made.

1. **Amitriptyline is one two-gene decision, not two axes.** CPIC keys its
   amitriptyline recommendations by a CYP2D6 and CYP2C19 pair together. The
   declared scope names two independent axes.
2. **Clopidogrel depends on indication.** CPIC states different
   recommendations for acute coronary syndrome with PCI, for other
   cardiovascular indications, and for neurovascular ones. The scope has no
   indication axis.
3. **The five-phenotype vocabulary does not fit CYP2D6.** CPIC assigns no
   RAPID phenotype for CYP2D6, does emit Likely Poor, Likely Intermediate and
   Indeterminate, and keys recommendations by activity score.
4. **FDA labelling does not cover CYP2C19 with amitriptyline at all**, and
   only clopidogrel and codeine carry boxed-warning-strength language.
5. **The clopidogrel boxed warning no longer says "poor metabolizer"** — it
   is worded around carrying two loss-of-function CYP2C19 alleles. Any
   extraction keyed on the phenotype term will silently return nothing for
   the most important warning in the first release.

## What was found and left alone

- Three files under `docs/examples/wp04/` record a session-scoped cache path
  from the machine that produced them. They are recorded drill output with a
  content hash and a test reads them, so they were committed unmodified and
  the finding is carried in `H00`. The producer should scrub the field.
- One legacy WP-01 evidence file records an interpreter path inside a
  historical command string. Editing it would falsify a record.
- Seven absolute paths in tests are negative fixtures — the scanner's own
  test data — and are meant to be there.

## The H01 decision, and why the source registry did not move

The reviewer approved this project's H01 package. The registry demands
something stricter before any source may carry an approving status: a version
policy, a citation policy, a licence identifier, approved claim categories,
all ten reuse dimensions answered, and at least one official evidence
reference **this project retrieved itself** — "naming a URL is not reading the
document at it", in the validator's own words, and a verified reference must
carry the retrieval instant.

WP-C04 established what each source's terms say. It did not record, per
document, the retrieval instant and content hash the registry requires, and
those cannot be reconstructed after the fact without inventing them. The
reviewer also read the package rather than each source's own terms page, so
their name does not belong in a field meaning "the official evidence URLs
this reviewer read".

So the decision is recorded in full and the registry is untouched —
byte-for-byte identical, `pgx-source-policy validate` still reports 20
sources and **0 approved**, and WP-11 still blocks on
`SOURCE_POLICY_NOT_APPROVED`. That is the correct outcome rather than a
failure to apply the approval: writing an approving status into the registry
would make the repository assert provenance nobody has.

What each of the four approved sources still needs is listed per source in
the decision record under `registry_change.gaps`.

## What is still true

`ths6_achieved: false`. All six gates BLOCKED. Fourteen of fifteen Definition
of Done items unsatisfied. Nine of nine sign-off roles unsigned. The
representative demonstration has not been executed. The evidence pack is
intact — 54 members, integrity true, no absolute-path leak, no secret
finding — and it describes a blocked programme, which is what it should do.
