# WP-05 handoff

| Field | Value |
|---|---|
| Document ID | `DOC-HANDOFF-005` |
| Work package | WP-05 - Scientific Source Strategy, Provenance and Licensing Policy |
| Status | **Mechanism delivered. Human review not started.** |
| Blocks | Any dataset publication; any release citing any source |

> Read this before WP-06. Two acceptance criteria are legitimately BLOCKED and
> must not be presented as met: no human has reviewed any source, and no
> official licensing evidence has been retrieved. Everything WP-05 built is the
> machinery around a decision nobody has taken yet.

---

## 1. What exists now

| Artefact | What it is |
|---|---|
| `pgx/scientific/` | Vocabularies, records, registry, validation, conflicts, gate, legacy inventory, ports, errors |
| `config/scientific-sources.json` | 20 candidate sources, all `PENDING_REVIEW` |
| `schemas/scientific-source-registry.schema.json` | Generated from the vocabularies by `scripts/render_source_registry_schema.py` |
| `data/migration/legacy-source-inventory.json` | 18 distinct source values, 11 308 occurrences, deterministic |
| `docs/migration/legacy-source-inventory.md` | The same, as a report |
| `migrations/versions/0003_wp05_source_policy.py` | Five tables, two append-only triggers |
| `pgx/application/source_policy_cli.py` | `pgx-source-policy`, five read-only subcommands |
| `docs/scientific/*.md` | Strategy, provenance, reuse matrix, conflict policy, review checklist |

## 2. What is blocked, and what unblocking looks like

### 2.1 No source has been reviewed (A19)

**Today.** Every source is `PENDING_REVIEW`. `approved_source_keys()` returns
an empty tuple. The publication gate returns `BLOCKED` for every dataset, and
`ReleaseService` refuses to activate any release citing any registered source.

**What a reader could wrongly conclude.** That the mechanism is untested. It is
not: `tests/unit/scientific/test_publication_gate.py` exercises the approving
path with a synthetic source, and the executed-schema evidence shows a genuine
review row making an `APPROVED` policy legal. What is missing is a *decision*,
not a code path.

**What "fixed" means.** A named person works through
`docs/scientific/source-review-checklist.md` for one source, records the
review in `config/scientific-sources.json`, and commits it. The commit is part
of the record.

### 2.2 No official licensing evidence has been retrieved (A20)

**Today.** One attempt was made, to `api.clinpgx.org` and `www.clinpgx.org`.
Both were refused at the network layer (`Tunnel connection failed: 403
Forbidden`). No other source was probed. Every `license_identifier` is `null`
and every reuse dimension is `UNKNOWN`.

**What a reader could wrongly conclude.** That ClinPGx refused this project
access. It did not: the request never left the environment. The failure is an
environment blocker, and the recorded `blocked_reason` says exactly that.

**What "fixed" means.** From an environment with egress, a person opens each
source's own terms document, records the URL, retrieval instant, content hash
and a short factual summary, and sets `verification: VERIFIED`. Not a tool: no
tool in this repository fetches a terms page, deliberately.

## 3. Open items WP-05 did not fix

### 3.1 Reuse permissions have no per-restriction record

`RESTRICTED` blocks and the restriction text lives on the review as free text.
There is no structured way to record "this restriction is satisfied because X",
so a source with any `RESTRICTED` dimension can only ever be approved as a
whole. If several sources turn out to be `RESTRICTED` in practice, this will
need a structured satisfaction record.

### 3.2 The database tables have no repository implementations

`pgx/scientific/ports.py` declares four ports. No SQLAlchemy repository
implements them, and no service writes to the `0003` tables yet. The registry
file is the working source of truth; the tables are the operational record that
a later work package will populate when datasets and releases actually exist.
Nothing currently reads them either, so an empty `source_policies` table is not
evidence of anything.

### 3.3 Conflict detection has no producer

`detect_conflicts` compares normalised statements. Producing those is canonical
resolution and curation - WP-07 and WP-09 onward. Nothing in this repository
currently feeds the detector, so the conflict register is empty for want of
inputs rather than because no conflicts exist.

### 3.4 Legacy container values are not sources

`data/guidelineAnnotation`, `report/pair:variantAnnotation` and the rest are
provider-internal locations, not sources in their own right. They are inventoried
and are deliberately **not** checked against the registry. If a later work
package wants to trace a record to a specific container, that mapping needs its
own decision.

### 3.5 Case-variant container spellings are unresolved

`report/pair:variantAnnotation` and `report/pair:VariantAnnotation` both occur
4718 times each, across three columns. The inventory reports them separately and merges nothing. Whether
they name the same thing is a question for the source owner.

### 3.6 The registry file is not packaged in the wheel

`default_config_path()` walks up from the installed module looking for
`config/scientific-sources.json`. In a wheel install there is none, and loading
raises `SourcePolicyConfigError` - which blocks rather than silently finding no
policy. The file *is* in the sdist. A deployment that needs a different registry
must pass its path explicitly.

## 4. What WP-06 may and may not assume

**May assume.** The vocabularies and record types are stable. The gate is
deterministic and its verdict digest can be cited. The `0003` schema exists and
its constraints hold on PostgreSQL 16.13. The legacy inventory is byte-stable
and can be regenerated in CI with `--check`.

**May not assume.** That any source is approved, that any licence is known,
that any reuse is permitted, that the ClinPGx adapter may be run, or that a
dataset may be published. WP-06 builds snapshot storage; packaging
`clinpgx_outputs_v2/` as a legacy raw snapshot with its limitations recorded is
consistent with WP-05 only because `internal.legacy_probe_outputs` is an
`INTERNAL_SYSTEM` source - which can never be scientific evidence.

**Must not do.** Add a precedence rule to `pgx/scientific/conflict.py`; add an
`approve` path anywhere; fetch a terms page from a tool; or seed a reviewer
identity into `config/`.

## 5. Inherited blockers, unchanged

WP-05 resolves none of these and presents none of them as resolved:

- WP-00 claim-boundary approval: **BLOCKED**, awaiting human and scientific review.
- WP-01 Git checkpoint: **BLOCKED**.
- WP-02 toolchain: `ruff`, `mypy`, `pytest`, `alembic`, `sqlalchemy`, `psycopg`
  all uninstallable; the package index is unreachable. Docker daemon unreachable.
- WP-03 review findings: six items open in `docs/handoffs/wp03-open-items.md`.
- WP-04: no live ClinPGx call has been made; the adapter is unexercised against
  the real API.
