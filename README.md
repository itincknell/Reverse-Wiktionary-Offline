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

## Current Index

The active production snapshot is selected by:

```text
indexes/latest.json
```

Run-specific details live in [offline run records](runs/offline_embedding/).

## Documentation

- [Offline Indexing Design](docs/design_offline_indexing.md)
- [Data Contracts](docs/data_contracts.md)
- [Azure Runbook](docs/azure_runbook.md)
- [Web Repo Handoff](docs/web_repo_handoff.md)
- [Repository Layout](docs/repo_layout.md)

## Design Principles

- GPU compute is ephemeral.
- Blob Storage is the durable artifact layer.
- Qdrant snapshots are the handoff artifact to serving systems.
- Offline indexing is independent of online serving.
- Metadata remains separate from embedding text.
- Scripts and manifests make pipeline state explicit.
