#!/usr/bin/env bash
set -euo pipefail

# Backfill serving_metadata.json for older processed Blob runs by reading the
# processed JSONL shards. This does not parse raw Wiktionary data.

STORAGE_ACCOUNT=""
CONTAINER=""
RUN_ID=""
USE_LATEST=true
WORK_ROOT="data/processed"
UPLOAD=false
PYTHON_BIN="${PYTHON:-python3}"

usage() {
  cat <<'EOF'
Backfill serving_metadata.json from processed shard blobs.

Required:
  --storage-account NAME
  --container NAME

Optional:
  --run-id RUN_ID
      Defaults to processed/latest.json.
  --work-root PATH
      Defaults to data/processed.
  --upload
      Upload serving_metadata.json back to processed/<run_id>/.
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
    --run-id)
      RUN_ID="$2"
      USE_LATEST=false
      shift 2
      ;;
    --work-root)
      WORK_ROOT="$2"
      shift 2
      ;;
    --upload)
      UPLOAD=true
      shift
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

if [ -z "$STORAGE_ACCOUNT" ]; then
  echo "Missing required argument: --storage-account"
  exit 1
fi

if [ -z "$CONTAINER" ]; then
  echo "Missing required argument: --container"
  exit 1
fi

POINTER_FILE="$(mktemp)"
trap 'rm -f "$POINTER_FILE"' EXIT

if [ "$USE_LATEST" = true ]; then
  az storage blob download \
    --account-name "$STORAGE_ACCOUNT" \
    --container-name "$CONTAINER" \
    --name "processed/latest.json" \
    --file "$POINTER_FILE" \
    --auth-mode login \
    --output none

  RUN_ID="$(jq -r '.run_id' "$POINTER_FILE")"
fi

if [ -z "$RUN_ID" ] || [ "$RUN_ID" = "null" ]; then
  echo "Could not determine processed run id"
  exit 1
fi

BLOB_PREFIX="processed/$RUN_ID"
RUN_DIR="$WORK_ROOT/$RUN_ID"
mkdir -p "$RUN_DIR"

echo "=== Downloading Processed Manifest and Shards ==="
echo "run id: $RUN_ID"

az storage blob list \
  --account-name "$STORAGE_ACCOUNT" \
  --container-name "$CONTAINER" \
  --prefix "$BLOB_PREFIX/" \
  --auth-mode login \
  --query "[?ends_with(name, '.jsonl') || ends_with(name, 'manifest.json')].name" \
  --output tsv |
while IFS= read -r blob_name; do
  relative_path="${blob_name#"$BLOB_PREFIX/"}"
  target_path="$RUN_DIR/$relative_path"

  if [ -f "$target_path" ]; then
    continue
  fi

  mkdir -p "$(dirname "$target_path")"
  az storage blob download \
    --account-name "$STORAGE_ACCOUNT" \
    --container-name "$CONTAINER" \
    --name "$blob_name" \
    --file "$target_path" \
    --auth-mode login \
    --output none
done

"$PYTHON_BIN" -m src.taxonomy.build_serving_metadata \
  --processed-dir "$RUN_DIR" \
  --output "$RUN_DIR/serving_metadata.json"

if [ "$UPLOAD" = true ]; then
  az storage blob upload \
    --account-name "$STORAGE_ACCOUNT" \
    --container-name "$CONTAINER" \
    --name "$BLOB_PREFIX/serving_metadata.json" \
    --file "$RUN_DIR/serving_metadata.json" \
    --overwrite true \
    --auth-mode login
fi
