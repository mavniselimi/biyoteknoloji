# WP-04 - Ingestion Foundation and ClinPGx Production Adapter

| Field | Value |
|---|---|
| Document ID | `DOC-ARCH-004` |
| Work package | WP-04 - Ingestion Foundation and ClinPGx Production Adapter |
| Companion documents | `docs/migration/clinpgx-probe-intent.md`, `docs/ths6/wp04-ingestion-evidence.md` |
| Architecture source | `architecture.md` sections 8.1, 8.2, 17 (WP-04) |

> **Acquiring a record asserts nothing about that record.** WP-04 retrieves raw
> responses and records what it did. It resolves no entity, deduplicates
> nothing, interprets nothing, and decides nothing about whether a source may
> back a release.
>
> **WP-00 approval remains BLOCKED**, WP-01's Git checkpoint remains BLOCKED,
> and WP-02's and WP-03's external blockers are unchanged. WP-04 resolves none
> of them. The WP-03 review findings are recorded, unfixed, in
> `docs/handoffs/wp03-open-items.md`.

---

## 1. The question this work package answers

*Exactly what did we ask the source, exactly what did it send back, and did we
get all of it?*

The last clause is the one the legacy probes could not answer. They issued one
request per endpoint and reported success, so "we have the data" and "we have
some of the data" were indistinguishable. Everything below exists to make that
distinction real and to keep it visible in the manifest.

## 2. Scope and non-goals

**In scope**

- an injected HTTP transport with an explicit safety policy;
- bounded retry with exponential backoff, jitter, and `Retry-After`;
- deterministic, credential-free request keys;
- a content-addressed cache preserving raw bytes;
- cache-only replay that makes no request;
- declarative pagination with loop and budget guards;
- a declarative ClinPGx endpoint catalog;
- completeness computed from endpoint outcomes;
- a run manifest and a separate deterministic content manifest;
- `pgx-ingest-clinpgx`.

**Explicitly out of scope**

| Deferred | Owner |
|---|---|
| Deciding a source may back a release (licensing, provenance policy) | WP-05 |
| Immutable dataset snapshots and publication | WP-06 |
| Canonical gene/drug resolution, deduplication | WP-07 |
| Evidence store, traceability | WP-08 |
| Curation, interpretations, computable rules | WP-09 to WP-11 |
| Any risk or attention computation | WP-12 to WP-14 |

## 3. Package layout

```
pgx/ingestion/common/     source-agnostic machinery
    errors.py             typed failures; the retry policy's input
    models.py             requests, responses, retrieval records, run status
    http.py               transport protocol, request key, safety policy
    retry.py              bounded retry, backoff, jitter, Retry-After
    cache.py              content-addressed raw response cache
    pagination.py         strategies and loop guards
    manifest.py           run manifest and the deterministic content hash
pgx/ingestion/clinpgx/    the ClinPGx adapter
    catalog.py            declarative endpoints - data, not behaviour
    client.py             transport configuration for this one host
    parsers.py            bytes -> records, with no interpretation
    adapter.py            one endpoint, page by page
pgx/application/          orchestration
    ingestion_service.py  plan / acquire / replay / validate
    ingestion_cli.py      pgx-ingest-clinpgx
```

Nothing in `pgx/domain` gained an HTTP or filesystem import. The service depends
on the ingestion package and the domain's hashing and immutability helpers, and
on nothing else.

## 4. Transport

One protocol method: request in, response out, typed errors. Everything above it
- retry, cache, pagination, the whole adapter - is written against it, which is
why the entire acquisition path is testable with a scripted fake and no socket.

The production transport uses `urllib`, so acquisition adds no dependency to a
project that cannot reach a package index.

**The safety policy is a list of refusals**, each with a specific failure in
mind:

| Rule | What it prevents |
|---|---|
| HTTPS required | credentials and payloads in clear text |
| Explicit host allowlist; an empty list is a configuration error | a mistyped base URL silently reaching another host |
| Cross-host redirects refused | a redirect walking the request off the allowlist |
| Timeout mandatory, and bounded above | a hung request stalling a run; a caller disabling the timeout by making it enormous |
| Response size limit | an unbounded read exhausting memory before any other check runs |

**Credentials never touch a request object.** They are held by the transport,
read from the environment at construction, and attached at send time - so no
credential can reach a request key, a cache entry, a manifest, or a log line.
`UrllibTransport.__repr__` is overridden for the same reason.

