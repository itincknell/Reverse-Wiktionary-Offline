#!/usr/bin/env bash
set -euo pipefail

# Upload a local raw dump run to Azure Blob Storage.
#
# Blob layout:
#   raw/<run_id>/...
#   raw/latest.json

ROOT_DIR="data/raw"
RUN_ID=""
STORAGE_ACCOUNT=""
CONTAINER=""

usage() {
  sed -n '5,22p' "$0"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --root-dir)
      ROOT_DIR="$2"
      shift 2
      ;;
    --run-id)
      RUN_ID="$2"
      shift 2
      ;;
    --storage-account)
      STORAGE_ACCOUNT="$2"
      shift 2
      ;;
    --container)
      CONTAINER="$2"
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

if [ -z "$STORAGE_ACCOUNT" ]; then
  echo "Missing required argument: --storage-account"
  exit 1
fi

if [ -z "$CONTAINER" ]; then
  echo "Missing required argument: --container"
  exit 1
fi

if [ -z "$RUN_ID" ]; then
  if [ ! -L "$ROOT_DIR/latest" ]; then
    echo "Missing --run-id and latest symlink not found: $ROOT_DIR/latest"
    exit 1
  fi

  RUN_ID="$(basename "$(readlink "$ROOT_DIR/latest")")"
fi

RUN_DIR="$ROOT_DIR/$RUN_ID"
BLOB_PREFIX="raw/$RUN_ID"
POINTER_FILE="$(mktemp)"
UPDATED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

if [ ! -d "$RUN_DIR" ]; then
  echo "Raw run directory not found: $RUN_DIR"
  exit 1
fi

cat > "$POINTER_FILE" <<EOF
{
  "stage": "raw",
  "run_id": "$RUN_ID",
  "prefix": "$BLOB_PREFIX",
  "manifest_path": "$BLOB_PREFIX/metadata.json",
  "updated_at_utc": "$UPDATED_AT"
}
EOF

echo "=== Uploading Raw Run ==="
echo "run id: $RUN_ID"
echo "source: $RUN_DIR"
echo "destination: $CONTAINER/$BLOB_PREFIX"

az storage blob upload-batch \
  --account-name "$STORAGE_ACCOUNT" \
  --destination "$CONTAINER" \
  --source "$RUN_DIR" \
  --destination-path "$BLOB_PREFIX" \
  --overwrite true \
  --auth-mode login

az storage blob upload \
  --account-name "$STORAGE_ACCOUNT" \
  --container-name "$CONTAINER" \
  --name "raw/latest.json" \
  --file "$POINTER_FILE" \
  --overwrite true \
  --auth-mode login

rm -f "$POINTER_FILE"

echo
echo "Upload complete."
echo "latest pointer: $CONTAINER/raw/latest.json"
