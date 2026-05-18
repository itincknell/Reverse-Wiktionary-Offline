# Web Serving Design

The web service serves natural-language reverse dictionary queries against the
production Qdrant collection built by the offline indexing pipeline.

## Architecture

```text
Azure Blob Qdrant snapshot
  -> serving VM restore
  -> Qdrant container
  -> FastAPI search/web service
  -> Nginx reverse proxy
  -> public UI and stable API
```

The serving stack does not own preprocessing, embedding generation, or index
construction. It restores or connects to an existing collection and serves
ranked lexical results.

## Locked Decisions

```text
reverse proxy: Nginx
server model: multiple sync FastAPI workers
model placement: one SentenceTransformer model copy per worker
session state: Redis with TTL
result navigation: Load more button
language list: fetched from Qdrant once at startup
payload indexes: created offline before serving deployment
production storage: stable host paths under /mnt/reverse-wiktionary
API stability: public stable v1 API
```

The query layer is replicated inside each FastAPI worker. There is no central
query queue. Each worker owns its model instance, Qdrant client, Redis client,
and search service objects.

## Source Layout

```text
src/search/        Qdrant query client and search orchestration.
src/web/           FastAPI app, templates, static assets, session state.
src/taxonomy/      Offline serving taxonomy builders and Glottolog matching.
deploy/web/        Web Dockerfile, compose files, Nginx config.
scripts/web/       Restore, deploy, health check, and smoke-test scripts.
scripts/qdrant/    Payload-index creation and verification scripts.
scripts/taxonomy/  Taxonomy artifact builders for processed runs.
```

`src/search/` owns Qdrant read/query behavior. `src/embeddings/` owns
preprocessing, embedding generation, and index construction.

## Stable API

```text
POST /api/v1/search
```

Request:

```json
{
  "query": "a book listing words and their meanings",
  "langs": [],
  "pos": [],
  "limit": 25,
  "offset": 0
}
```

Response:

```json
{
  "query": "a book listing words and their meanings",
  "filters": {
    "langs": [],
    "pos": []
  },
  "limit": 25,
  "offset": 0,
  "has_more": true,
  "timing_ms": {
    "embedding": 12.4,
    "qdrant": 31.8,
    "total": 47.2
  },
  "results": [
    {
      "word": "dictionary",
      "lang": "English",
      "pos": "noun",
      "score": 0.82,
      "glosses": ["A reference work listing words..."],
      "expansion": null
    }
  ]
}
```

Validation:

```text
query: required, trimmed, bounded string
langs: optional list; empty means all languages
pos: optional list; empty means all POS
limit: default 25, max 100
offset: default 0, non-negative
```

Filter semantics:

```text
multiple languages: OR
multiple POS values: OR
language filter AND POS filter
repeated values are normalized and deduplicated
no grouping
no reranking
```

## Web Routes

```text
GET  /
POST /ui/search
POST /ui/search/more
GET  /health
```

`/ui/*` routes are implementation routes for the HTMX/Jinja UI. The stable
programmatic contract is `/api/v1/search`.

## Query Path

```text
request
  -> validate query/limit/offset/filters
  -> encode query text
  -> build Qdrant filter
  -> search Qdrant
  -> normalize response payloads
  -> return JSON or render HTML partial
```

Search logs include route-level timings without recording raw query text:

```text
embedding_ms
qdrant_ms
search_total_ms
route_overhead_ms
route_total_ms
result_count
filter counts
```

Qdrant searches use query-time `hnsw_ef=512` by default. Searches with language
or POS filters additionally enable Qdrant ACORN traversal with
`max_selectivity=1.0`; this preserved filtered retrieval quality in live tests
without moving filtering or reranking into application code.

For diagnostics, `SEARCH_EXACT_FILTERED=true` switches filtered requests to
exact Qdrant search.

The web service uses the same embedding model family as the offline pipeline:

```text
sentence-transformers/all-mpnet-base-v2
```

## UI

UI stack:

```text
FastAPI
Jinja2
HTMX
plain CSS
```

UI behavior:

```text
default languages: all
default POS: all
initial page: no results
search execution: explicit Search button only
pagination: Load more button
gloss display: first three glosses, show-more toggle for the rest
expansion display: hidden by default, toggle when present
```

Result cards show:

```text
word
language
part of speech
glosses
expansion
```

Scores are included in the API response and hidden in the normal UI.

The language selector is a custom searchable multi-select populated from the
offline taxonomy artifact when available. The POS selector uses the shared
vocabulary from `src/common/lexical_schema.py`, narrowed at runtime to values
present in `serving_metadata.json`.

