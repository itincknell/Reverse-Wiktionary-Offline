# Repository Layout

This repository owns the offline data and index build path. It intentionally
does not contain the public web/API service, web deployment manifests, Redis
session state, Nginx config, or serving smoke benchmarks.

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
runs/              Small committed offline run records.
data/              Local generated data; ignored by git.
```

## Qdrant Boundary

Keep Qdrant code that creates the offline artifact:

- local Qdrant container startup for indexing
- collection creation and deterministic point upserts
- payload index creation and verification
- optional collection quantization
- collection snapshot creation, download, and Blob upload

Do not keep Qdrant code that exists only to operate a deployed application:

- long-running web/API containers
- production Nginx or Redis config
- query-time HTTP routes and templates
- web smoke tests, route benchmarks, or UI state

The offline output is a Qdrant collection snapshot plus manifests. A separate
serving repository should decide how to restore and expose that snapshot.
