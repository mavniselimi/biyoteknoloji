# Operating the curation console and CLI

| Field | Value |
|---|---|
| Document ID | `DOC-OPS-010` |
| Work package | WP-10 — Curation Workflow and Approval Governance |
| Status | **Offline only. There is no server, no listening port, and no authentication.** |

---

## 1. What this is, and what it is not

Two things ship: a **console** (`pgx/curation/workflow/forms.py`) that renders
pages, and a **CLI** (`pgx-curation-workflow`) that reads the migration
artifacts and runs the real workflow service over them.

The console is not a web application. It has no framework, no server, no
socket, and nothing that binds or listens — asserted by test, not just stated
here. A handler takes a request mapping and returns a response object;
rendering a page is a function from data to a string. Whatever eventually
serves it is WP-16's decision, and making that decision here would be inventing
the web layer a work package early.

The CLI is offline. No database connection, no network. It loads
`data/migration/wp10/legacy-work-items.ndjson` into memory and drives the same
`CurationWorkflowService` the persistent adapters drive.

Neither is authenticated. Neither should be exposed to anyone.

## 2. CLI commands

```
python3 -m pgx.application.curation_workflow_cli <command> [options]
```

| Command | What it does |
|---|---|
| `import-legacy` | Builds RAW work items from the WP-08 proposals and reports the counts |
| `list` | Lists work items, optionally filtered by `--status` |
| `show <id>` | Prints one work item, including its unreviewed legacy values |
| `history <id>` | Every revision, review and adjudication, including superseded ones |
| `gate-status <id>` | Evaluates the thirteen gates without attempting anything |
| `validate-draft <id> --payload F` | Checks a draft payload against WP-09's rules |
| `render-form <route>` | Renders one console page to stdout |
| `submit <id>` | Submits a revision for independent review |
| `review <id>` | Records one review decision |
| `adjudicate <id>` | Settles a referred dispute |

Common options: `--text` for human-readable output (JSON otherwise),
`--work-items`, `--protocol`, `--roles`.

## 3. Exit codes

| Code | Meaning |
|---|---|
| `0` | the command answered |
| `1` | refused — a gate, a role, a state or a version said no |
| `2` | configuration failure — a file is missing or malformed |
| `3` | not found — no such work item |

A refusal is structured, not just prose, so a script can branch on it:

```json
{
  "refused": true,
  "code": "GateBlockedError",
  "gate_codes": ["GATE_EVIDENCE_QUARANTINED", "GATE_PROTOCOL_NOT_APPROVED"],
  "blockers": [
    {"code": "GATE_PROTOCOL_NOT_APPROVED",
     "requirement": "…",
     "owner": "a named scientific expert"}
  ]
}
```

`gate-status` exits `1` when any gate is shut, including when a work item has
no revision at all — a work item with nothing claimed cannot be approved, so
that is a refusal rather than an answer of "yes".

## 4. What every mutating command does here

It refuses, and the refusal is the deliverable:

```
$ … submit CWI-LEGACY-000835a2ce3e2726 --revision REV-1 \
      --expected-version 0 --actor TEST-curator-1
{
  "code": "ActorError",
  "detail": "no roles are assigned to 'TEST-curator-1'. This repository's
             production role assignment set is empty: no real curator,
             reviewer or adjudicator identity exists, so no real workflow
             can run.",
  "refused": true
}
```

Exit code `1`. This is correct behaviour, not a broken installation.

## 5. Roles cannot be supplied by the caller

`--actor` names who is acting. It grants nothing: the roles come from the
injected provider, and the default provider is empty.

These flags do not exist and are refused **by name**, so the message explains
why: `--role`, `--as`, `--as-role`, `--reviewer-role`, `--grant`, `--force`,
`--skip-gates`, `--approve`.

Argparse abbreviation is switched off. Without that, `--role ADJUDICATOR` was
silently accepted as an abbreviation of `--roles` and its value read as a
filename — a flag the tool deliberately does not have, absorbed by one it does.

A role file may be supplied with `--roles` for exercising the workflow, and is
refused unless **every** actor in it carries the `TEST-` prefix. Assigning a
role to a named person is authentication; a JSON file is not an authentication
system.

## 6. Commands that do not exist

Named here so their absence is visible in the documentation as well as in the
source: `approve`, `approve-protocol`, `create-rule`, `validate-rule`,
`publish-dataset`, `curate`, `auto-review`, `resolve-conflict`.

## 7. The console

```
python3 -m pgx.application.curation_workflow_cli render-form detail \
    --work-item CWI-LEGACY-… > /tmp/page.html
```

Six read routes — `list`, `detail`, `editor`, `evidence`, `review-form`,
`history` — and three write routes — `save-revision`, `submit-revision`,
`record-review`.

**Read routes cannot mutate.** They receive a read-only façade exposing only
`gate_status` and `history`. A mutating call in a read handler is an
`AttributeError`, not a code-review finding.

**Write routes require a POST.** A write route reached by a GET-like method
returns `405` before reading anything: a state change behind a link is a state
change somebody can be tricked into making.

**Every mutating form carries the version it was rendered from**, and a
submission without `expected_version` is refused rather than defaulted. A
default would silently mean "whatever the version is now", which is exactly the
assumption optimistic concurrency exists to refuse.

**The form supplies no role.** There is no widget, no accepted parameter, no
default — and `role`, `roles`, `as_role`, `actor_roles`, `force`,
`skip_gates`, `approved_by` and `status` are refused if sent anyway.

**Approval disappears when a gate is shut.** Not disabled with a tooltip:
absent from the decision list, replaced by the blockers with the owner of each.
Rejecting, requesting changes and referring stay available.

## 8. Source text and curator text never share a channel

Upstream text — what a source actually said, and the legacy values from WP-08 —
is rendered in a block labelled **"unreviewed upstream text"**. Text this
project wrote is rendered in a differently styled block labelled **"written by
this project"**.

A console that blurred the two would let a curator adopt an upstream claim
believing a colleague had already checked it.

Everything is escaped once, in one function, with quoting on, because values
are interpolated into attributes as well as into text. Source text comes from
files this project did not write.

Pages are deterministic: no script tag, no external stylesheet, no timestamp.
The same inputs render byte-identical output, which is what makes a snapshot
test meaningful.

## 9. Rebuilding the artifacts

```
python3 scripts/build_wp10_migration.py
python3 scripts/render_wp10_schema.py --out build/wp10-schema.sql
python3 scripts/render_wp10_schema.py --direction downgrade \
    --out build/wp10-downgrade.sql
```

Both are byte-identical on a rebuild from unchanged input. The migration's
import timestamp is derived from the input file's content hash rather than the
clock, so a change in the output means a change in the data.

## 10. Related

- [curation-workflow](../scientific/curation-workflow.md)
- [curation-approval-gates](../scientific/curation-approval-gates.md)
- [wp10-legacy-work-items](../migration/wp10-legacy-work-items.md)
