# Reverse Wiktionary Design

Reverse Wiktionary is a semantic lexical search system. The offline pipeline
builds a Qdrant vector index from Wiktionary data; the online service will serve
natural-language reverse dictionary queries against that index.

The system is intentionally split into two execution profiles:

```text
offline indexing:
  raw Wiktionary dump
  -> normalized JSONL shards
  -> sentence embeddings
  -> Qdrant collection
  -> Qdrant snapshot
  -> Azure Blob artifacts

online serving:
  Qdrant snapshot
  -> serving VM
  -> Qdrant + web/API service
  -> public search UI
```

## Current State

```text
raw_run_id: 20260506T173841Z
processed_run_id: 20260512T205400Z
index_run_id: 20260512T204458Z
collection_name: reverse_wiktionary_v1
model: sentence-transformers/all-mpnet-base-v2
rows_indexed: 3,869,247
vector_size: 768
snapshot_size_bytes: 13,601,704,960
```

The production index snapshot is stored in Azure Blob Storage under:

```text
indexes/20260512T204458Z/
indexes/latest.json
```

## Design Documents

- [Offline Indexing Design](docs/design_offline_indexing.md)
- [Web Serving Design](docs/design_web_serving.md)
- [Data Contracts](docs/data_contracts.md)
- [Azure Runbook](docs/azure_runbook.md)
- [Repository Layout](docs/repo_layout.md)

## Design Principles

- Keep GPU compute ephemeral.
- Treat Blob Storage as the durable artifact layer.
- Treat Qdrant snapshots as deployable index artifacts.
- Keep online serving independent of offline indexing.
- Keep metadata separate from embedding text.
- Prefer explicit scripts and manifests over implicit state.
- Benchmark before increasing serving infrastructure size.
