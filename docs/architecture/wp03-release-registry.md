# WP-03 - Version Registry, Release Bundle, and Rollback

| Field | Value |
|---|---|
| Document ID | `DOC-ARCH-003` |
| Work package | WP-03 - Version Registry, Release Bundle, and Rollback |
| Migration revision | `0002_wp03_release_registry` (parent `0001_wp02_foundation`, single head) |
| Companion documents | `docs/architecture/wp02-domain-and-db.md`, `docs/ths6/wp03-release-evidence.md` |
| Architecture source | `architecture.md` sections 6.2, 6.3, 7.1, 7.2, 17 (WP-03) |

> **Nothing here is scientific content.** WP-03 builds the machinery that lets a
> result name exactly what produced it. It creates no dataset, no ruleset, no
> validated rule and no assessment.
>
> **WP-00 approval remains BLOCKED** (`DRAFT / AWAITING HUMAN AND SCIENTIFIC
> REVIEW`), **WP-01's Git checkpoint remains BLOCKED**, and WP-02's
> toolchain-dependent criteria remain BLOCKED. WP-03 changed none of them and
> does not resolve any of them.

---

## 1. The question this work package answers

*Which exact software, data and rules produced this result?*

Without a version registry the honest answer is "whatever was deployed at the
time", which is not an answer. A release binds three identities into one, and
every assessment records that one identity. When the active release later
changes - forward or back - the assessment still names what it actually used.

That is the whole point, and it drives every design decision below.

## 2. Scope and non-goals

**In scope**

- `SoftwareVersion`, `RulesetVersion` membership, a typed `ReleaseBundle`, the
  `ActiveRelease` pointer, and `AuditEvent`;
- the deterministic release manifest and its JSON Schema;
- migration `0002`: six tables, a seeded singleton row, an append-only trigger;
- typed ports and SQLAlchemy repositories for all six;
- `ReleaseService`: validate, activate, roll back, history;
- `pgx-release`, a machine-readable CLI;
- the WP-01 legacy seed registered as a **RETIRED, comparison-only** baseline.

**Explicitly out of scope** - each belongs to a later work package, and building
it now would imply a capability that does not exist:

| Deferred | Owner |
|---|---|
| Building real datasets and rulesets | WP-06, WP-11 |
| Converting legacy rows into validated rules | WP-09 to WP-11 |
| The assessment engine and assessment persistence | WP-12 to WP-14 |
| FastAPI, web UI, authentication | WP-16, WP-17, WP-23 |
| ClinPGx acquisition | WP-04 |

## 3. Domain model

| Entity | Identity | Key invariant |
|---|---|---|
| `SoftwareVersion` | `SoftwareVersionId` | `source_tree_hash` is what distinguishes two builds; the declared version string is not unique |
| `RulesetVersion` | `RulesetVersionId` | Membership is explicit, deterministically ordered and duplicate-free; a `FROZEN` ruleset is non-empty and approved |
| `ReleaseBundle` | `ReleaseBundleId` | Pins all three versions **by identity**; carries an immutable manifest and its digest |
| `ActiveRelease` | singleton | One row; monotonic `generation`; `release_id` is `None` before the first activation |
| `AuditEvent` | `AuditEventId` | Append-only; a pointer event names the release it moved to |

### 3.1 Software is pinned by identity, not by a string

WP-02 held `ReleaseBundle.software_version` as free text. Two builds declaring
`0.3.0` were indistinguishable, and nothing joined a release to a registered
build. It is now `software_version_id`, and the registry row carries the source
commit and source tree hash that actually tell two builds apart.

### 3.2 Ruleset membership is the pin

A ruleset that named its rules indirectly - "whatever is `VALIDATED` today" -
could not pin anything, because the set it denotes changes underneath the
release that cited it. `RulesetVersion.rule_ids` is an explicit tuple, fixed at
construction, sorted by UUID string so two processes selecting the same rules
produce the same manifest, and rejected outright if it contains a duplicate.

### 3.3 The pointer is a value, not a mutable cell

`ActiveRelease` is frozen like every other domain object. Moving it means
constructing the next value with `moved_to()`, which increments the generation.
Nothing mutates a pointer in place, so there is no state a half-finished
activation could leave behind.

## 4. The release manifest

`schemas/release-manifest.schema.json` is the published contract;
`pgx/domain/release_manifest.py` builds and checks it.

```json
{
  "schema_version": "pgx-release-manifest/1",
  "release":  {"public_id": "PGX-REL-YYYYMMDD-NNN"},
  "software": {"id", "version", "source_commit", "source_tree_hash", "manifest_hash"},
  "dataset":  {"id", "public_id", "status", "manifest_hash"},
  "ruleset":  {"id", "public_id", "status", "manifest_hash", "member_count", "rule_ids"}
}
```

Three properties carry the weight, and each is enforced rather than assumed:

