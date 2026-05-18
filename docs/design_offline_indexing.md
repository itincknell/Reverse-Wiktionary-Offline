# Offline Indexing Design

The offline pipeline builds the production Qdrant collection from Wiktionary
source data and exports the collection as a Blob-backed snapshot.

## Architecture

```text
raw Wiktionary JSONL
  -> preprocessing
  -> processed JSONL shards
  -> embedding generation
  -> Qdrant upsert/index
  -> Qdrant snapshot
  -> Azure Blob Storage
```

## Production Run

```text
raw_run_id: 20260506T173841Z
processed_run_id: 20260512T205400Z
embedding_run_id: 20260512T210221Z
index_run_id: 20260512T204458Z
collection_name: reverse_wiktionary_v1
model: sentence-transformers/all-mpnet-base-v2
```

```text
raw_records_processed: 10,575,029
processed_rows: 3,869,247
processed_shards: 78
embedding_batches: 30,258
embedding_elapsed_seconds: 19,810.39
embedding_rows_per_second: 195.3
vector_size: 768
snapshot_size_bytes: 13,601,704,960
```

Run record:

```text
runs/offline_embedding/20260512T204458Z.md
```

## Artifact Layout

Blob prefixes:

```text
raw/<run_id>/
raw/latest.json

processed/<run_id>/
processed/<run_id>/serving_metadata.json
processed/latest.json

code/<cloud_run_id>/

logs/<cloud_run_id>/

indexes/<run_id>/
indexes/latest.json
```

Local generated data lives under `data/` and is not committed.

## Raw Input

Source:

```text
https://kaikki.org/dictionary/raw-wiktextract-data.jsonl.gz
```

The raw dump is downloaded once per source run and uploaded to Blob Storage.
Subsequent batch jobs read raw artifacts from Blob unless an explicit refresh
is required.

## Preprocessing

Producer:

```text
src/embeddings/parse_wiktionary.py
```

The parser emits one normalized row per raw record when the record contains
usable semantic glosses. The row unit is:

```text
language + word + part of speech + aggregated semantic glosses
```

Current processed row schema: `v4`

Required fields:

```text
lang
word
pos
glosses
embedding_text
```

Optional fields:

```text
expansion
```

`embedding_text` is the joined gloss text. It does not include the word,
language, or part of speech. Those fields are stored as metadata and used for
display/filtering.

The parser filters low-value form/variant records, including `form_of`,
`alt_of`, alternative spellings, abbreviations, misspellings, obsolete senses,
and archaic senses. The parser keeps topical categories for future metadata
work; they are not suppression rules.

The preprocessing stage also writes:

```text
data/processed/<run_id>/serving_metadata.json
processed/<run_id>/serving_metadata.json
```

This artifact records available language values and part-of-speech counts for
the processed run. The web service fetches language values from Qdrant at
startup for serving truth, but the offline metadata remains the deterministic
pipeline contract and fallback.

## Embedding Generation

Producer:

```text
src/embeddings/generate_embeddings.py
```

The embedding generator:

```text
processed shards
  -> deterministic shard iteration
  -> SentenceTransformer batching
  -> bounded Qdrant upsert queue
  -> background Qdrant writer
  -> embedding manifest checkpoints
```

The production run used:

```text
model: sentence-transformers/all-mpnet-base-v2
batch_size: 128
queue_size: 4
distance: cosine
point_id_shard_size: 50,000
```

The generator checkpoints completed shards in a local embedding manifest. In
the recovered production run, the original wrapper failed before uploading the
embedding manifest to Blob; final metrics are preserved in the remote log and
run record.

## Qdrant Collection

One Qdrant collection stores all normalized rows.

Vector configuration:

```text
dimension: 768
distance: cosine
```

Payload fields:

```text
lang
word
pos
glosses
expansion
```

The serving layer supports filters on `lang` and `pos`.

Serving-ready Qdrant state requires payload indexes:

```text
lang: keyword
pos: keyword
```

These indexes are created offline before web deployment so filtered search does
not pay the index build cost during first public startup.

## Snapshot Recovery

Qdrant snapshots are the deployable output of the offline pipeline.

The original production wrapper timed out during snapshot creation with a 600
second HTTP timeout. The completed Qdrant collection was recovered manually by
rerunning snapshot creation with a 3600 second timeout and uploading:

```text
indexes/20260512T204458Z/
indexes/latest.json
```

The current snapshot path in Blob is recorded by:

```text
runs/offline_embedding/20260512T204458Z/artifacts/index_manifest.json
```

## Operational Constraints

- GPU VMs are batch compute only.
- Blob Storage is the durable artifact layer.
- A failed snapshot/upload must not require regenerating embeddings.
- Scripts must expose enough state to support manual recovery.
- Root-created VM artifacts can interfere with SSH recovery; VM jobs must
  converge on a single runtime user before the next production run.
- Serving deployment must use Qdrant storage outside the repository path.

## Deferred Work

- Global deduplication across duplicate `(lang, word, pos)` records.
- Quantization and on-disk vector evaluation.
- Automated restore test from `indexes/latest.json`.
- Final cost/performance report after web serving benchmarks.
