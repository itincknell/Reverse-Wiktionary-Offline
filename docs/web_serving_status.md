# Web Serving Status

This file tracks implementation state for the serving phase. Architecture and
API details live in `docs/design_web_serving.md`.

## Decisions

```text
reverse proxy: Nginx
server model: multiple sync FastAPI workers
model placement: one SentenceTransformer model copy per worker
session state: Redis with TTL
pagination: Load more button
language source: Qdrant facet at startup, taxonomy artifact when available
payload indexes: lang and pos keyword indexes created before serving
filtered retrieval: Qdrant ACORN, max_selectivity=1.0
serving memory: scalar int8 quantization with original vectors on disk
storage: stable host paths under /mnt/reverse-wiktionary
API: stable public /api/v1/search
```

## Implemented

- Shared POS vocabulary in `src/common/lexical_schema.py`.
- Processed serving metadata emitted by preprocessing.
- Payload-index create/check scripts under `scripts/qdrant/`.
- Search package under `src/search/` for request models, filter construction,
  query encoding, Qdrant search, and timing.
- Web package under `src/web/` for FastAPI routes, Redis session state, Jinja
  templates, static assets, and health checks.
- Language taxonomy builders under `src/taxonomy/` and `scripts/taxonomy/`.
- Docker/Nginx/Redis/Qdrant serving scaffolding under `deploy/web/`.
- Web smoke and benchmark scripts under `scripts/web/` and `scripts/azure/`.

## Current Retrieval Policy

```text
no filters: hnsw_ef=512
language or POS filters: hnsw_ef=512 + ACORN max_selectivity=1.0
diagnostic override: SEARCH_EXACT_FILTERED=true
serving collection: scalar int8 quantization, original vectors on disk
```

Live evaluation showed that plain filtered HNSW degraded semantic quality for
small filter subsets. ACORN restored filtered quality without application-side
post-filtering. Follow-up testing showed scalar int8 quantization preserved
manual retrieval quality while reducing Qdrant memory enough to test an
8 GiB beta host.

## Remaining Before Public Deployment

- Create and upload a quantized serving-ready Qdrant snapshot.
- Restore the quantized snapshot on `Standard_D2as_v5`.
- Run the smoke benchmark on the final VM size with one web worker.
- Configure Nginx for the production domain and TLS.
- Add request rate limiting.
- Confirm artifact upload paths for final benchmark logs.

## Operational Checks

```text
/health returns ok
/api/v1/search returns results
language and POS filters return expected subsets
Load more returns the next page
payload indexes exist for lang and pos
benchmark.json and benchmark_samples.json upload to logs/web_smoke/<run_id>/
```
