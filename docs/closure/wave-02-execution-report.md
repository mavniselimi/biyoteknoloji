# Execution Wave 2 — report

Controlled acquisition, dataset-quality closure, and operational proof.
Work packages **WP-C01 residuals**, **WP-C02**, **WP-C05**, **WP-C06**, and
the **H02** review package.

Machine-readable companion: `data/closure/wave-02-execution-manifest.json`.

**THS-6 is not achieved, no gate passes, no source became usable, no dataset
was acquired and no rule exists.** One human decision was recorded — on H01 —
and the section below explains why it did not, and should not, make anything
usable on its own.

## The one thing to read first

A pharmacist approved this project's source policy. That approval is recorded,
bound to the exact bytes he read, and it is real. It did **not** change
`config/scientific-sources.json`, and `pgx-source-policy validate` still
reports 20 sources and 0 approved.

That is not a failure to apply the approval. The registry's own validator
requires, before any source may carry an approving status: a version policy, a
citation policy, a licence identifier, approved claim categories, all ten
reuse dimensions answered, and at least one official evidence reference *this
project retrieved itself* — "naming a URL is not reading the document at it",
in the validator's own words, and a verified reference must carry the
retrieval instant.

WP-C04 established what each source's terms say. It did not record, per
document, the retrieval instant and content hash the registry requires, and
those cannot be reconstructed after the fact without inventing them. The
reviewer also read the package rather than each source's terms page, so his
name does not belong in a field meaning "the official evidence URLs this
reviewer read".

So two independent things both stop acquisition, and either alone would be
enough:

1. **The registry clears no source.** Governance integrity.
2. **Every approved mode is `MANUAL_DOWNLOAD`.** A person must do the
   retrieving. A script fetching one page is still automated acquisition, and
   automated acquisition is not approved for any of these sources.

Wave 2 therefore produced an acquisition matrix and a checklist for a person,
and acquired nothing.

## WP-C01 residuals and WP-C02 — what actually ran

Against a real PostgreSQL 16.13 server, all verified by result rather than by
exit status:

| Check | Result |
| --- | --- |
| migrations to head | `0011_wp23_auth_audit`, 65 tables |
| `UPDATE` on `audit_events` | refused by `trg_audit_events_append_only` |
| `DELETE` on `audit_events` | refused by the same trigger |
| blank actor insert | refused by `ck_audit_events_actor_not_blank` |
| unknown action insert | refused by `ck_audit_events_action_enum` |
| `RELEASE_ACTIVATED` with no release id | refused by the pointer constraint |
| `begin; insert; rollback` | 0 rows remained |
| `pg_dump` | 316,457 bytes, `sha256:ee7ea7d1…` |
| `pg_restore` into a fresh database | 65 tables, head intact, the audit row's actor and object id match |
| `DELETE` after restore | still refused — the trigger survived |

The last line is the one worth keeping: a backup that restores the rows but
loses the constraint that made them trustworthy is not a restored database.

**A finding, reported and not fixed.** `pyproject.toml` allows
`ruff>=0.4.0,<1.0` and `mypy>=1.9,<2.0`, and no lock file pins which version
CI installs. With ruff 0.15.11 the lint job reports 9,791 findings and the
format job would reformat 690 of 790 files; with mypy 1.20.2 the type job
reports 1,304 errors in 213 of 387 files. Both counts are version-sensitive,
because newer releases add rules inside families the project already selects.
**The finding is the unpinned range, not the count** — CI's result is not
reproducible while the linter floats and nothing pins it. Reformatting 690
files is a large unreviewed change and was not made.

### Blocked, with the exact command and result

| Item | Command | Observed |
| --- | --- | --- |
| `uv.lock` | `uv lock --no-cache` | alembic not found; PyPI `403 Forbidden` |
| wheel / sdist | `uv build` | hatchling not found; PyPI `403` |
| CI action pins | `scripts/resolve_action_pins.sh` | `api.github.com` `403`; the script refused to write a partially pinned workflow |
| container, SBOM, vuln scan | `docker info` | no daemon; syft, grype, trivy, cosign all absent |
| app → PostgreSQL | `pip download psycopg` | no matching distribution |
| staging / TLS | none | no authorized destination |

