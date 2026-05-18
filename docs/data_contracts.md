# Data Contracts

This project stores pipeline artifacts as immutable timestamped runs. A run ID
uses UTC timestamp format:

```text
YYYYMMDDTHHMMSSZ
```

Consumers read manifests rather than inferring state from directory contents.
Unknown JSON fields are reserved for compatible extension.

## Local Artifact Layout

Local development uses real directories plus a `latest` symlink:

```text
data/raw/<run_id>/
data/raw/latest -> <run_id>

data/processed/<run_id>/
  serving_metadata.json
data/processed/latest -> <run_id>

data/embeddings/<run_id>/
  manifest.json
  vectors/
    shard_00000.npz
    shard_00000.json
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
  manifest.json
  vectors/
    shard_00000.npz
    shard_00000.json

code/<run_id>/

indexes/<run_id>/
indexes/latest.json
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

Current row schema: `v5`

Each line in `shard_*.jsonl` is one JSON object.

Required fields:

- `lang`: Source language as a string.
- `word`: Dictionary headword as a string.
- `pos`: Part of speech as a string.
- `glosses`: Ordered list of cleaned gloss strings.
- `embedding_text`: String sent to the embedding model.

Optional fields:

- `expansion`: Display text from Wiktionary head templates when available.

Compatibility:

- Consumers ignore unknown fields.
- Producers bump `SCHEMA_VERSION` before removing or renaming fields.
- `embedding_text` is the model input contract; presentation fields are stored
  separately.

Wiktionary result links are computed by serving clients from existing payload
fields. The offline collection does not store full URLs or URL-safe title
copies.

URL construction contract:

- Page title input: `word`
- Language-section input: `lang`
- Page path component: replace spaces with underscores, then percent-encode for
  a MediaWiki path segment.
- Section fragment: trim/collapse heading whitespace, replace spaces with
  underscores, then percent-encode for a URL fragment.
- Preferred validation source: MediaWiki `action=parse&prop=tocdata`, matching
  top-level sections where `line == lang` and using `linkAnchor || anchor`.

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
- `serving_metadata_path`: Local path to the processed metadata artifact.
- `shards`: Per-shard metadata.

## Processed Metadata

Producer: `src/embeddings/parse_wiktionary.py`

Path:

```text
data/processed/<run_id>/serving_metadata.json
processed/<run_id>/serving_metadata.json
```

Current schema: `v1`

`serving_metadata.json` is the processed-run metadata artifact used for audit,
taxonomy generation, and downstream artifact consumers.

Important fields:

- `schema_version`: Metadata schema version.
- `processed_run_id`: Processed run identifier.
- `created_at_utc`: Metadata creation time.
- `language_count`: Number of language values represented.
- `languages`: Objects with `lang` and `rows`.
- `pos`: Objects with `pos` and `rows`.

This metadata records language/POS values and row counts for the processed run.
Qdrant payloads remain the source of truth for the snapshotted collection.

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
- `tree`: `family -> branch -> languages` hierarchy for downstream consumers.
- `languages`: Flat enriched language records; this remains the complete
  language universe for search, filtering, and audit/debugging.

Glottolog paths may contain arbitrary-depth family/group ancestors. The taxonomy
builder reduces those paths to stable display buckets:

```text
Family = Glottolog root family or isolate bucket
Branch = curated display branch, with second-ancestor fallback
Language = Wiktionary language label
```

Unmatched, unclassifiable, artificial, bookkeeping, speech-register, and other
non-language labels are retained in the flat records but excluded from the
tree. Strict line-shaped families with one branch and one language are also
pruned from the visible tree. These pruned languages remain in the flat language
records.

`language_taxonomy_unmatched.json` stores high-priority unmatched and
review-needed labels, sorted by row count. `language_taxonomy_report.json`
stores aggregate match counts, top families, and the top unmatched candidates.

The override map is the audit trail for Wiktionary labels with reviewed
taxonomy assignments, including pseudo-language labels such as `Translingual`.

## Embedding Manifest

Producer: `src/embeddings/generate_embeddings.py`

Current schema: `v2`

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
- `config`: Batch size, queue size, point ID stride, and distance metric.
- `metrics`: Rows, batches, and shards completed.
- `shards`: Per-shard completion records, including vector artifact paths when
  available.

Each vector shard artifact stores:

- `vectors`: `float32` NumPy array of encoded vectors.
- `point_ids`: Deterministic Qdrant point IDs for the rows.
- `source_row_indices`: Source row indices within the processed shard.

The `.json` sidecar records source shard, row count, vector size, and point ID
range. Qdrant upsert and snapshot recovery should restart from these vector
artifacts when they exist rather than re-running GPU embedding from processed
text.

Resume behavior depends on the manifest's completed shard list and the vector
artifact directory. When changing model, processed input, collection, or point
ID stride, use a new embedding run.

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
- `points_count`: Point count reported by Qdrant before snapshot upload.
- `indexed_vectors_count`: Indexed-vector count reported by Qdrant.
- `vector_size`: Collection vector size.
- `distance`: Collection distance metric.
- `vectors_on_disk`: Whether original vectors are stored on disk.
- `on_disk_payload`: Whether payload storage is on disk.
- `quantization_config`: Qdrant quantization configuration captured from the
  collection.
- `payload_indexes`: Qdrant payload schema captured from the collection.
- `timeout_seconds`: Snapshot create/download timeout used by the run.
- `poll_interval_seconds`: Poll interval used while waiting for snapshot metadata.
- `reused_existing_snapshot`: Whether the run uploaded an already downloaded snapshot.
- `snapshot_path`: Local snapshot path.
- `snapshot_size_bytes`: Downloaded snapshot size.

## Qdrant Payload Indexes

Producer: `scripts/qdrant/create_payload_indexes.sh`

Verifier: `scripts/qdrant/check_payload_indexes.sh`

The snapshotted collection includes keyword payload indexes for:

```text
lang
pos
```

These indexes support filtered vector search after restore. They are created as
part of offline artifact preparation before the Qdrant snapshot is written.

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
quantizing
waiting_for_qdrant
snapshotting
uploading_snapshot
uploading_embedding_manifest
succeeded
```
