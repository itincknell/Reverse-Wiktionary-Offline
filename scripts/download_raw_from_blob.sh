#!/usr/bin/env bash
set -euo pipefail

# Download a raw dump run from Azure Blob Storage.
#
# By default this reads raw/latest.json and downloads the run it points to.

DEST_ROOT="data/raw"
RUN_ID=""
USE_LATEST=true
STORAGE_ACCOUNT=""
CONTAINER=""

usage() {
  sed -n '5,26p' "$0"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dest-root)
      DEST_ROOT="$2"
      shift 2
      ;;
    --run-id)
      RUN_ID="$2"
      USE_LATEST=false
      shift 2
      ;;
    --latest)
      USE_LATEST=true
      shift
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

POINTER_FILE="$(mktemp)"

if [ "$USE_LATEST" = true ]; then
  az storage blob download \
    --account-name "$STORAGE_ACCOUNT" \
    --container-name "$CONTAINER" \
    --name "raw/latest.json" \
    --file "$POINTER_FILE" \
    --auth-mode login \
    --output none

  RUN_ID="$(jq -r '.run_id' "$POINTER_FILE")"
  BLOB_PREFIX="$(jq -r '.prefix' "$POINTER_FILE")"
else
  if [ -z "$RUN_ID" ]; then
    echo "Missing required argument: --run-id"
    exit 1
  fi

  BLOB_PREFIX="raw/$RUN_ID"
fi

if [ -z "$RUN_ID" ] || [ "$RUN_ID" = "null" ]; then
  echo "Could not determine raw run id"
  exit 1
fi

RUN_DIR="$DEST_ROOT/$RUN_ID"
mkdir -p "$RUN_DIR"

echo "=== Downloading Raw Run ==="
echo "run id: $RUN_ID"
echo "source: $CONTAINER/$BLOB_PREFIX"
echo "destination: $RUN_DIR"

az storage blob list \
  --account-name "$STORAGE_ACCOUNT" \
  --container-name "$CONTAINER" \
  --prefix "$BLOB_PREFIX/" \
  --auth-mode login \
  --query "[].name" \
  --output tsv |
while IFS= read -r blob_name; do
  relative_path="${blob_name#"$BLOB_PREFIX/"}"
  target_path="$RUN_DIR/$relative_path"

  mkdir -p "$(dirname "$target_path")"

  az storage blob download \
    --account-name "$STORAGE_ACCOUNT" \
    --container-name "$CONTAINER" \
    --name "$blob_name" \
    --file "$target_path" \
    --auth-mode login \
    --output none
done

if [ ! -f "$RUN_DIR/wiktionary.jsonl" ]; then
  echo "Downloaded run is missing raw JSONL: $RUN_DIR/wiktionary.jsonl"
  exit 1
fi

rm -f "$DEST_ROOT/latest"
ln -s "$RUN_ID" "$DEST_ROOT/latest"
rm -f "$POINTER_FILE"

echo
echo "Download complete."
echo "latest symlink: $DEST_ROOT/latest -> $RUN_ID"