setuptools was **not** substituted for hatchling. A different backend produces
a different artifact, and it would not be this project's wheel.

## WP-C05 — the acquisition that did not happen

`data/closure/wp-c05-acquisition-plan.json` derives a matrix from the recorded
H01 decision, and the producer refuses to be broader than it: every source in
the plan must appear in the approved set and every mode must appear in that
source's permitted list.

Four sources, one permitted mode each — `MANUAL_DOWNLOAD` — with internal
derivation permitted for two of them. `OFFICIAL_API` is prohibited for all
four. `docs/closure/wp-c05-manual-acquisition-checklist.md` is what an
operator works through: entry point, version to record, what may be kept
locally, where it goes, and the URL / UTC instant / SHA-256 to capture.

No dataset id was allocated. No snapshot was sealed. The quarantined legacy
dataset was not reused, relabelled or copied.

## WP-C06 — audited first, then implemented

The mechanism was **not** missing. WP-07 has carried the transition since it
was written: `BUILDING -> QUALITY_CHECKED`, guarded inside the transaction,
refusing a replay, verifying the build's digests and schemas first, and
refusing to invent a reviewer. None of that was rebuilt.

What was missing, from an 18-row audit recorded in
`docs/closure/checkpoints/H04-dataset-quality-decision/evidence-table.csv`:

- **No verdict.** `QualityCheckRequest` has no decision field, so the only
  expressible outcome was approval. A data owner who read the report and said
  no had nowhere to put that.
- **No reviewer role**, only a name.
- **No source-policy binding**, so a decision could not say which policy was
  in force when the data it approves was acquired.
- **No durable record.** The only trace was an audit row in a database
  nobody in either available environment can reach.
- **No rejection path at all.**

Implemented: `DatasetQualityDecision` with exactly two verdicts, every field
required and no defaults, a derived decision id, an append-only NDJSON ledger,
refusal of a replay, of a stale binding (naming both halves of what moved) and
of a missing build; and `record_dataset_quality_decision`, which records first
and only then hands an approval to the existing WP-07 transition. A rejection
is recorded, is auditable, and moves nothing.

Thirty tests cover it, including a rejection that never reaches the
transition, a regenerated report that invalidates a standing decision, and a
replay that does not transition twice. Every reviewer in them is the shouted
synthetic data-owner identity the repository reserves for exactly this
situation, and a test walks `data/`, `docs/` and `config/` to prove that
identity appears in no committed artifact — which is why this report describes
it rather than spelling it. That test caught this report on its first run.

**Deliberately not implemented:** an operator command that records a real
decision. Adding one before a real dataset and a named data owner exist would
be a stub inviting misuse, and it is named as a gap rather than filled.

The committed ledger holds **zero** decisions. Nothing was approved.

## H02 — ready for a clinician

`docs/closure/checkpoints/H02-curation-protocol/clinical-review-table.csv`
carries seven decisions, each split into seven parts: what the authoritative
source states, what this repository currently assumes, what the project owner
directed, what is proposed technically, what goes wrong clinically, the open
scientific question, and the exact decision requested.

The owner's directions are carried as
`PROJECT_OWNER_DIRECTION / PENDING_CLINICAL_CONFIRMATION` — amitriptyline as a
joint two-gene decision, clopidogrel restricted to ACS/PCI, no CYP2D6 RAPID,
fail-closed for Likely and Indeterminate states, no FDA-supported claim for an
axis FDA does not cover, and clopidogrel extraction keyed on loss-of-function
rather than the obsolete phenotype phrase. They are directions, not clinical
decisions, and they stay open until a clinician rules.

Each proposed decision is bound to the protocol and disposition-report content
hashes, and the package states plainly that **the H01 approval is not an H02
approval**: the reviewer was not asked, and did not answer, any of these
questions.

## What is still true

`ths6_achieved: false`. No gate passes. No source is usable. No dataset
exists beyond the quarantined legacy build. No curated interpretation, no
rule, no ruleset, no release. Four of the five human checkpoints are
undecided, and the fifth — H01 — is decided but cannot yet be reflected in the
registry.
