# WP-04 - Ingestion Evidence Artifact

| Field | Value |
|---|---|
| Document ID | `DOC-THS6-004` |
| Work package | WP-04 - Ingestion Foundation and ClinPGx Production Adapter |
| Captured (UTC) | 2026-08-30 |
| Live ClinPGx calls made | **zero** |
| Sockets opened by the test suite | **zero** |

> **This is a technical evidence artifact for WP-04 only.** It claims no THS 6
> success, no scientific validation, and no clinical safety. Acquiring a record
> asserts nothing about that record.
>
> WP-00 approval remains **BLOCKED**; WP-01's Git checkpoint remains
> **BLOCKED**; WP-02's and WP-03's toolchain blockers are unchanged; the WP-03
> review findings are open in `docs/handoffs/wp03-open-items.md`. WP-04 resolves
> none of them and presents none of them as resolved.

---

## 1. Three kinds of evidence, kept apart

| Kind | What it proves | What it cannot |
|---|---|---|
| **A. Offline behavioural** | Retry, backoff, `Retry-After`, request keys, cache semantics, pagination guards, completeness arithmetic, determinism | Anything about the real ClinPGx API |
| **B. Structural** | The catalog matches the legacy probes' request intent; the defects were not ported; the layers do not cross | That any of it runs against a live source |
| **C. BLOCKED** | Nothing | Live connectivity (A15); source licensing (A16) |

Every claim below is A or B. **No live ClinPGx call was made at any point**, and
no claim about how the API *behaves* rests on anything but a reading of the
probe source.

## 2. Test results

All runs use `PYTHONDONTWRITEBYTECODE=1` and `-W error::ResourceWarning`.

| Command | Exit | Result |
|---|---|---|
| `... discover -s tests/unit -p 'test_*.py' -q` | 0 | **874 tests, OK** |
| `... discover -s tests/failure -p 'test_*.py' -q` | 0 | **15 tests, OK** |
| `... discover -s tests/regression/legacy -p 'test_*.py' -q` | 0 | **151 tests, OK** |
| `... discover -s tests/integration -p 'test_*.py' -q` | 0 | **0 run, 10 skipped** (PostgreSQL, WP-02/03) |
| `... discover -s tests -p 'test_*.py' -t .` | 0 | **1040 tests, OK, 10 skipped** |
| `python3 -m compileall pgx scripts tests migrations` | 0 | all modules compile |
| `compare_legacy_v2.py verify-manifest` | 0 | **MATCH, 64/64 + 22/22, 0 problems** |

WP-04 added **214** tests, none of them a skip:

| Suite | Tests | Kind |
|---|---|---|
| `test_transport_and_retry.py` | 46 | A |
| `test_request_key_and_cache.py` | 40 | A |
| `test_acquisition.py` | 36 | A |
| `test_replay_and_determinism.py` | 19 | A |
| `test_clinpgx_catalog.py` | 40 | B |
| `test_ingestion_cli.py` | 33 | A + B |

Two socket-level assertions back the "offline" claim: `socket.socket` is
replaced with a raising stub while every ingestion module is reloaded, and again
while the ClinPGx transport is constructed. Both pass.

## 3. Request intent carried across

The full inventory, with the parameter spellings and the assumptions that need
live confirmation, is `docs/migration/clinpgx-probe-intent.md`.

| Ported | Not ported |
|---|---|
| 8 endpoints, query keys verbatim (`relatedGenes.accessionId`, `location.genes.symbol`, …) | `get_first()` - first-result selection |
| `https://api.clinpgx.org/v1`, host allowlisted | `flatten_items()` - six container keys then wrap-the-payload |
| `view=base` on every call | `time.sleep(0.6)` before every request |
| The three guideline parameter sets, as **three separate endpoints** | merging and deduplicating those three |
| Path-parameter reports (`/report/pair`, `/report/connectedObjects`) | trying twelve `result_type` spellings and keeping whichever answered |
| | `OUT_DIR` - a module-level output directory |
| | `quiet_404` - swallowing 404s |
| | `summarize_*`, `make_mvp_edge_row`, `html_to_text`, `rank_key`, `dedupe_by_id`, the keep-30 variant heuristic |

Each "not ported" item is pinned by a test that reads the module's **AST**, not
its text - so prose explaining why `get_first` was left behind does not register
as `get_first`, and a real reintroduction cannot hide inside a string literal.

## 4. Offline drill

`python3 scripts/ingestion_drill.py --out docs/examples/wp04`, exit 0.

### 4.1 Network acquisition, with one retried 503

```
status            : COMPLETE          publishable : True
endpoints         : 4 (3 required)    pages/records : 8 / 5
content hash      : sha256:c0b82f088d25d330d80a98e063960e56d8ae8aaa19c52d5b2df5a7c963580110
  gene_lookup                    required COMPLETE pages=2 terminal=True (EMPTY_PAGE)
  chemical_lookup                required COMPLETE pages=2 terminal=True (EMPTY_PAGE)
  guideline_annotation_by_pair   required COMPLETE pages=2 terminal=True (EMPTY_PAGE)
  guideline_annotation_by_gene   optional COMPLETE pages=2 terminal=True (EMPTY_PAGE)
transport calls   : 9      (8 pages + 1 retried 503)
first page retries: 1
first page digest : sha256:da052c8a94b9785d067fe60dedd56396bb828064f875b94dd2a94e18906c11fe
```

