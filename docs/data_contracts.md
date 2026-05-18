# Data Contracts

This project stores pipeline artifacts as immutable timestamped runs. A run ID
uses UTC timestamp format:

```text
YYYYMMDDTHHMMSSZ
```

Consumers should use manifests rather than directory inspection and ignore
unknown JSON fields.

## Local Artifact Layout

Local development uses real directories plus a `latest` symlink:

```text
data/raw/<run_id>/
data/raw/latest -> <run_id>

data/processed/<run_id>/
  serving_metadata.json
data/processed/latest -> <run_id>

data/embeddings/<run_id>/
data/embeddings/latest -> <run_id>

data/indexes/<run_id>/
```

The local `latest` symlink is not uploaded to Blob Storage.

## Blob Artifact Layout

Azure Blob Storage uses immutable run prefixes plus small JSON pointer blobs:

```text
raw/<run_id>/
raw/latest.json

processed/<run_id>/
  serving_metadata.json
  language_taxonomy.json
  language_taxonomy_unmatched.json
  language_taxonomy_report.json
processed/latest.json

embeddings/<run_id>/

code/<run_id>/

indexes/<run_id>/
indexes/latest.json

logs/web_smoke/<run_id>/
```

Blob `latest.json` pointer files replace local symlinks without duplicating
large shard or snapshot files.

## Latest Pointer Schema

Current schema: `v1`

Example:

```json
{
  "stage": "processed",
  "run_id": "20260511T183000Z",
  "prefix": "processed/20260511T183000Z",
  "manifest_path": "processed/20260511T183000Z/manifest.json",
  "updated_at_utc": "2026-05-11T18:45:00Z"
}
```

Fields:

- `stage`: Artifact stage. Expected values include `raw`, `processed`, and `indexes`.
- `run_id`: Timestamped run identifier.
- `prefix`: Blob prefix containing the immutable run artifacts.
- `manifest_path`: Blob path to the run manifest or metadata file.
- `updated_at_utc`: UTC timestamp when this pointer was written.

## Raw Run

Producer: `scripts/download_wiktionary_dump.sh`

Local layout:

```text
data/raw/<run_id>/
  raw-wiktextract-data.jsonl.gz
  wiktionary.jsonl
  metadata.json
```

Blob layout:

```text
raw/<run_id>/
  raw-wiktextract-data.jsonl.gz
  wiktionary.jsonl
  metadata.json

raw/latest.json
```

`metadata.json` fields:

- `source_url`: Source URL for the downloaded dump.
- `updated_at_utc`: UTC timestamp when local metadata was written.
- `compressed_path`: Local path to the compressed dump.
- `uncompressed_path`: Local path to the decompressed JSONL dump.
- `compressed_size_bytes`: Compressed file size.
- `uncompressed_size_bytes`: Decompressed file size.

## Processed Rows

Producer: `src/embeddings/parse_wiktionary.py`

Backfill producer for older processed runs:
`scripts/taxonomy/backfill_serving_metadata_from_blob.sh`

Consumers:

- `src/embeddings/generate_embeddings.py`
- `src/embeddings/utils/shard_reader.py`

Current row schema: `v4`

Each line in `shard_*.jsonl` is one JSON object.

Required fields:

- `lang`: Source language as a string.
- `word`: Dictionary headword as a string.
- `pos`: Part of speech as a string.
- `glosses`: Ordered list of cleaned gloss strings.
- `embedding_text`: String sent to the embedding model.

Optional fields:

- `expansion`: Display text from Wiktionary head templates when available.

Compatibility rules:

- Consumers must ignore unknown fields.
- Producers bump `SCHEMA_VERSION` before removing or renaming fields.
- `embedding_text` is the model input contract; presentation fields must not
  be reconstructed by consumers.

## Preprocessing Manifest

Producer: `src/embeddings/parse_wiktionary.py`

Path:

```text
data/processed/<run_id>/manifest.json
processed/<run_id>/manifest.json
```

Important fields:

- `run_id`: Processed run identifier.
- `created_at_utc`: Manifest creation time.
- `schema_version`: Processed row schema version.
- `input_path`: Local input path used by the run.
- `output_dir`: Local output directory.
- `shard_size`: Maximum rows per shard.
- `num_shards`: Number of shard files written.
- `records_processed`: Raw JSONL records read.
- `rows_written`: Normalized rows emitted.
- `skipped_bad_json`: Malformed JSON lines skipped.
- `skipped_non_object`: Non-object JSON values skipped.
- `skipped_empty_lines`: Empty input lines skipped.
- `language_count`: Number of language values emitted into processed rows.
- `pos_counts`: Row counts by allowed part-of-speech value.
- `serving_metadata_path`: Local path to the serving metadata artifact.
- `shards`: Per-shard metadata.