| Property | How |
|---|---|
| The clock never leaks in | `build_release_manifest` reads no time source. A test parses the module's AST and fails on any `now`/`utcnow`/`today`/`time` attribute. |
| Key order is irrelevant | Hashing goes through `pgx.domain.hashing.sha256_digest`, which sorts keys. |
| The payload cannot be edited after hashing | `freeze_json` returns a deeply immutable structure; `ReleaseBundle` re-freezes on load. |

Array order *is* significant, which is why membership is sorted by the domain
before it reaches the manifest: the ordering is a property of the ruleset, not
of whoever queried it.

`validate_release_manifest` returns **every** problem rather than raising on the
first, because an operator repairing a manifest wants the list. It is written
against the schema using only the standard library: there is no reachable
package index here, and a validator that could not run offline would never run.

## 5. The fourteen compatibility rules

Checked together, all failures collected, before anything is mutated.

| # | Rule | Code |
|---|---|---|
| 1 | The software build is registered | `SOFTWARE_VERSION_NOT_REGISTERED` |
| 2 | The dataset is `PUBLISHED` | `DATASET_NOT_PUBLISHED` |
| 3 | The dataset hash matches what the manifest pinned | `DATASET_MANIFEST_HASH_MISMATCH` |
| 4 | The ruleset is `FROZEN` | `RULESET_NOT_FROZEN` |
| 5 | The ruleset hash matches what the manifest pinned | `RULESET_MANIFEST_HASH_MISMATCH` |
| 6 | Membership is non-empty | `RULESET_MEMBERSHIP_EMPTY` |
| 7 | Every member is `VALIDATED` | `RULE_NOT_VALIDATED` |
| 8 | Every member cites evidence | `RULE_EVIDENCE_MISSING` |
| 9 | Cited evidence lies inside the pinned dataset | `EVIDENCE_OUTSIDE_DATASET` |
| 10 | The evidence source is `release_eligible` | `EVIDENCE_SOURCE_NOT_RELEASE_ELIGIBLE` |
| 11 | An `INTERNAL_SYSTEM` source cannot back a release | `EVIDENCE_SOURCE_IS_INTERNAL_SYSTEM` |
| 12 | The manifest is valid and matches its recorded digest | `RELEASE_MANIFEST_INVALID`, `RELEASE_MANIFEST_HASH_MISMATCH` |
| 13 | The release is not `RETIRED` | `RELEASE_RETIRED` |
| 14 | WP-00 governance is unchanged; `PILOT` is still disabled | `OPERATION_MODE_NOT_PERMITTED`, `CLAIM_BOUNDARY_NOT_APPROVED` |

Rules 12 and 14 deserve a note. **12** recomputes the digest rather than
trusting the stored one, which is what catches a row whose hash column was
edited out of band. **14** is a governance check, not a data check: if `PILOT`
were ever enabled, activating a release would put a forbidden mode into service,
so activation refuses.

On any failure: the pointer does not move, the generation does not advance, no
status changes, no audit event is written, and nothing is committed.

## 6. Activation and rollback

### 6.1 Activation

1. lock the singleton pointer row (`SELECT ... FOR UPDATE`);
2. load the candidate;
3. run all fourteen rules;
4. recompute the manifest digest and compare;
5. determine the previous active release;
6. mark the candidate `ACTIVE`;
7. mark the previous release `ROLLED_BACK`;
8. move the pointer, incrementing the generation;
9. append exactly one audit event;
10. commit.

The order is the guarantee: every check precedes every mutation, so a rejection
has nothing to undo.

Re-activating the release that is already active is an **idempotent no-op** -
`changed=False`, no generation bump, no second audit event. Deploy scripts
re-run; treating that as an error would make them fail for being run twice.

### 6.2 Rollback

Rollback is narrower than activation, deliberately:

- the target must appear in the **audit history** as having actually been
  active. "Roll back" to something that never ran is an activation wearing the
  wrong name, and would reach a never-validated release through a path with
  softer expectations;
- a `RETIRED` release is refused - retirement is terminal;
- **compatibility is re-checked in full.** A release valid a month ago may not
  be valid now (a source can lose its release eligibility), and returning to it
  blindly would reinstate exactly the state the checks exist to prevent;
- the generation **advances**; it does not rewind. A rollback is a new event in
  history, not an erasure of an old one.

Nothing is rewritten: datasets, rulesets, rules, manifests, digests and past
assessments are untouched. Only the pointer, two status fields and one new audit
event change.

`ROLLED_BACK -> ACTIVE` is reachable only through `rollback_release`.

## 7. Concurrency

Two mechanisms, and they answer different questions.

**The row lock** (`get_for_update`) makes a second activation *wait*. It works
because the pointer is a genuine singleton: `ck_active_release_singleton` pins
the primary key to one value, so every activation locks the same row. Without
that constraint two pointers could exist, each activation would lock a
different one, and nothing would be locked at all.

**The generation guard** makes a lost update *detectable*. `update()` writes
only if the pointer is still at the generation the caller read. Locking alone
would suffice on PostgreSQL; the counter is kept so the failure is loud rather
than silent, and so the same contract could be honoured by a store with weaker
locking.

