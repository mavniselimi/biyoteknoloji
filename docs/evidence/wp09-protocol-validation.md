# WP-09 verification evidence

What was executed, on what, and what it produced. Every command is reproducible
from a clean checkout with no network access.

## 1. Environment

| Item | Value |
| --- | --- |
| Python | 3.10 (`python3`) |
| Test runner | `python3 -W error::ResourceWarning -m unittest discover -s tests -p 'test_*.py' -t .` |
| PyPI | unreachable. No SQLAlchemy, Alembic, psycopg, pytest, ruff or mypy is installed. |
| Database | **not used.** WP-09 adds no migration and writes no row. |
| Network | not used, and asserted absent (§7). |

`PYTHONDONTWRITEBYTECODE=1` is set for every run.

## 2. Test suite

```
$ PYTHONDONTWRITEBYTECODE=1 python3 -W error::ResourceWarning \
    -m unittest discover -s tests -p 'test_*.py' -t .
Ran 2410 tests in 88.492s
OK (skipped=10)
```

218 are new in WP-09, all under `tests/unit/curation/`:

| File | Tests | Covers |
| --- | ---: | --- |
| `test_curation_records.py` | 42 | evidence requirement, exclusions, rationale contract, source/conclusion separation, granularity, RAPID vs ULTRARAPID, numeric and executable prohibitions |
| `test_protocol_structure.py` | 40 | requirement uniqueness and mapping, field dictionary completeness, approval genuineness, the two separate verdicts, checked-in artifacts |
| `test_exercise.py` | 31 | real evidence references, determinism, blinding, blank-template refusal, comparison behaviour, pending real status |
| `test_conflict_and_insufficiency.py` | 24 | contradiction retention, no precedence, blocking conflicts, insufficiency as non-reassurance |
| `test_roles_and_cases.py` | 24 | author/reviewer separation, scientific-approval roles, placeholder names, adjudication preservation, case separation |
| `test_curation_protocol_cli.py` | 21 | command set, absent flags, blocked approval status, determinism |
| `test_curation_boundaries.py` | 16 | pure domain, no persistence, no migration, no later work package, evidence never mutated |

Four older tests asserting that `pgx/curation` does not exist were **converted,
not deleted**: each now asserts the dependency direction the physical-absence
check stood for — that the evidence, snapshot, release and scientific layers do
not import the curation layer. Those keep working as WP-09 grows.

## 3. Protocol validation

```
$ pgx-curation-protocol validate --text
protocol              pgx-curation-protocol/1
content hash          sha256:e0a76f45b0f606e4fd76d4c31829fcd61825278b01e407b71c13fc38298b56d6
status                AWAITING_EXPERT_REVIEW
technical completeness PASS
expert approval       BLOCKED
checks run            20
issues                1 (0 blocking)
  INFORMATIONAL CUR_APPROVAL_ABSENT                    pgx-curation-protocol/1
exit=0
```

**The two verdicts are reported separately and are different.** The protocol is
structurally complete and nobody has approved it. Collapsing those into one
boolean would let completeness stand in for approval, which is the failure this
work package exists to prevent.

20 checks ran, covering artifacts, requirement uniqueness and mapping,
vocabulary/code parity, field definitions and null semantics, evidence and
rationale requirements, conflict and insufficiency behaviour, role and case
separation, approval metadata, exercise evidence references and blinding,
legacy accounting, and the numeric-score and executable-field prohibitions.

Negative controls, each turning `technical_completeness` to `FAIL`:

```
$ pgx-curation-protocol validate --expect-proposals 1      → FAIL, exit=1
  (a missing artifact path)                                → FAIL
```

An absent input is reported informationally rather than passing silently: "the
inventory was not checked" and "the inventory is correct" are different
statements.

## 4. Schema validation

All five published schemas, applied to the checked-in artifacts:

```
protocol-v1.json              valid
field-dictionary-v1.json      valid
exercise manifest + cases     valid
comparison.pending.json       valid
a synthetic curation record   valid
```

Each constraint was confirmed to bite rather than pass silently:

```
a record carrying risk_level          → schema violation
a record with no evidence             → $.evidence: 0 items is below the minimum of 1
an artifact claiming APPROVED vocab   → $.vocabulary_status: expected 'DRAFT_AWAITING_EXPERT_REVIEW'
an approval by ENGINEERING_OBSERVER   → $.approval.approver.role: not one of the three scientific roles
```

The WP-06 validator raises on any keyword it does not implement, so these
schemas use only checked constructs.

## 5. Determinism

The artifact generator was run twice and every file byte-compared:

```
$ python3 scripts/build_curation_artifacts.py   # twice
$ diff <(sha256 of all 10 files) <(sha256 of all 10 files)
IDENTICAL across 10 files
```

