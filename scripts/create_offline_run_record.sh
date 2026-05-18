#!/usr/bin/env bash
set -euo pipefail

# Create a human-readable Markdown record for one cloud embedding run from Blob
# status/log/manifest artifacts.

STORAGE_ACCOUNT=""
CONTAINER=""
CLOUD_RUN_ID=""
OUTPUT_DIR="runs/offline_embedding"

usage() {
  cat <<'EOF'
Create a Markdown run record from cloud embedding Blob artifacts.

Required:
  --storage-account NAME
  --container NAME
  --cloud-run-id RUN_ID

Optional:
  --output-dir PATH
      Defaults to runs/offline_embedding.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --storage-account)
      STORAGE_ACCOUNT="$2"
      shift 2
      ;;
    --container)
      CONTAINER="$2"
      shift 2
      ;;
    --cloud-run-id)
      CLOUD_RUN_ID="$2"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

if [ -z "$STORAGE_ACCOUNT" ] || [ -z "$CONTAINER" ] || [ -z "$CLOUD_RUN_ID" ]; then
  echo "Missing required arguments: --storage-account, --container, --cloud-run-id"
  exit 1
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

status_file="$tmp_dir/status.json"
embedding_manifest="$tmp_dir/embedding_manifest.json"
snapshot_manifest="$tmp_dir/snapshot_manifest.json"
output_file="$OUTPUT_DIR/$CLOUD_RUN_ID.md"

download_required() {
  local blob_name="$1"
  local output_path="$2"

  az storage blob download \
    --account-name "$STORAGE_ACCOUNT" \
    --container-name "$CONTAINER" \
    --name "$blob_name" \
    --file "$output_path" \
    --auth-mode login \
    --overwrite \
    --output none
}

download_optional() {
  local blob_name="$1"
  local output_path="$2"

  az storage blob download \
    --account-name "$STORAGE_ACCOUNT" \
    --container-name "$CONTAINER" \
    --name "$blob_name" \
    --file "$output_path" \
    --auth-mode login \
    --overwrite \
    --output none >/dev/null 2>&1
}

json_value() {
  local file="$1"
  local query="$2"
  local fallback="${3:-}"

  if [ ! -f "$file" ]; then
    echo "$fallback"
    return
  fi

  jq -r "($query) as \$value | if \$value == null then \"$fallback\" else \$value end" "$file"
}

duration() {
  local started="$1"
  local finished="$2"

  if [ -z "$started" ] || [ -z "$finished" ] || [ "$finished" = "null" ]; then
    echo ""
    return
  fi

  python - "$started" "$finished" <<'PY'
from __future__ import annotations

import datetime as dt
import sys

started = dt.datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00"))
finished = dt.datetime.fromisoformat(sys.argv[2].replace("Z", "+00:00"))
seconds = int((finished - started).total_seconds())

hours, remainder = divmod(max(seconds, 0), 3600)
minutes, seconds = divmod(remainder, 60)
print(f"{hours}h {minutes}m {seconds}s")
PY
}

download_required "logs/$CLOUD_RUN_ID/status.json" "$status_file"

embedding_run_id="$(json_value "$status_file" '.embedding_run_id')"
embedding_manifest_path="$(json_value "$status_file" '.embedding_manifest_path')"
snapshot_prefix="$(json_value "$status_file" '.snapshot_prefix')"

if [ -n "$embedding_manifest_path" ] && [ "$embedding_manifest_path" != "null" ]; then
  download_optional "$embedding_manifest_path" "$embedding_manifest" || true
fi

if [ -n "$snapshot_prefix" ] && [ "$snapshot_prefix" != "null" ]; then
  download_optional "$snapshot_prefix/manifest.json" "$snapshot_manifest" || true
fi

status="$(json_value "$status_file" '.status')"
stage="$(json_value "$status_file" '.stage')"
started_at="$(json_value "$status_file" '.started_at_utc')"
finished_at="$(json_value "$status_file" '.finished_at_utc')"
run_duration="$(duration "$started_at" "$finished_at")"

rows_embedded="$(json_value "$embedding_manifest" '.metrics.rows_embedded')"
batches_completed="$(json_value "$embedding_manifest" '.metrics.batches_completed')"
shards_completed="$(json_value "$embedding_manifest" '.metrics.shards_completed')"
snapshot_size_bytes="$(json_value "$snapshot_manifest" '.snapshot_size_bytes')"

mkdir -p "$OUTPUT_DIR"

cat > "$output_file" <<EOF
# Offline Embedding Run: $CLOUD_RUN_ID

## Summary

\`\`\`text
status: $status
stage: $stage
cloud_run_id: $CLOUD_RUN_ID
embedding_run_id: $embedding_run_id
started_at_utc: $started_at
finished_at_utc: $finished_at
duration: $run_duration
\`\`\`

## Configuration

\`\`\`text
storage_account: $(json_value "$status_file" '.storage_account')
container: $(json_value "$status_file" '.container')
processed_run_id: $(json_value "$status_file" '.processed_run_id')
collection_name: $(json_value "$status_file" '.collection_name')
model_name: $(json_value "$status_file" '.model_name')
prepare_processed_if_missing: $(json_value "$status_file" '.prepare_processed_if_missing')
allow_raw_download: $(json_value "$status_file" '.allow_raw_download')
\`\`\`

## Blob Artifacts

\`\`\`text
log_path: $(json_value "$status_file" '.log_path')
status_path: $(json_value "$status_file" '.status_path')
embedding_manifest_path: $embedding_manifest_path
snapshot_prefix: $snapshot_prefix
indexes_latest_pointer: indexes/latest.json
\`\`\`

## Metrics

\`\`\`text
qdrant_points_count: $(json_value "$status_file" '.qdrant_points_count')
qdrant_indexed_vectors_count: $(json_value "$status_file" '.qdrant_indexed_vectors_count')
rows_embedded: $rows_embedded
batches_completed: $batches_completed
shards_completed: $shards_completed
snapshot_size_bytes: $snapshot_size_bytes
\`\`\`

## Notes

\`\`\`text

\`\`\`

## Follow-Ups

\`\`\`text

\`\`\`
EOF

echo "run record: $output_file"