The offline suite proves the guard. Only a real server proves the lock - see
the evidence document.

## 8. Audit

Append-only, enforced in three places on purpose:

| Layer | Mechanism |
|---|---|
| Port | `AuditEventRepository` declares `append`, `list_for_object`, `list_recent` - and nothing else |
| Repository | `SqlAlchemyAuditEventRepository` implements no update and no delete |
| Database | `trg_audit_events_append_only` raises on `UPDATE` and `DELETE` |

The first two are application promises. Only the third survives someone with a
`psql` prompt.

## 9. Schema (migration 0002)

| Table | Notable constraints |
|---|---|
| `software_versions` | `source_tree_hash` unique; both digests format-checked |
| `ruleset_versions` | public-ID format; `VALIDATED`/`FROZEN` require approval metadata |
| `ruleset_rules` | composite PK forbids duplicate membership; `CASCADE` from the ruleset, `RESTRICT` from the rule |
| `release_bundles` | all three FKs `RESTRICT`; activation metadata must match status |
| `active_release` | `singleton_id = 1`; `generation >= 0`; a moved pointer names a release |
| `audit_events` | closed action vocabulary; a pointer event names `new_release_id`; append-only trigger |

`ruleset_rules` has asymmetric `ondelete` for a reason: deleting a ruleset takes
its membership rows with it (they describe that ruleset and mean nothing
without it), while deleting a *rule* a ruleset pins is refused - a released
ruleset that silently loses a member is precisely the drift this registry
exists to prevent.

The singleton row is inserted **by the migration**. Creating it lazily on first
activation would mean two concurrent first activations each found nothing to
lock, both inserted, and the singleton became one only after the race it was
meant to prevent.

`downgrade()` drops the trigger *and* its function - a leftover function makes
the next upgrade fail on `CREATE FUNCTION` - then the six tables children-first.
It touches nothing from `0001`.

## 10. The legacy baseline

The WP-01 legacy seed is registered as a reference, never an operational
release:

| Record | Status | Contents |
|---|---|---|
| Dataset | `RETIRED` | The WP-01 manifest hash. Never `PUBLISHED`. |
| Ruleset | `RETIRED` | **Empty membership.** Never `FROZEN`. |
| Release | `RETIRED` | Pins the two, carries the limitation in `notes`. |

No legacy row is read, converted or imported. The activation checks refuse it
four times over (`RELEASE_RETIRED`, `DATASET_NOT_PUBLISHED`,
`RULESET_NOT_FROZEN`, `RULESET_MEMBERSHIP_EMPTY`), and rollback refuses it as
`RETIRED`. Registration is idempotent by public identifier, so it is safe in a
deploy script.

The approval fields name the registration process and say in the value itself
that it is **not** a scientific approval.

## 11. CLI

`pgx-release` (`pgx.application.release_cli:main`; `scripts/release.py` is a
thin wrapper).

| Subcommand | Mutates | Exit codes |
|---|---|---|
| `show-active`, `inspect`, `history` | no | 0 |
| `validate` | no | 0 compatible, 1 not |
| `activate`, `rollback` | yes | 0, 1, 3, 4 |
| `register-legacy-baseline` | yes | 0 |

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | not activatable, or a rollback refused |
| 2 | configuration failure |
| 3 | release not found |
| 4 | the pointer moved during the operation |

`--actor` and `--reason` are required on everything that mutates. The database
URL comes from the environment and is never an argument - a URL in `argv` lands
in the shell history and the process list. All failure text passes through
`config.sanitize_message` first.

The CLI contains no compatibility logic; a test asserts it, because a CLI that
re-implemented a rule would eventually disagree with the service, and the
disagreement would surface as a release that validated on the command line and
failed in production.

## 12. What WP-03 does not prove

| Claim | Status |
|---|---|
| The compatibility rules, activation sequencing, rollback contract, audit shape | **Proven offline** - in-memory unit of work, 179 new tests |
| Schema validity, constraint behaviour, the append-only trigger, row locking | **Proven on real PostgreSQL 16.13 via rendered SQL** - supplementary, see the evidence document |
| Alembic `upgrade`/`downgrade`, revision chain, `alembic_version` stamping | **BLOCKED** - Alembic is not installable here |
| The SQLAlchemy repositories and `SqlAlchemyUnitOfWork` against a database | **BLOCKED** - psycopg is not installable here |
| The service holding a real row lock across a real transaction | **BLOCKED** - needs the driver |

The in-memory unit of work models rollback and the generation guard faithfully.
It does **not** model row locking, and no test here claims otherwise.

## 13. Handed to WP-04 and later

- dataset and ruleset *construction* (WP-06, WP-11) - WP-03 only pins them;
- promoting rules to `VALIDATED` (WP-10, WP-11);
- assessment persistence, which will reference `release_bundles.id` (WP-14);
- the `PGX-*` sequence allocator - WP-03 uses fixed identifiers in fixtures and
  reserves `-999` for the legacy baseline.