## 5. Retry

| Retried | Not retried |
|---|---|
| timeouts, reset connections | 400, 401, 403, 404, 405, 409, 410, 422 |
| 429, 500, 502, 503, 504 | corrupt JSON, wrong shape, wrong content type |
| | configuration and security-policy errors |

An unclassifiable error is **not** retried: guessing "probably transient" turns
one bad request into a storm of them. Retrying a 401 additionally looks like a
brute-force attempt from the far end, and retrying a 429 that was quota
exhaustion makes the quota worse.

**Two bounds, because either alone is insufficient.** `max_attempts` caps the
tries; `max_elapsed_seconds` caps the wall clock. Five attempts against a server
answering `Retry-After: 300` would otherwise block a run for 25 minutes.

**`Retry-After` wins over our backoff, clamped.** When a server states how long
to wait, guessing is worse than listening - but the value is clamped to
`max_delay_seconds` so a server cannot park a run for an hour.

Clock, sleeper and randomness are injected. Every attempt is recorded with its
delay, status or error, any `Retry-After`, and why it was retried.

## 6. Request keys

`sha256` over a canonical description of *what was asked for*:

| In the key | Not in the key |
|---|---|
| method, scheme, host, port, path | any credential header |
| sorted query pairs | `User-Agent` |
| endpoint ID | the wall clock |
| response shape version | the timeout |
| semantic headers (`Accept`, `Accept-Language`) | the cache or output directory |
| | the retry attempt number |

The same semantic request always produces the same key, whatever order the query
was built in. Every exclusion has a reason: including any of them would make the
same question produce a different key and the cache would never hit, and the
credential exclusions would additionally write a token into a filename and into
every manifest.

## 7. Cache

Three things, kept apart:

```
<root>/index/<request-key-hex>.json   metadata, pointing at a blob
<root>/blobs/<aa>/<sha256-hex>        the raw bytes
```

Two different requests returning identical bytes share one blob; the metadata
records *how* a response was obtained without that affecting *what* was obtained.

| Property | Why |
|---|---|
| Bytes stored exactly as received | every downstream digest derives from them; a normalisation would change the data's identity |
| Digest re-verified on every read | trusting the filename makes a corrupt blob indistinguishable from a good one |
| Corruption raises, never degrades to a miss | a cache that silently re-fetches stays corrupt and unnoticed |
| Atomic write: temp file, same directory, rename | a crash mid-write cannot leave a blob that fails its own digest |
| Never overwrites different bytes at one digest | under SHA-256 that is a collision or a caller bug; both warrant stopping |
| Path containment checked on the resolved path | `..` segments and symlink escapes both caught |
| Credential headers stripped before storage | |
| Root is a required argument | the legacy `OUT_DIR` meant importing decided where data went |

**Cache-only replay calls no transport at all.** The service does not even
invoke the transport factory, so a replay cannot silently fall back to the
network. A missing page is `CacheMissError`; a corrupt one is
`CacheCorruptionError`. Neither is a quiet re-fetch.

This is a *retrieval cache*, not the WP-06 immutable dataset snapshot. It holds
what was fetched; publishing anything is a later work package.

## 8. Pagination

Declared per endpoint: `SINGLE_PAGE`, `PAGE_SIZE`, `OFFSET_LIMIT`, `CURSOR`,
`NEXT_LINK`. Parameter names are fields, because they differ between APIs and
hard-coding one API's spelling is how a second source ends up forking the runner.

**Terminal means the source said stop.** Only three reasons are terminal:

| Terminal | Not terminal |
|---|---|
| `SINGLE_PAGE` | `MAX_PAGES_REACHED` |
| `EMPTY_PAGE` | `MAX_RECORDS_REACHED` |
| `NO_NEXT_CURSOR` | `REPEATED_CURSOR`, `REPEATED_REQUEST_KEY` |
| | `MALFORMED_CURSOR`, `ERROR` |

Running out of budget is not finishing, and neither is looping. A malformed
cursor is an error rather than an ending: absent means "no more pages",
malformed means "we cannot tell", and conflating them lets a broken response end
an endpoint early and look complete.

A repeated request key is detected independently of the cursor, so a page
counter that fails to advance is caught too.

## 9. The ClinPGx catalog

