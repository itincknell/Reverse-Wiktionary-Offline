#!/usr/bin/env bash

set -euo pipefail

RAW_ROOT="data/raw"
PROCESSED_ROOT="data/processed"
RAW_LATEST_LINK="$RAW_ROOT/latest"
TARGET_FILE="wiktionary.jsonl"

if [ ! -e "$RAW_LATEST_LINK" ]; then
  echo "Latest raw dump link not found: $RAW_LATEST_LINK"
  echo "Run the download script first."
  exit 1
fi

if [ ! -d "$RAW_LATEST_LINK" ]; then
  echo "Latest raw link does not point to a directory: $RAW_LATEST_LINK"
  exit 1
fi

INPUT="$RAW_LATEST_LINK/$TARGET_FILE"

if [ ! -f "$INPUT" ]; then
  echo "Expected input file not found: $INPUT"
  exit 1
fi

SOURCE_RUN_ID="$(basename "$(readlink "$RAW_LATEST_LINK")")"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"

RUN_DIR="$PROCESSED_ROOT/$RUN_ID"
OUTDIR="$RUN_DIR"
MANIFEST="$RUN_DIR/manifest.json"

rm -rf "$RUN_DIR"
mkdir -p "$OUTDIR"

python ./src/embeddings/parse_wiktionary.py \
  --input "$INPUT" \
  --output-root "$PROCESSED_ROOT" \
  --manifest "$MANIFEST" \
  --run-id "$RUN_ID"

echo "=== Run Info ==="
echo "source run id: $SOURCE_RUN_ID"
echo "process run id: $RUN_ID"
echo "input: $INPUT"
echo "output dir: $OUTDIR"
echo "manifest: $MANIFEST"

echo "=== Manifest Summary ==="
jq '{
  records_processed,
  rows_written,
  num_shards,
  shard_size,
  language_count,
  pos_counts,
  serving_metadata_path,
  expansion_ratio: (.rows_written / .records_processed)
}' "$MANIFEST"

echo "=== Shards ==="
ls -lh "$OUTDIR"/shard_*.jsonl

echo "=== Rows Per Shard ==="
jq -r '.shards[] | "\(.path): \(.rows) rows"' "$MANIFEST"

echo "=== Sample Output ==="
head -n 5 "$OUTDIR"/shard_00000.jsonl | jq . || true
