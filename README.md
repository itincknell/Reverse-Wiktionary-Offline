# Reverse Wiktionary Offline

This repository is the offline half of Reverse Wiktionary. It builds the
semantic Qdrant index from Wiktionary source data and publishes the resulting
artifacts for a serving system to consume.

The sister repository is
[itincknell/Reverse-Wiktionary](https://github.com/itincknell/Reverse-Wiktionary),
which owns online serving and deployment.

## Scope

Reverse Wiktionary is split into two repositories:

- `Reverse-Wiktionary-Offline`: data acquisition, preprocessing, embedding,
  Qdrant index construction, snapshots, and run records.
- `Reverse-Wiktionary`: online search service, UI, runtime configuration, and
  deployment.

## Pipeline

```text
raw Wiktionary dump
  -> normalized JSONL shards
  -> sentence embeddings
  -> Qdrant collection
  -> Qdrant payload indexes
  -> Qdrant snapshot
  -> Azure Blob artifacts
```

The serving repository restores the snapshot advertised by `indexes/latest.json`.

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

## Documentation

- [Offline Indexing Design](docs/design_offline_indexing.md)
- [Data Contracts](docs/data_contracts.md)
- [Azure Runbook](docs/azure_runbook.md)
- [Repository Layout](docs/repo_layout.md)

## Design Principles

- GPU compute is ephemeral.
- Blob Storage is the durable artifact layer.
- Qdrant snapshots are the handoff artifact to serving systems.
- Offline indexing is independent of online serving.
- Metadata remains separate from embedding text.
- Scripts and manifests make pipeline state explicit.
