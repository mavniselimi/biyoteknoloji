# Operating the rule registry

| Field | Value |
|---|---|
| Document ID | `DOC-OPS-008` |
| Work package | WP-11 — Computable Rule Specification and Validated Rule Registry |
| Tool | `pgx-rules` (`python3 -m pgx.application.rules_cli`) |

---

## 1. The current state, in one command

```
$ python3 -m pgx.application.rules_cli gate-status
```

Exit code 1, because the gates are shut. That is the correct exit code: a tool
that returned 0 on a closed gate would let a pipeline treat "blocked" as
"fine". The JSON names every blocker, who owns it, and what clearing it would
unblock.

## 2. Every command

| Command | Does |
|---|---|
| `inspect-rule PATH` | print one rule document |
| `validate-rule PATH` | report every structural issue at once |
| `list-issue-codes` | the 56 issue codes and the 8 conflict kinds |
| `detect-conflicts PATH...` | classify duplicates, overlaps and disagreements |
| `inspect-ruleset DIR` | print a frozen artifact's manifest |
| `verify-ruleset DIR` | checksums, manifest, members, approval list |
| `list-executable [--root DIR]` | what the engine-facing registry can serve |
| `gate-status` | why no real rule may be created |
| `build-attempt` | attempt a real build and report where it stopped |
| `legacy-inventory [--verify]` | the legacy candidate inventory |

Everything is read-only or refuses. There is no command that approves a rule,
assigns a role, forces a freeze, skips validation, ignores an evidence error
or promotes a legacy row — and the absent ones are listed in the source so
their absence is visible rather than merely true.

## 3. Flags that do not exist

`--role`, `--as`, `--grant`, `--force`, `--force-freeze`, `--skip-validation`,
`--ignore-evidence`, `--promote-legacy` and `--approve` are each refused **by
name**, with the reason:

```
$ python3 -m pgx.application.rules_cli --force validate-rule rule.json
{"error": "--force is not a flag this tool has",
 "reason": "there is no override for a failed validation"}
```

Abbreviations are off (`allow_abbrev=False`), so `--fo` does not silently
become `--force`.

## 4. The production registry is empty

```
$ python3 -m pgx.application.rules_cli list-executable
{"root": "data/rulesets", "executable_rulesets": [], "count": 0, ...}
```

`data/rulesets/` holds documentation and the two gate reports and no ruleset
artifact. The synthetic fixtures live under `tests/` and the production
registry never scans them; a test asserts both halves of that.

## 5. Verifying an artifact somebody hands you

```
$ python3 -m pgx.application.rules_cli verify-ruleset path/to/PGX-RULESET-...
```

Verification fails closed and specifically: a missing checksum file, a missing
member, a changed byte and an unlisted extra file are four different problems
reported as four different errors. Nothing is repaired. A tampered artifact is
absent from `list-executable` rather than present and broken.

## 6. Regenerating the published reports

```
$ python3 scripts/build_wp11_artifacts.py
```

Deterministic: running it twice produces byte-identical files. A test compares
the committed files against a fresh build, so a stale report is a test
failure.