## Processed Serving Metadata

Producer: `src/embeddings/parse_wiktionary.py`

Path:

```text
data/processed/<run_id>/serving_metadata.json
processed/<run_id>/serving_metadata.json
```

Current schema: `v1`

Important fields:

- `schema_version`: Serving metadata schema version.
- `processed_run_id`: Processed run identifier.
- `created_at_utc`: Metadata creation time.
- `language_count`: Number of language values represented.
- `languages`: Objects with `lang` and `rows`.
- `pos`: Objects with `pos` and `rows`.

The web service uses Qdrant as serving truth at startup, but this metadata is
the offline contract for expected filter values and row counts.

## Language Taxonomy

Producer: `scripts/taxonomy/build_language_taxonomy_from_blob.sh`

Input:

```text
processed/<run_id>/serving_metadata.json
data/reference/glottolog/<version>/glottolog_languoid.csv
src/taxonomy/language_taxonomy_overrides.json
```

Outputs:

```text
processed/<run_id>/language_taxonomy.json
processed/<run_id>/language_taxonomy_unmatched.json
processed/<run_id>/language_taxonomy_report.json
```

Current schema: `v1`

`language_taxonomy.json` stores:

- `source`: Processed run and Glottolog source metadata.
- `tree`: UI-ready `family -> branch -> languages` browse hierarchy.
- `languages`: Flat enriched language records; this remains the complete
  language universe for search, select-all, and audit/debugging.

Glottolog paths may contain arbitrary-depth family/group ancestors. The serving
UI reduces those paths to stable display buckets:

```text
Family = Glottolog root family or isolate bucket
Branch = curated display branch, with second-ancestor fallback
Language = Wiktionary language label
```

Unmatched, unclassifiable, artificial, bookkeeping, speech-register, and other
non-language labels are retained in the flat records but excluded from the
filter tree. Strict line-shaped families with one branch and one language are
also pruned from the visible tree. These pruned languages remain searchable in
the language filter and participate in select-all.

With no language filter, all Qdrant records remain eligible. Once any language
filter is selected, the API receives an explicit language allowlist assembled
from the full flat language set, not only the visible browse tree.

`language_taxonomy_unmatched.json` stores high-priority unmatched and
review-needed labels, sorted by row count. `language_taxonomy_report.json`
stores aggregate match counts, top families, and the top unmatched candidates.

The override map is the audit trail for Wiktionary labels that should not rely
on fuzzy matching, including pseudo-language labels such as `Translingual`.

## Embedding Manifest

Producer: `src/embeddings/generate_embeddings.py`

Path:

```text
data/embeddings/<run_id>/manifest.json
embeddings/<run_id>/manifest.json
```

Important fields:

- `run_id`: Embedding run identifier.
- `stage`: `embedding`.
- `processed_run_id`: Processed input run identifier.
- `processed_dir`: Local processed input path.
- `model`: Embedding model name and vector size.
- `qdrant`: Qdrant URL and collection name.
- `config`: Batch size, queue size, point ID stride, distance metric.
- `metrics`: Rows, batches, and shards completed.
- `shards`: Per-shard completion records.

Resume behavior depends on the manifest's completed shard list. When changing
model, processed input, collection, or point ID stride, use a new embedding run.

## Qdrant Snapshot Manifest

Producer: `scripts/store_qdrant_snapshot.sh`

Path:

```text
data/indexes/<run_id>/manifest.json
indexes/<run_id>/manifest.json
```

Important fields:

- `run_id`: Snapshot run identifier.
- `stage`: `qdrant_snapshot`.
- `created_at_utc`: Manifest creation time.
- `qdrant_url`: Qdrant HTTP endpoint used to create the snapshot.
- `collection_name`: Qdrant collection snapshotted.
- `blob_prefix`: Blob prefix used when uploaded.
- `timeout_seconds`: Snapshot create/download timeout used by the run.
- `poll_interval_seconds`: Poll interval used while waiting for snapshot metadata.
- `reused_existing_snapshot`: Whether the run uploaded an already downloaded snapshot.
- `snapshot_path`: Local snapshot path.
- `snapshot_size_bytes`: Downloaded snapshot size.

