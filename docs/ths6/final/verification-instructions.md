# How to check all of this yourself

Nothing in this pack asks to be trusted. Every claim it makes can be
re-derived from the repository with the commands below.

## Prerequisites

Python 3.11 and this repository. No network, no database, no container
runtime, no extra packages. If any command below needed one of those, it
would report BLOCKED rather than failing.

## The nine commands

```
pgx-ths6 inventory        # every artifact, classified and hashed
pgx-ths6 claims           # every claim and what refutes it
pgx-ths6 traceability     # requirement -> implementation -> test -> evidence
pgx-ths6 gates            # gates A-F rebuilt from source artifacts
pgx-ths6 dod              # all fifteen Definition of Done items
pgx-ths6 demo-preflight   # the demonstration's preconditions, in order
pgx-ths6 verify-pack      # recompute the pack's hashes and compare
pgx-ths6 build-pack       # rewrite the twelve artifacts and the manifest
pgx-ths6 status           # pack integrity and THS 6 achievement, separately
```

Add `--json` to any of them for the full document. Add `--verbose` to `gates`
to print every blocker with its owner.

## Expected exit codes today

| Command | Code | Why |
|---|---|---|
| `inventory` | 1 | one artifact fails its own published schema |
| `claims` | 2 | no claim is supported |
| `traceability` | 2 | twenty of twenty-one rows are unsupported |
| `gates` | 2 | all six gates are BLOCKED |
| `dod` | 2 | fourteen of fifteen items are unsatisfied |
| `demo-preflight` | 2 | stops at DEMO-02 |
| `verify-pack` | 0 | the pack is intact |
| `build-pack` | 0 | the pack was written and is intact |
| `status` | 2 | the programme is blocked |

`0` means the thing asked about is genuinely so. `1` means something is
invalid, corrupt or failing. `2` means it has not happened. `3` means the
request was malformed.

**`verify-pack` and `build-pack` exiting 0 is not a THS 6 pass.** They ask
whether the pack is sound; a sound pack honestly recording six blocked gates
is a success for them and nothing more. Every other command asks about the
programme.

## Checking a single gate condition by hand

Each condition names the artifact and the field it read. To check A1:

```
python3 -c "import json;print(json.load(open('data/rulesets/wp11-real-gate-status.json'))['upstream_state']['source_registry_approved'])"
```

If that prints anything other than `0`, this pack is out of date and
`pgx-ths6 gates` will say so.

## Checking the Definition of Done transcription

The fifteen bullets are carried verbatim. Compare
`data/ths6/wp25-definition-of-done.json` against `architecture.md` §21. A unit
test does this automatically by parsing the section and comparing bullet by
bullet, so a drift in either fails the suite.

## Checking pack integrity by hand

```
python3 -c "
import json,hashlib
m=json.load(open('data/ths6/wp25-evidence-pack-manifest.json'))
for e in m['members']:
    d=hashlib.sha256(open(e['path'],'rb').read()).hexdigest()
    assert 'sha256:'+d==e['sha256'], e['path']
print('all', len(m['members']), 'members match')"
```

The manifest is not one of its own members — a manifest containing a digest of
itself could never satisfy its own check, because writing the digest changes
the bytes. The pack's identity is `pack_sha256`, a digest over the sorted
`(path, digest)` pairs, which a verifier recomputes.

## Running the WP-25 test suite

```
python3 -m unittest discover -s tests/unit/ths6 -t .
```

Or through the verification profile:

```
pgx-verify run --profile ths6
```

## Running the whole suite

```
python3 -W error::ResourceWarning -m unittest discover -s tests -p 'test_*.py' -t .
```

## What you cannot do

There is no way to make any of this report a better result. No `--force`, no
`--assume`, no `--fixture`, no `--ignore-blocker`, no environment variable and
no fixture mode. `GateRecord` refuses at construction to hold `PASS` beside an
unmet condition, so the absence of an override is a property of the types
rather than a promise about the command line — and a unit test greps every
module in the package for each spelling.
