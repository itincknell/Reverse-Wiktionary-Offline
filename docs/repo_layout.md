# Repository Layout

Current shape:

```text
src/common/        Shared file, manifest, logging, and run-id helpers.
src/embeddings/    Offline data preparation, embedding, Qdrant indexing code.
scripts/           Local operational scripts.
scripts/azure/     Azure VM bootstrap and remote execution scripts.
scripts/qdrant/    Qdrant index management scripts.
scripts/taxonomy/  Serving taxonomy artifact scripts.
scripts/web/       Web deployment, smoke, and benchmark scripts.
deploy/compose/    Local/runtime service compose files.
deploy/web/        Web app Dockerfile, Compose files, and Nginx config.
docs/              Data contracts and operational runbooks.
runs/              Small committed run records and benchmark summaries.
data/              Local generated data; ignored by git.
```

## Web Deployment Additions

Add serving code beside the embedding pipeline:

```text
src/web/           FastAPI app, templates, static assets, session state.
src/search/        Qdrant client/query code shared by API and CLI checks.
src/taxonomy/      Optional serving taxonomy builders and Glottolog matching.
deploy/web/        Web app Dockerfile, app service/container deployment files.
scripts/web/       Web deployment and smoke-test scripts.
```

`src/search/` should own Qdrant read/query behavior. `src/embeddings/` should
remain focused on preprocessing, embedding generation, and index construction.
`src/taxonomy/` is serving-support code: it builds filter metadata from the
processed run and is kept out of the core embedding path.

## Defer

- Monorepo-style `apps/` split.
- Moving `scripts/azure/` into `deploy/`.
- Packaging the offline pipeline as a separate installable distribution.
