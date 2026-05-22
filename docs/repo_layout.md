# Repository Layout

This repository owns the offline data and index build path. Its serving sister
repo is `itincknell/Reverse-Wiktionary`.

```text
src/common/        Shared file, manifest, logging, and run-id helpers.
src/embeddings/    Preprocessing, embedding generation, Qdrant writes, snapshots.
src/taxonomy/      Optional processed-language metadata and taxonomy builders.
scripts/           Local and cloud batch orchestration scripts.
scripts/azure/     Azure VM bootstrap and remote offline job helpers.
scripts/qdrant/    Qdrant collection payload-index and quantization helpers.
scripts/taxonomy/  Processed metadata and language taxonomy artifact scripts.
compose/           Local Qdrant compose file for offline indexing.
docs/              Offline contracts, design notes, and runbooks.
runs/              Small committed run records for offline jobs and snapshot validation.
data/              Local generated data; ignored by git.
```

## Repository Boundary

`Reverse-Wiktionary-Offline` contains Qdrant code for index construction:
local container startup, deterministic point upserts, payload index preparation,
snapshot creation, and Blob upload.

`Reverse-Wiktionary` contains the deployed application surface: API routes,
query-time request schemas, UI assets, and runtime configuration.

The offline output is a Qdrant collection snapshot plus manifests.
`Reverse-Wiktionary` decides how to restore and expose that snapshot.
