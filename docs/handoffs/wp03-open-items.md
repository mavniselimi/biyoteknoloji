# WP-03 open items

| Field | Value |
|---|---|
| Document ID | `DOC-HANDOFF-003` |
| Source | Adversarial review of the WP-03 delivery |
| Status | **OPEN — recorded, not fixed** |
| Owner | A future corrective pass, before WP-03 can be called complete |

> **This file is a register, not a plan of record.** Nothing here was fixed in
> WP-04, and nothing here may be assumed fixed. Each item states what is wrong
> today, what a reader might wrongly conclude from the current code, and what
> "fixed" would have to mean. WP-04 was built on top of WP-03 as it actually
> is, and takes no dependency on any of these being resolved.

---

## 1. Claim-boundary approval activation gate

**Today.** `ReleaseService._check_claim_boundary` checks that `PILOT` is not
enabled and that at least one mode is. It does **not** check
`P0_CLAIM_BOUNDARY.is_approved`, which is `False` and will stay `False` until a
human and scientific reviewer sign WP-00 off.

**What a reader could wrongly conclude.** That rule 14 gates activation on WP-00
approval. It does not. A release can be activated today, with the claim boundary
still in `DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW`.

**What fixing it means.** Deciding — explicitly, with the reviewer — whether
activation requires approval, and if so adding an `is_approved` gate with a
distinct compatibility code, plus a documented escape for demo and validation
work that must run before approval exists. This is a governance decision, not a
code change, which is why it was not made unilaterally.

## 2. Manifest-to-registry exact binding

**Today.** Compatibility rules 3 and 5 compare the *manifest hash* the release
pinned against the stored dataset and ruleset hashes. They do **not** compare
the pinned **identities** (`dataset.id`, `ruleset.id`, `software.id`) in the
manifest against `release.dataset_version_id`, `release.ruleset_version_id` and
`release.software_version_id`.

**What a reader could wrongly conclude.** That the manifest and the release row
are proven to describe the same three records. They are not. A release whose
manifest names dataset A while its foreign key points at dataset B would pass if
both datasets happened to share a manifest hash, and the manifest's software
section is not cross-checked at all.

**What fixing it means.** Adding identity equality checks for all three pinned
records, with their own compatibility codes, and a test per record that mutates
one identity and asserts the rejection.

## 3. Manual JSON Schema validator parity

**Today.** `schemas/release-manifest.schema.json` is the published contract;
`validate_release_manifest` is a hand-written standard-library check. They are
maintained separately. `TestTheJsonSchemaMatchesTheValidator` compares required
keys, property names, `additionalProperties` and the digest pattern — but it
does not compare `enum` values, `minLength`, `minimum`, `uniqueItems` or
`format`.

**What a reader could wrongly conclude.** That passing the validator is
equivalent to passing the schema. It is not. A manifest with
`dataset.status: "INVENTED"` satisfies the validator (which only requires a
non-empty string) and violates the schema's `enum`.

**What fixing it means.** Either driving the validator from the schema document
itself, or extending the parity test to every constraint keyword the schema
uses. The offline constraint stands: no JSON Schema library is installable here,
so the validator has to stay standard-library.

## 4. Legacy baseline drift detection

**Today.** `register_legacy_baseline` reads and hashes the WP-01 manifest at
registration time and stores that digest. Nothing re-checks it afterwards. If
the WP-01 manifest is later amended, the registered baseline silently continues
to claim a digest that no longer matches the file.

**What a reader could wrongly conclude.** That the registered baseline tracks
the WP-01 manifest. It records a digest once; it does not watch it.

**What fixing it means.** A verification path — a CLI subcommand, or a check
inside `validate_run` — that recomputes `wp01_manifest_hash()` and reports a
mismatch against the stored value, plus a test that amends a copy of the
manifest and asserts the mismatch is reported.

## 5. Active-release no-op revalidation

**Today.** `activate_release` returns the idempotent no-op **before** running
the compatibility checks, deliberately, so that re-running a deploy step cannot
fail because the world moved on. The consequence is that re-activating the
currently active release never revalidates it. If the release became
incompatible after activation — a source lost its release eligibility, a
dataset was retired — the no-op reports success and says nothing.

**What a reader could wrongly conclude.** That a successful `activate` implies
the release is compatible *now*. For the no-op path it implies only that the
release is the one currently active.

**What fixing it means.** Deciding what the operator actually wants: either run
the checks and return `changed=False` alongside a compatibility report, or add a
separate `revalidate-active` operation. Either way the no-op must keep not
writing a second audit event.

## 6. Store-independent stale-generation error

**Today.** `SqlAlchemyActiveReleaseRepository.update` raises
`StaleActiveReleaseError`, which is defined in
`pgx/infrastructure/db/repositories.py`. The in-memory fake raises its own
`FakeStaleGenerationError`. `ReleaseService` declares a
`StaleActivationError` but nothing raises it: the service does not catch either
store-specific error and translate it.

**What a reader could wrongly conclude.** That a caller can catch one exception
type for "the pointer moved". They cannot — the type depends on which store is
underneath, which is exactly the coupling ports exist to prevent. The CLI papers
over it by catching both.

**What fixing it means.** Defining the stale-generation error in the domain or
application layer, having every `ActiveReleaseRepository` implementation raise
it (or having the service translate at the boundary), and a test asserting the
fake and the SQLAlchemy repository raise the same type.

---

## Not affected by these items

For the avoidance of doubt, the following WP-03 properties were verified and are
independent of everything above: manifest determinism, the append-only audit
trail (port, repository and database trigger), rollback restricted to
previously-active releases, immutable artifacts surviving rollback, the legacy
baseline being non-activatable, and the singleton pointer's constraints and row
locking on real PostgreSQL.

WP-03's external blockers — Alembic, psycopg, the PostgreSQL repository
integration and the Docker daemon — are recorded in
`docs/ths6/wp03-release-evidence.md` and are **not** duplicated here. They are
environment limitations, not defects in the code.
