# ClinPGx probe intent: what was ported, and what was not

| Field | Value |
|---|---|
| Document ID | `DOC-MIG-004` |
| Sources | `clinpgx_probe.py` (357 lines), `clinpgx_probe_v2.py` (697 lines) |
| Method | **Static reading only.** Neither probe was executed and no ClinPGx call was made. |
| Result | `pgx/ingestion/clinpgx/catalog.py` |

> The probes were exploratory tools and they did their job: they discovered
> which endpoints exist and which query parameters they accept. That knowledge
> is worth keeping. Their *retrieval behaviour* is not, and this document
> separates the two so the distinction survives the people who made it.

---

## 1. What the probes actually did

| Property | `clinpgx_probe.py` | `clinpgx_probe_v2.py` |
|---|---|---|
| Base URL | `https://api.clinpgx.org/v1` | same |
| OpenAPI | `openapi.json`, `swagger/openapi.json` | `openapi.json` |
| HTTP client | `requests` | `requests` |
| Timeout | 30s | 35s |
| Between calls | none | `time.sleep(0.6)`, unconditional |
| Retry | none | none |
| Pagination | **none** | **none** |
| Cache | none | none |
| Output | printed | `clinpgx_outputs_v2/`, module-level `OUT_DIR` |
| 404 handling | printed | `quiet_404=True` - swallowed |
| Result selection | first success wins | `get_first()` |

`clinpgx_probe.py` additionally guessed parameter names: for each endpoint it
tried `q`, `query`, `search`, `term`, `name`, `symbol`, `id`, `identifier`, plus
whatever the OpenAPI document declared, and kept the first combination that
returned anything. That is reasonable for discovery and unusable for
acquisition, so only its *conclusions* were carried across.

## 2. Endpoints and queries, ported

| Legacy call | Query keys | Catalog endpoint | Required |
|---|---|---|---|
| `resolve_gene` | `symbol`, `view` | `gene_lookup` | yes |
| `resolve_chemical` | `name`, `view` | `chemical_lookup` | yes |
| `query_guideline_annotations` set 1 | `relatedGenes.accessionId`, `relatedChemicals.accessionId`, `view` | `guideline_annotation_by_pair` | yes |
| `query_guideline_annotations` set 2 | `relatedGenes.accessionId`, `view` | `guideline_annotation_by_gene` | no |
| `query_guideline_annotations` set 3 | `relatedChemicals.accessionId`, `view` | `guideline_annotation_by_chemical` | no |
| `query_variant_annotations_by_gene` | `location.genes.symbol`, `view` | `variant_annotation_by_gene` | no |
| `report_pair` | path `/report/pair/{first}/{second}/{type}`, `view` | `pair_report` | no |
| `connected_objects` | path `/report/connectedObjects/{id}/{type}` | `connected_objects` | no |

The parameter spellings are ported **verbatim**, dots included
(`relatedGenes.accessionId`, `location.genes.symbol`). They look like a filter
syntax the API defines; nothing about them was normalised or "tidied", because a
tidied parameter is a different request.

The probe merged all three guideline parameter sets and deduplicated the result
by ID. The three are separate endpoints here: merging records from different
queries into one set is a **resolution decision**, and resolution is WP-07.

## 3. Defects not ported

Each of these worked, which is why each is easy to reintroduce. Each is pinned
by a test in `tests/unit/ingestion/test_clinpgx_catalog.py`.

### 3.1 `get_first()` - first-result selection

```python
def get_first(items):
    for item in items:
        if isinstance(item, dict):
            return item
```

`resolve_gene("CYP2C19")` returned whichever record the API happened to list
first and treated it as *the* gene. That is an identity decision made silently,
with no record of the alternatives and no way to review it. The adapter returns
every match; choosing among them is WP-07.

### 3.2 `flatten_items()` - guessing the container

```python
for key in ["data", "items", "results", "content", "objects", "resources"]:
    if key in payload: ...
return [payload]          # <- nothing matched
```

The final line is the problem. An error object, an HTML page, a rate-limit
notice - anything at all - became a list of one record, and the probe reported
success. The catalog declares `records_path` per endpoint and a mismatch is
`ResponseShapeError`.

### 3.3 No pagination

Neither probe paged. One request per endpoint, and whatever came back was the
answer. For a collection endpoint that silently collects an unknown fraction of
the data. Pagination is now declared per endpoint, and an endpoint that does not
reach a terminal state fails the run.

### 3.4 `time.sleep(0.6)` before every request

An unconditional delay is simultaneously too slow (when the server is fine) and
too fast (when it is rate-limiting). Replaced by bounded retry with exponential
backoff, jitter, and `Retry-After` honoured when the server sends it.

### 3.5 `OUT_DIR` - a module-level output path

Importing the probe decided where data went, and two runs in one process could
not use different locations. The cache root is now a required argument
everywhere: constructor, service and CLI.

### 3.6 `quiet_404=True`

A missing record and an empty result became indistinguishable. 404 is now a
`PermanentTransportError` - not retried, and not silent.

### 3.7 Scientific normalisation in the retrieval path

`summarize_annotation`, `make_mvp_edge_row`, `html_to_text`, `rank_key`,
`dedupe_by_id`, and the variant ranking heuristic that kept the "best" 30 of N
records. Every one is a judgement about what source text means. Acquisition
stores bytes; interpretation is WP-07 onward.

## 4. Assumptions that need live confirmation

Written down because they are assumptions, and because the next person will
otherwise have to re-derive which parts were verified.

| Assumption | Basis | How to confirm |
|---|---|---|
| Collections page with `page` and `size` | Not observed. The probes never paged, so no pagination parameter was ever seen. | One live call with `page=1&size=2`; compare against `page=2`. |
| Records live under `data` | `flatten_items` tried `data` first, and the MVP outputs are consistent with it. | Read one live response. |
| `/report/pair` and `/report/connectedObjects` return a single page | They are pre-joined reports, so a page is plausible; unverified. | One live call each. |
| `view=base` is the right view | Every probe call passed it. Whether a fuller view is needed is a scientific question. | WP-05/WP-06. |
| No API token is required | The probes sent none and worked. | A live call without a token. |
| `PAIR_RESULT_TYPES` casing | The probe tried twelve spellings (`guidelineAnnotation`, `GuidelineAnnotation`, …) and kept whichever returned anything, so the correct casing is genuinely unknown. | Read the OpenAPI document. |

**The pagination assumption deliberately errs toward failure.** Collection
endpoints are declared `PAGE_SIZE`. If the API does not accept those parameters,
the run fails loudly on the first live call. Declaring `SINGLE_PAGE` instead
would be the more dangerous guess: it would silently accept page one of a paged
endpoint as the whole endpoint, which is exactly the legacy defect.

## 5. What a live run will settle

A single supervised `pgx-ingest-clinpgx acquire` against one gene/drug pair
would confirm or refute every row in section 4. Until then A15 (live
connectivity) is **BLOCKED**, and no claim in this document about how the API
*behaves* rests on anything but a reading of the probe source.
