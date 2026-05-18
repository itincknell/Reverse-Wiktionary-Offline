#!/usr/bin/env bash
set -euo pipefail

# Ensure data/processed/latest exists for an embedding job.
#
# Default behavior is strict: require processed artifacts in Blob Storage.
# Optional fallback behavior can prepare processed shards from raw Blob data, and
# optionally download raw data from Kaikki when Blob does not have it.

STORAGE_ACCOUNT=""
CONTAINER=""
PROCESSED_RUN_ID="latest"
PREPARE_IF_MISSING=false
ALLOW_RAW_DOWNLOAD=false

write_remote_stage() {
  local stage="$1"

  if [ -n "${REVWIK_STAGE_FILE:-}" ]; then
    cat > "$REVWIK_STAGE_FILE" <<EOF
stage=$stage
embedding_run_id=${REVWIK_EMBEDDING_RUN_ID:-}
EOF
  fi
}

usage() {
  cat <<'EOF'
Ensure data/processed/latest exists for an embedding job.

Required:
  --storage-account NAME
  --container NAME

Optional:
  --processed-run-id RUN_ID
      Defaults to latest.
  --prepare-if-missing
      Prepare processed shards from raw Blob data when processed is missing.
  --allow-raw-download
      Allow Kaikki download if raw Blob artifacts are also missing.
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
    --processed-run-id)
      PROCESSED_RUN_ID="$2"
      shift 2
      ;;
    --prepare-if-missing)
      PREPARE_IF_MISSING=true
      shift
      ;;
    --allow-raw-download)
      ALLOW_RAW_DOWNLOAD=true
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

download_processed() {
  if [ "$PROCESSED_RUN_ID" = "latest" ]; then
    ./scripts/download_processed_from_blob.sh \
      --storage-account "$STORAGE_ACCOUNT" \
      --container "$CONTAINER" \
      --latest
  else
    ./scripts/download_processed_from_blob.sh \
      --storage-account "$STORAGE_ACCOUNT" \
      --container "$CONTAINER" \
      --run-id "$PROCESSED_RUN_ID"
  fi
}

echo "=== Ensuring Processed Input ==="
echo "processed run id: $PROCESSED_RUN_ID"
write_remote_stage "ensuring_processed_input"

if download_processed; then
  echo "Processed input is ready."
  exit 0
fi

if [ "$PREPARE_IF_MISSING" != true ]; then
  echo "Processed input was not found, and fallback preparation is disabled."
  exit 1
fi

echo
echo "Processed input not found. Preparing processed input from raw data."
write_remote_stage "downloading_raw"

if ! ./scripts/download_raw_from_blob.sh \
  --storage-account "$STORAGE_ACCOUNT" \
  --container "$CONTAINER" \
  --latest; then

  if [ "$ALLOW_RAW_DOWNLOAD" != true ]; then
    echo "Raw input was not found in Blob, and Kaikki download fallback is disabled."
    exit 1
  fi

  echo
  echo "Raw input not found in Blob. Downloading from Kaikki."
  write_remote_stage "downloading_raw_from_kaikki"
  ./scripts/download_wiktionary_dump.sh --download-new

  write_remote_stage "uploading_raw"
  ./scripts/upload_raw_to_blob.sh \
    --storage-account "$STORAGE_ACCOUNT" \
    --container "$CONTAINER"
fi

echo
echo "=== Running Preprocessing ==="
write_remote_stage "normalizing"
./scripts/run_parse_wiktionary.sh

echo
echo "=== Uploading Prepared Processed Run ==="
write_remote_stage "uploading_processed"
./scripts/upload_processed_to_blob.sh \
  --storage-account "$STORAGE_ACCOUNT" \
  --container "$CONTAINER"

echo
echo "Processed input is ready."