Data, not behaviour. Each endpoint declares its ID, path, required/optional
flag, pagination strategy, expected shape, records path, purpose, limitations,
and which legacy function it came from. Adding an endpoint means adding a
declaration; a test asserts the adapter and the service name no endpoint ID.

Three required (`gene_lookup`, `chemical_lookup`,
`guideline_annotation_by_pair`) and five optional.

What was ported and what was deliberately left behind is in
`docs/migration/clinpgx-probe-intent.md`. The short version: endpoints and query
spellings were ported; `get_first()`, `flatten_items()`, the fixed 0.6s sleep,
the module-level output directory, `quiet_404`, and every scientific
normalisation helper were not.

## 10. Response handling

**Bytes are hashed and stored before anything parses them.** A body that turns
out to be corrupt JSON still has its digest and its cache entry, so a failed run
remains diagnosable and replayable.

Then: content type checked against the declaration, JSON parsed, records
extracted from the declared container. Each failure is distinct
(`ContentTypeError`, `ResponseValidationError`, `ResponseShapeError`) and each
is recorded on the retrieval as a `ParseStatus`.

Records are handed on **exactly as received** - nothing renamed, normalised,
dropped or filled in.

## 11. Completeness

Computed in `build_acquisition_manifest`, from the endpoint outcomes, and
nowhere else. There is deliberately no `status` parameter: a caller that could
pass `COMPLETE` alongside a failed required endpoint would make every
completeness guarantee in this work package advisory.

| Condition | Status |
|---|---|
| a required endpoint is not `COMPLETE`, or its pagination is not terminal | `FAILED` |
| otherwise, an optional endpoint failed or was skipped | `COMPLETE_WITH_WARNINGS` |
| otherwise | `COMPLETE` |

`is_publishable` is true for the last two. A failed run keeps every raw response
it obtained - a failure worth diagnosing is worth keeping the evidence for - but
it is never publishable.

## 12. The determinism boundary

A run produces two views of itself, and keeping them apart is the point.

| Content manifest | Run manifest |
|---|---|
| request keys, endpoint IDs, page identities, raw digests, byte lengths | timestamps, attempt counts, cache hits, rate-limit headers, run ID |
| sorted, so arrival order does not matter | ordered as it happened |
| **hashed** | not hashed |

A network run and a cache-only replay of the same data differ in every
operational field and agree exactly on `content_hash`. If a timestamp or a retry
count reached the content hash, replay would produce a different identity for
identical bytes and the hash would answer no useful question.

## 13. CLI

`pgx-ingest-clinpgx` (`pgx.application.ingestion_cli:main`;
`scripts/ingest_clinpgx.py` is a thin wrapper).

| Subcommand | Network | Exit codes |
|---|---|---|
| `plan` | **no** | 0 |
| `acquire` | **yes** | 0, 1, 2 |
| `replay-cache` | **no** | 0, 1, 3 |
| `validate-cache` | **no** | 0, 4 |
| `inspect-run` | **no** | 0, 1 |

| Code | Meaning |
|---|---|
| 0 | success (warnings permitted) |
| 1 | the run finished and is not publishable |
| 2 | configuration or safety failure - the run did not start |
| 3 | a cache-only operation could not be satisfied |
| 4 | a manifest or cache failed validation |

`--cache-dir` is required everywhere; there is no default output directory.
Endpoints are selected by catalog ID only - a path or URL on the command line
would reach an endpoint nobody declared. No database is involved. Failure text
is redacted before it is written.

A test asserts the transport is built in exactly one place and that only
`acquire` requests it.

## 14. What WP-04 does not prove

| Claim | Status |
|---|---|
| Transport policy, retry, keys, cache, pagination, completeness, determinism | **Proven offline** - 214 new tests, no socket |
| The ClinPGx catalog matches the legacy probes' request intent | **Proven** by inventory tests against the probe source |
| That ClinPGx accepts `page`/`size`, returns records under `data`, needs no token | **BLOCKED** - no live call was made; the assumptions are listed in the probe-intent document |
| That a source may back a release (licensing, provenance) | **BLOCKED** - WP-05 |
| Persisting acquisitions | **Not started** - WP-06, WP-08 |

## 15. Handed to WP-05 and later

- source licensing and provenance policy, which decides `release_eligible`;
- immutable dataset snapshots built from a `COMPLETE` acquisition;
- canonical resolution of the multiple matches this adapter deliberately returns;
- the evidence store, and everything that turns a raw record into a claim.
