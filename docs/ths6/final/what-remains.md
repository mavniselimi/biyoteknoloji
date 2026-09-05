# What remains

Everything below is work no code in this repository can do. It is ordered by
dependency: nothing in a later section can start until the earlier ones are
done.

## 1. Scientific approval (Gate A) — scientific source approver, data owner

- Review each of the 20 registered sources against
  `docs/scientific/source-review-checklist.md` and record an approval decision
  per source. Zero are approved today.
- Re-ingest under a **new dataset identifier**. The current snapshot is
  `QUARANTINED`, and `SnapshotState` has no transition out of quarantine — a
  quarantined snapshot is superseded, not promoted. `PGX-DATA-20260830-900`
  cannot become `SEALED`.
- Build and publish a canonical dataset from the sealed snapshot, moving its
  lifecycle state out of `BUILDING`.
- Approve the evidence build for rule construction, clearing the
  `NOT_CURATED` and `NOT_PUBLICATION_ELIGIBLE` labels.

## 2. Curation and rules (Gate B) — expert reviewer, curation lead

- Approve `docs/scientific/curation-protocol-v1.md`. Its status is
  `AWAITING_EXPERT_REVIEW`; nothing downstream can begin without it.
- Complete the inter-curator exercises; only templates exist today.
- Curate interpretations under the approved protocol. Zero exist.
- Author, review and approve rules with complete approval envelopes, then
  validate and freeze a ruleset and register it as executable.
- Resolve the 33 unlinked legacy rule candidates — link each to a governed
  work item or record why it is not a rule candidate.

## 3. Assessment, coverage and safety (Gate C) — curation lead, platform owner, clinical safety authority, release approver

- Create an active release binding a software version, a dataset version and a
  ruleset version.
- Compute at least one assessment from governed content, and a report from it.
- Execute a coverage manifest over governed content producing at least one
  supported axis.
- Run the safety gate under a CI provider. `.github/workflows/safety-gate.yml`
  exists and has never been executed by one.
- **Approve the claim boundary.** A named clinical safety authority must sign
  off on what the system may state and the wording of each refusal. Six
  prohibited claim surfaces are declared and the scanner has four known gaps.

## 4. Validation and expert review (Gate D) — validation owner, expert review chair

- Design a validation case architecture. `real_patient_case_count` is
  *structurally* zero: the current case model refuses real-patient, genotype
  and raw-sequencing fields at any depth, so authoring more cases in it cannot
  reach the target.
- Author at least 50 serious validation cases; the architecture asks for 100 or more.
- Build an independent holdout set and demonstrate, via the separation audit,
  that no case in it influenced rule development. The audit currently runs
  over seven development cases, which is a check with nothing to separate.
- Execute a benchmark against the active release so at least one of the
  fifteen metric definitions has a computed value.
- Obtain a signatory for the expert protocol; name at least one reviewer;
  complete at least one blind-first review, performed through the interactive
  workflow rather than a static report.

## 5. Security, audit and deployment (Gate E) — security owner, platform owner

- Provision a PostgreSQL server; install `argon2-cffi`; apply migration 0011.
- Exercise authentication, sessions, CSRF and RBAC against a real store and
  verify the audit chain.
- Execute a backup and a restore, and satisfy all four verification
  conditions. `pg_restore` exiting zero satisfies none of them.
- Resolve the CI action pins to commit digests (`scripts/resolve_action_pins.sh`)
  and produce a lockfile.
- Build a container image; deploy a staging environment with real ingress and
  a real certificate; observe its health endpoints answering.
- Execute the reliability drills and the rollback drill.
- Run the configured CI workflows on a provider at least once.

## 6. Aggregate and demonstration (Gate F) — release approver, verification owner, programme owner

- Regenerate WP-19's verification run so the recorded evidence is fresh; it is
  currently rejected as stale, and its recorded discovery count predates
  WP-20 through WP-25.
- Populate the validation dashboard so it renders metrics rather than an
  empty state.
- Execute the representative demonstration end to end, offline, with the model
  off and every P1 feature off.
- Satisfy every required release gate so `release_may_proceed` becomes true.

## 7. Human sign-off — nine roles

All nine roles in [`human-signoff.md`](human-signoff.md) must sign. There is
no mechanism in this repository to record a signature, and there should not
be.

## Two documents to fix

- WP-17's gate status must be reconciled with its own published schema:
  either the producer stops emitting `"CAPTURED"` or the schema admits it.
  Whichever way, the tests must be updated with it.
  **Done in WP-C00 A.6:** the producer stopped emitting `"CAPTURED"`. The two
  spellings were replaced by one constant that the producer, the schema and the
  tests all read, and the committed artifact is now validated against the
  committed schema on every test run.
- `architecture.md`'s Definition of Done count and the WP-25 prose must agree
  on fifteen.

## What is genuinely finished

The software. Twenty-five work packages, 7,000+ tests, 20 published schemas
for WP-25 alone, a complete governance model that refuses to compute from
unapproved content, and a safety layer whose twelve invariants and
thirty-seven negative controls all fire correctly.

None of that is THS 6, and this pack exists to say so precisely.