### 4.2 Cache-only replay - zero network

```
status            : COMPLETE          publishable : True
content hash      : sha256:c0b82f088d25d330d80a98e063960e56d8ae8aaa19c52d5b2df5a7c963580110
transport calls   : 0
content hash equal to the network run : True
run id differs                        : True
every page a cache hit                : True
```

The replay used a transport that **raises if called**, and a clock stepping nine
seconds instead of half a second. Every operational field differs; the content
hash is identical to the character. A separate test also asserts the transport
*factory* is never invoked, so the replay could not fall back to the network
even if a page were missing.

### 4.3 Partial failure - a required endpoint returns corrupt JSON

```
status            : FAILED            publishable : False
  gene_lookup                    required COMPLETE pages=2 terminal=True  (EMPTY_PAGE)
  chemical_lookup                required FAILED   pages=1 terminal=False (ERROR)
  guideline_annotation_by_pair   required COMPLETE pages=2 terminal=True  (EMPTY_PAGE)
  guideline_annotation_by_gene   optional COMPLETE pages=2 terminal=True  (EMPTY_PAGE)
FAILURE: required endpoint 'chemical_lookup' did not complete: response body is
         not valid JSON ... The raw bytes are still preserved with their digest,
         so the run can be diagnosed and replayed.
raw bytes of the corrupt page were still stored: True
```

Three of four endpoints succeeded and the run is **not publishable**. The
corrupt page's bytes and digest are kept.

### 4.4 Optional failure - a warning, not a failure

```
status            : COMPLETE_WITH_WARNINGS   publishable : True
  guideline_annotation_by_gene   optional FAILED pages=1 terminal=False (ERROR)
WARNING: optional endpoint 'guideline_annotation_by_gene' failed: expected
         content type 'application/json', got 'text/html'.
```

Example manifests: `docs/examples/wp04/acquisition-manifest-{complete,replay,failed}.json`.

## 5. Completeness, proven case by case

| Case | Status | Publishable |
|---|---|---|
| every required endpoint terminal | `COMPLETE` | yes |
| optional endpoint failed | `COMPLETE_WITH_WARNINGS` | yes |
| required endpoint returned corrupt JSON | `FAILED` | no |
| required endpoint hit the page budget | `FAILED` | no |
| required endpoint hit the record budget | `FAILED` | no |
| required endpoint's cursor repeated | `FAILED` | no |
| required endpoint's cursor was malformed | `FAILED` | no |
| required endpoint's request key repeated | `FAILED` | no |
| cache-only replay with an empty cache | `FAILED` | no |
| cache-only replay with a corrupt blob | `FAILED` | no |

`build_acquisition_manifest` takes **no `status` parameter** - a test asserts it
by reading the function signature. The status is derived from the endpoint
outcomes and cannot be supplied by a caller.

## 6. Credential safety

Asserted by putting a distinctive secret in and searching the output for it,
rather than by inspecting code:

| Surface | Result |
|---|---|
| request key | identical with and without a token set |
| cache blobs and metadata | every file in the cache tree scanned; secret absent |
| written run manifest | scanned; secret absent |
| CLI stdout and stderr | scanned; secret absent |
| `UrllibTransport.__repr__` | overridden; prints a count, not the headers |

Credential header names are filtered in three independent places: the request
key builder, the cache writer, and the transport's outgoing header assembly.

## 7. Layer boundaries

| Assertion | Result |
|---|---|
| `pgx/domain` gained no HTTP or filesystem import | pass (WP-02's dependency test still passes) |
| no release module imports `pgx.ingestion` | pass |
| no ingestion module imports the release service | pass |
| no ingestion module imports SQLAlchemy | pass |
| no ingestion module names `EvidenceRecord`, `ComputableRule`, `DatasetVersion`, … | pass |
| no ingestion module mentions `PUBLISHED`, `release_eligible = True`, `approve_source` | pass |
| the adapter and the service name no endpoint ID | pass |
| the transport is built in exactly one place, reachable from one subcommand | pass |

Three WP-03 tests asserted that `pgx/ingestion` did not exist. That was correct
for WP-03 and became false-by-design when WP-04 created it. They were converted
to the invariants above rather than deleted: the separation is what was worth
keeping, not the absence.

## 8. Preservation

| Scope | Result |
|---|---|
| WP-00 `claims.py`, `test_claims.py`, both documents | **byte-identical** |
| `architecture.md` | **byte-identical** |
| Seven legacy Python modules, including both probes | **unchanged - read only, never executed** |
| WP-01 manifest | **64/64 legacy, 22/22 evidence, 0 problems** |
| WP-01 amendments | **1** (the WP-02 record); no new amendment |
| `migrations/versions/0001` and `0002` | **unchanged** |
| `uv.lock` | **absent** - none fabricated |
| WP-05 / WP-06 artifacts | **none** |

## 9. BLOCKED

| Criterion | Why | What would settle it |
|---|---|---|
| **A15 - live ClinPGx connectivity** | No live call was made. WP-04 was built and verified entirely against a scripted transport. | One supervised `pgx-ingest-clinpgx acquire` against a single gene/drug pair. It would confirm or refute every assumption in `docs/migration/clinpgx-probe-intent.md` section 4. |
| **A16 - source licensing and approval** | WP-05 has not started. Nothing in WP-04 sets or reads `release_eligible`. | WP-05. |

Neither blocker stopped the offline work, and neither is presented as resolved.