| File | sha256 (first 16) |
| --- | --- |
| `config/curation/protocol-v1.json` | `d3edb6cd58e7a6b3` |
| `config/curation/field-dictionary-v1.json` | `36b942c616572117` |
| `data/curation/protocol-v1/legacy-hint-review-inventory.json` | `0f39a16dc118d5bc` |
| `data/curation/protocol-v1/exercises/manifest.json` | `73dbacb2c6b1fa76` |
| `data/curation/protocol-v1/exercises/cases.ndjson` | `3799e65c743b3f22` |
| `data/curation/protocol-v1/exercises/curator-a.template.json` | `4d8662732f8ea491` |
| `data/curation/protocol-v1/exercises/curator-b.template.json` | `ac135a679d4e0fbf` |
| `data/curation/protocol-v1/exercises/comparison.pending.json` | `7d3d690edeaaf436` |
| `data/curation/protocol-v1/exercises/adjudication.template.json` | `8e92aa9900934a4f` |
| `data/curation/protocol-v1/exercises/status.json` | `db0fcc7d9bb5408c` |

No generated file carries an operational timestamp. A `generated_at` would
change the bytes on every run, making "did this artifact change" unanswerable
and the approval hash unverifiable a day later.

## 6. Legacy proposal accounting

```
$ pgx-curation-protocol legacy-inventory --limit 3 --text
legacy manual-hint review queue
  proposals        1559
  linked           1526
  unlinked         33
  reviewed         0
  by state         {'NOT_REVIEWED': 1559}
```

All 1,559 WP-08 proposals are accounted for. Not one is reviewed. The 33
unlinked each carry the note saying why. A test asserts that the set of
proposal ids in the inventory equals the set in the source file, so none can be
dropped silently.

## 7. Offline execution

Every command was run with `socket.socket` replaced by a constructor that
raises:

```
validate                           exit=0
inspect                            exit=0
approval-status                    exit=1   (BLOCKED, as designed)
exercise                           exit=0
legacy-inventory --limit 1         exit=0
field conclusion_state             exit=0
all commands ran with sockets disabled
```

## 8. Synthetic inter-curator comparison

Two synthetic completed responses over the real nine-case packet:

| Scenario | Result |
| --- | --- |
| Two curators agreeing on every field | 81 fields compared, **0 differing** |
| Two curators disagreeing on four fields per case | 81 compared, **36 differing** (9 cases × 4 fields) |
| Evidence listed in reverse order | reported as **agreement** — order is not a disagreement |
| Two blank templates | **refused**: "a blank template would report perfect agreement about nothing" |
| Two responses by the same person | **refused** |
| A response to a different exercise | **refused** |

The report contains no `winner`, `correct_response`, `consensus`,
`merged_response`, `agreement_score` or `validity` — asserted by test and
forbidden by the published schema.

## 9. Real exercise and approval status

```
$ pgx-curation-protocol approval-status --text
protocol       pgx-curation-protocol/1
content hash   sha256:e0a76f45b0f606e4fd76d4c31829fcd61825278b01e407b71c13fc38298b56d6
status         AWAITING_EXPERT_REVIEW
expert approval BLOCKED
exercise       AWAITING_HUMAN_CURATORS

blocked by:
  - No named scientific expert has approved pgx-curation-protocol/1.
  - The inter-curator exercise has not been run: two named curators have not
    been assigned and neither response is complete.
  - No inter-curator comparison or adjudication record exists.
exit=1
```

## 10. Prior artifacts unchanged

WP-09 reads the sealed raw, canonical and evidence builds and writes to none of
them. Re-verified after all WP-09 work:

```
$ pgx-evidence verify --build data/evidence/PGX-DATA-20260830-900 \
    --snapshot data/raw/clinpgx-legacy-v2/PGX-DATA-20260830-900 --trace-limit 0
  checksums          ok
  files              ok
  published schemas  ok (1794 records)
  traces re-derived  1794 checked, ok

$ pgx-normalize verify --build data/canonical/PGX-DATA-20260830-900
  checksums              ok
  summary vs artifacts   ok
  published schemas      ok
```

A test additionally records every file's mtime in the evidence build before and
after a full exercise generation and asserts they are unchanged.

## 11. Known limitations

- **No scientific expert has read this protocol.** Its vocabularies, effect
  dimensions and requirements are one engineer's structuring of what the brief
  and the safety contract demand. They may be wrong in ways only a
  pharmacogenomicist would see.
- **The inter-curator exercise has not been run**, so nothing is known about
  whether two competent people would read this protocol the same way — which is
  the main thing the exercise exists to find out.
- **No legacy hint has been reviewed.** All 1,559 remain unreviewed.
- **`CurationStatus` spells `DRAFT` as `RAW`.** The protocol and the persisted
  enum use different names for the same state; the delta is recorded for WP-10
  rather than resolved here, because renaming a persisted enum is a migration.
- Inherited and unchanged: the WP-07 **1,572 versus 1,644** discrepancy remains
  open; the dataset remains `BUILDING`; the evidence build remains
  `QUARANTINED` and `NOT_PUBLICATION_ELIGIBLE`; no source policy has genuine
  human approval.