## Serving-Ready Qdrant Indexes

Producer: `scripts/qdrant/create_payload_indexes.sh`

Verifier: `scripts/qdrant/check_payload_indexes.sh`

The serving collection must have keyword payload indexes for:

```text
lang
pos
```

These indexes support filtered vector search for the stable public API and web
UI. Serving snapshots should be created after the indexes exist.

## Web Smoke Benchmark Artifacts

Producer: `scripts/web/benchmark_search.py`

Remote smoke runners upload durable benchmark records to:

```text
logs/web_smoke/<run_id>/benchmark.json
logs/web_smoke/<run_id>/benchmark_samples.json
logs/web_smoke/<run_id>/web.log
```

`benchmark.json` stores the aggregate report, including route set, language/POS
filters, concurrency, throughput, latency percentiles, error counts, and API
timing fields. `benchmark_samples.json` stores one record per request for
later inspection.

## Azure VM Job Status

Producer: `scripts/azure/run_embedding_job_remote.sh`

Path:

```text
logs/<cloud_run_id>/status.json
```

Important fields:

- `cloud_run_id`: Azure launcher run identifier.
- `embedding_run_id`: Embedding/index/snapshot run identifier, once allocated.
- `started_at_utc`: Job start time.
- `updated_at_utc`: Last status write time.
- `finished_at_utc`: Terminal completion time, or `null` while running.
- `stage`: Current stage.
- `status`: `running`, `succeeded`, or `failed`.
- `exit_code`: Process exit code for the latest status write.
- `collection_name`: Qdrant collection being built.
- `model_name`: SentenceTransformer model name.
- `qdrant_status`: Current collection status when Qdrant is reachable.
- `qdrant_points_count`: Current point count when Qdrant is reachable.
- `qdrant_indexed_vectors_count`: Current indexed-vector count when reachable.
- `qdrant_update_queue_length`: Current Qdrant update queue length when reachable.
- `log_path`: Blob path to the streamed remote job log.
- `embedding_manifest_path`: Blob path to the embedding manifest, once known.
- `snapshot_prefix`: Blob prefix for uploaded Qdrant snapshot artifacts.

Expected stage values include:

```text
starting
preparing_repo
installing_dependencies
ensuring_processed_input
downloading_raw
downloading_raw_from_kaikki
uploading_raw
normalizing
uploading_processed
starting_qdrant
embedding
creating_payload_indexes
snapshotting
uploading_snapshot
uploading_embedding_manifest
succeeded
```

## Azure VM Job Contract

Launcher: `scripts/run_embeddings_on_azure_vm.sh`

Remote job: `scripts/azure/run_embedding_job_remote.sh`

Bootstrap script: `scripts/azure/bootstrap_embedding_vm.sh`

Snapshot-only rerun: `scripts/snapshot_qdrant_on_azure_vm.sh`

The VM is expected to have:

- Azure CLI authenticated with access to the storage account.
- Docker and Docker Compose available.
- `jq` available.
- Python 3 with `venv` available.

The launcher uploads a lightweight repository archive to:

```text
code/<run_id>/repo.tar.gz
```

The launcher submits a short Azure Run Command. That command extracts the repo
archive into `/opt/reverse-wiktionary`, or a custom path passed with
`--vm-repo-dir`, starts the real job as a background systemd unit, and exits.

The background job creates `.venv`, installs `requirements.txt`, periodically
uploads `logs/<cloud_run_id>/status.json`, and periodically uploads
`logs/<cloud_run_id>/remote_embedding_job.log`.

By default, the VM job reads `processed/latest.json`, downloads that processed
run, and fails if processed input is missing.

Optional fallback flags:

- `--prepare-processed-if-missing`: If processed input is missing, download
  `raw/latest.json`, preprocess the raw dump, upload the new processed run, and
  continue embedding.
- `--allow-raw-download`: If raw input is also missing from Blob Storage,
  download the Kaikki dump, upload it to `raw/<run_id>/`, preprocess it, upload
  the new processed run, and continue embedding.

After processed input is ready, the VM job generates embeddings, snapshots
Qdrant, uploads `indexes/<run_id>/`, and updates `indexes/latest.json`.

If embedding succeeds but snapshot/upload fails, rerun only the snapshot stage
with `scripts/snapshot_qdrant_on_azure_vm.sh`.

Snapshot-only reruns write:

```text
logs/snapshot-<run_id>/status.json
logs/snapshot-<run_id>/remote_snapshot_job.log
```