Language-tree metadata is built offline from processed `serving_metadata.json`
plus Glottolog release data. The web UI consumes that artifact when available
and falls back to the flat Qdrant language facet. The browse tree is deliberately
smaller than the full language universe: low-value singleton family paths are
pruned from the tree, while the flat taxonomy language list still powers
search-only matches, select-all, and submitted filter allowlists.

## Session State

Redis stores per-client UI state across multiple FastAPI workers.

```text
key: rw:session:<session_uuid>
ttl: 86400 seconds
```

Stored fields:

```text
selected_langs
selected_pos
latest_query
limit
next_offset
created_at_utc
updated_at_utc
```

Result bodies are not stored in Redis. "Load more" reruns the latest
query/filter state with the next offset.

## Deployment

Serving target:

```text
single Azure Linux VM
Docker Compose
Qdrant container
Redis container
FastAPI/web container
Nginx reverse proxy
managed disk for Qdrant storage
```

Initial FastAPI worker count:

```text
1 sync worker on 2-vCPU beta hosts
```

Worker count is a hardware and memory tuning decision because each worker loads
its own model copy.

Production host paths:

```text
/opt/reverse-wiktionary/app
/mnt/reverse-wiktionary/qdrant/storage
/mnt/reverse-wiktionary/redis/data
/mnt/reverse-wiktionary/logs
/mnt/reverse-wiktionary/snapshots
```

Production Qdrant storage must not live under the application repository.

## Restore Flow

```text
read indexes/latest.json
download indexes/<run_id>/manifest.json
download snapshot from indexes/<run_id>/snapshots/
restore Qdrant collection
verify lang and pos payload indexes
start web service
verify /health
```

## Benchmarking

Serving latency testing uses `scripts/web/benchmark_search.py` with a fixed
query set in `scripts/web/benchmark_queries.json`. The harness exercises API and UI
routes separately and reports latency percentiles, throughput, errors, and API
search timing fields. It can also write per-request samples for later review.

Remote smoke runs upload benchmark artifacts and the web log to:

```text
logs/web_smoke/<run_id>/benchmark.json
logs/web_smoke/<run_id>/benchmark_samples.json
logs/web_smoke/<run_id>/web.log
```

Cloud tuning should vary FastAPI worker count and request concurrency before
selecting the serving VM size.

Serving snapshots should be prepared offline with payload indexes on:

```text
lang: keyword
pos: keyword
```

May 2026 smoke benchmarks on the production collection before quantization
showed:

```text
Qdrant version: 1.18.0
points: 3,869,247
unfiltered API, concurrency 4: 38.19 rps, p95 120.65 ms
English-filtered API, concurrency 4: 23.18 rps, p95 233.97 ms
French-filtered API, concurrency 4: 27.64 rps, p95 203.02 ms
```

Serving memory was dominated by Qdrant: about 13.6 GiB RSS for the collection,
plus about 1.5 GiB for one web worker/model process. The T4 GPU was not used
for serving.

Scalar int8 quantization with original vectors on disk preserved manual result
quality and reduced Qdrant Docker memory to about 3.3 GiB during the follow-up
benchmark. This changed the beta target from a 32 GiB host to a lean CPU VM:

```text
target VM: Standard_D2as_v5
CPU/RAM: 2 vCPU / 8 GiB
disk: 256 GiB Standard SSD
estimated 24/7 cost: about $82/month including disk
```

The fallback for more memory headroom is `Standard_E2as_v5` with 2 vCPU /
16 GiB RAM.

Committed run summary:

```text
runs/web_serving/20260518-acorn-sizing.md
runs/web_serving/20260518-quantized-sizing.md
```

## Health Checks

`GET /health` reports:

```json
{
  "status": "ok",
  "qdrant": "ok",
  "redis": "ok",
  "collection": "reverse_wiktionary_v1",
  "model": "loaded",
  "vector_size": 768,
  "available_langs": 0,
  "available_pos": 9,
  "language_taxonomy_families": 0,
  "qdrant_hnsw_ef": 512,
  "qdrant_acorn_max_selectivity": 1.0,
  "search_exact_filtered": false
}
```

The endpoint returns non-200 when Qdrant, Redis, model loading, or the
collection check fails.

## Metrics

Per-search logs:

```text
route
query_length
langs_count
pos_count
limit
offset
embedding_ms
qdrant_ms
search_total_ms
route_overhead_ms
route_total_ms
result_count
has_more
```

Do not log full query text by default.

## Remaining Deployment Work

- Restore the serving snapshot on the final CPU VM.
- Run the web smoke benchmark on the final VM size.
- Configure Nginx for the production domain and TLS.
- Add rate limiting before public traffic.
- Keep result caching, query expansion, reranking, and infinite scroll out of
  the first deployment unless benchmark or user feedback justifies them.
