#!/usr/bin/env bash
set -euo pipefail

# Build taxonomy artifacts from the processed serving metadata stored in Blob.

STORAGE_ACCOUNT=""
CONTAINER=""
RUN_ID=""
USE_LATEST=true
WORK_ROOT="data/processed"
GLOTTOLOG_VERSION="5.3"
UPLOAD=false

usage() {
  cat <<'EOF'
Build taxonomy artifacts from Blob processed serving metadata.

Required:
  --storage-account NAME
  --container NAME

Optional:
  --run-id RUN_ID
      Defaults to processed/latest.json.
  --work-root PATH
      Defaults to data/processed.
  --glottolog-version VERSION
      Defaults to 5.3.
  --upload
      Upload taxonomy artifacts back to processed/<run_id>/.
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
    --glottolog-version)
      GLOTTOLOG_VERSION="$2"
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
SERVING_METADATA="$RUN_DIR/serving_metadata.json"

mkdir -p "$RUN_DIR"

echo "=== Downloading Serving Metadata ==="
echo "run id: $RUN_ID"
echo "source: $CONTAINER/$BLOB_PREFIX/serving_metadata.json"
echo "destination: $SERVING_METADATA"

if ! az storage blob download \
  --account-name "$STORAGE_ACCOUNT" \
  --container-name "$CONTAINER" \
  --name "$BLOB_PREFIX/serving_metadata.json" \
  --file "$SERVING_METADATA" \
  --auth-mode login \
  --output none
then
  echo "serving_metadata.json not found; backfilling from processed shard blobs."
  scripts/taxonomy/backfill_serving_metadata_from_blob.sh \
    --storage-account "$STORAGE_ACCOUNT" \
    --container "$CONTAINER" \
    --run-id "$RUN_ID" \
    --work-root "$WORK_ROOT" \
    --upload
fi

scripts/taxonomy/build_language_taxonomy.sh \
  --serving-metadata "$SERVING_METADATA" \
  --output-dir "$RUN_DIR" \
  --glottolog-version "$GLOTTOLOG_VERSION"

if [ "$UPLOAD" = true ]; then
  echo "=== Uploading Taxonomy Artifacts ==="
  for artifact in \
    language_taxonomy.json \
    language_taxonomy_unmatched.json \
    language_taxonomy_report.json
  do
    az storage blob upload \
      --account-name "$STORAGE_ACCOUNT" \
      --container-name "$CONTAINER" \
      --name "$BLOB_PREFIX/$artifact" \
      --file "$RUN_DIR/$artifact" \
      --overwrite true \
      --auth-mode login
  done
fi

echo
echo "Taxonomy artifacts:"
echo "  $RUN_DIR/language_taxonomy.json"
echo "  $RUN_DIR/language_taxonomy_unmatched.json"
echo "  $RUN_DIR/language_taxonomy_report.json"
