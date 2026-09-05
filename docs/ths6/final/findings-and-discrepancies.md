# Findings and discrepancies

A **finding** says a document, a count or an artifact is wrong. A **blocker**
says a condition is unmet. They are different things, they have different
fixes, and they are counted separately.

## 1. A real defect: WP-17's gate status fails its own schema

`data/web/wp17-real-gate-status.json` records:

```
"screenshot_evidence_status": "CAPTURED"
```

Its own published schema, built by `apps/web/artifacts.py`, permits only:

```
"enum": ["NONE", "BROWSER_CAPTURED"]
```

The producer (`apps/web/gate_status.py`) emits `"CAPTURED"`; the tests assert
`"CAPTURED"`; the schema says something else. Nothing in the repository ever
validated the gate status against its own published schema, so the
disagreement survived WP-17 through WP-24 unseen.

- **Code:** `THS6_EVIDENCE_INVALID`, blocking
- **Owner:** platform owner
- **WP-25's action:** the artifact is typed `INVALID` and supports no claim.
  WP-25 does **not** repair another work package's artifact or schema —
  overwriting historical artifacts with successor results is outside this
  work package. `pgx-ths6 inventory` exits `1` because of it.
- **Note on Gate F:** condition F4 reads a *different* field of the same
  artifact (`validation_dashboard_status`), which is well-formed. The gate
  still reads it, and this finding is why a reader should treat that
  condition's evidence as provisional.

A unit test pins the exception by name. If somebody fixes WP-17, that test
fails and tells them to retire this finding rather than leaving a stale one in
the pack.

## 2. The Definition of Done count discrepancy

WP-25's prose says fourteen items; `architecture.md` §21 enumerates fifteen.

- **Code:** `THS6_DOD_DECLARED_COUNT_MISMATCH`, non-blocking
- **Owner:** architecture/document owner
- **Resolution:** all fifteen implemented as `P0-DOD-001` … `P0-DOD-015` and
  evaluated separately. No bullet merged, renumbered or discarded. The schema
  pins the count to fifteen.

## 3. WP-24's prose about `docs/ths6/`

WP-24's closing prose stated that no `docs/ths6/` directory existed. It did,
containing three preliminary WP-local evidence notes.

- **Code:** `THS6_PROSE_INVENTORY_DISCREPANCY`, non-blocking
- **Owner:** WP-24 author
- **Resolution:** the three notes are preserved unchanged, inventoried as
  `DOCUMENT_ONLY`, and kept disjoint from the final pack under
  `docs/ths6/final/`.

## 4. Two source documents could not be read

Two requirement documents named by the WP-25 brief live in a folder that is
not connected to the session this pack was built in. No bytes of either
reached this work.

- **Code:** `THS6_SOURCE_DOCUMENT_UNAVAILABLE`, non-blocking
- **Owner:** work package author
- **Resolution:** requirements taken from `architecture.md` (`EV-WP00-001`).
  Nothing about the unread documents is inferred, quoted or summarised
  anywhere in this pack.

## 5. Three stale artifacts

`data/verification/wp19-real-gate-status.json`,
`wp19-test-inventory.json` and `wp19-verification-run.json` record values
their own sources have since changed.

- **Code:** `THS6_EVIDENCE_STALE`, non-blocking
- **Owner:** verification owner
- **Resolution:** typed `STALE`. A stale artifact supports no claim.

## 6. One artifact is named but absent

`data/api/wp16-runtime-verification.json` is named by WP-16's manifest and is
not present, because the ASGI runtime suite has never run.

- **Code:** `THS6_EVIDENCE_UNAVAILABLE`, non-blocking
- **Owner:** repository maintainer
- **Resolution:** typed `UNAVAILABLE` with no invented digest. Its absence
  makes the served OpenAPI document report itself unverified, which is the
  truthful answer.

## Four source-artifact disagreements

Where two authoritative artifacts state different things about the same fact,
WP-25 records the disagreement and does **not** resolve it. Choosing the more
favourable of two values is how an evidence pack becomes advocacy.

| Fact | Left | Right |
|---|---|---|
| whether the expert review workflow is implemented | WP-17: `NOT_IMPLEMENTED` | WP-22: `IMPLEMENTED` |
| the number of holdout validation cases | WP-17: `null` (no count taken) | WP-18: `0` (a count found none) |
| whether WP-24 has started | WP-20: `false` | WP-19: `true` |
| how many tests this repository has | WP-19: `6374` recorded | 6,996 test functions defined, counted by parsing |

`null` and `0` are treated as a **disagreement**, not a match. One says no
measurement was taken and the other says a measurement found none, and this
project has spent five work packages keeping them apart.

The test count is measured rather than read: WP-25 parses every file under
`tests/` and counts the test functions defined. That is a different
measurement from discovery, so only a *material* gap is reported — a recorded
count below the number of defined functions cannot be explained by skips,
which reduce execution rather than discovery.
