#!/usr/bin/env bash
set -euo pipefail

# Create a Qdrant collection snapshot, download it locally, and optionally upload
# it to Azure Blob Storage using the project blob artifact layout.
#
# Required:
#   --collection-name NAME
#
# Optional:
#   --qdrant-url URL
#       Defaults to QDRANT_URL or http://localhost:6333.
#
#   --output-root PATH
#       Local root directory for snapshot artifacts.
#       Defaults to data/indexes.
#
#   --run-id RUN_ID
#       Snapshot run identifier.
#       Defaults to current UTC timestamp.
#
#   --storage-account NAME
#       Azure Storage account for upload.
#
#   --container NAME
#       Azure Blob container for upload.
#
#   --blob-prefix PATH
#       Destination prefix inside the container.
#       Defaults to indexes/<run_id>.
#
#   --timeout-seconds SECONDS
#       Snapshot create/download timeout.
#       Defaults to 3600.
#
#   --poll-interval-seconds SECONDS
#       Poll interval while waiting for snapshot metadata.
#       Defaults to 5.
#
#   --reuse-existing
#       Upload the newest local snapshot in data/indexes/<run_id>/snapshots
#       instead of creating a new Qdrant snapshot.
#
#   --upload
#       Upload the downloaded snapshot directory to Azure Blob Storage and
#       update indexes/latest.json to point at this run.
#
# Examples:
#   ./scripts/store_qdrant_snapshot.sh --collection-name reverse_wiktionary_test
#
#   ./scripts/store_qdrant_snapshot.sh \
#     --collection-name reverse_wiktionary_v1 \
#     --upload \
#     --storage-account mystorageacct \
#     --container reverse-wiktionary

QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
COLLECTION_NAME=""
OUTPUT_ROOT="data/indexes"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
STORAGE_ACCOUNT=""
CONTAINER=""
BLOB_PREFIX=""
TIMEOUT_SECONDS=3600
POLL_INTERVAL_SECONDS=5
REUSE_EXISTING=false
UPLOAD=false

write_remote_stage() {
  local stage="$1"

  if [ -n "${REVWIK_STAGE_FILE:-}" ]; then
    cat > "$REVWIK_STAGE_FILE" <<EOF
stage=$stage
embedding_run_id=${REVWIK_EMBEDDING_RUN_ID:-$RUN_ID}
EOF
  fi
}

usage() {
  cat <<'EOF'
Create a Qdrant collection snapshot, download it locally, and optionally upload
it to Azure Blob Storage using the project artifact layout.

Required:
  --collection-name NAME

Optional:
  --qdrant-url URL
      Defaults to QDRANT_URL or http://localhost:6333.
  --output-root PATH
      Defaults to data/indexes.
  --run-id RUN_ID
      Defaults to current UTC timestamp.
  --storage-account NAME
      Azure Storage account for upload.
  --container NAME
      Azure Blob container for upload.
  --blob-prefix PATH
      Defaults to indexes/<run_id>.
  --timeout-seconds SECONDS
      Defaults to 3600.
  --poll-interval-seconds SECONDS
      Defaults to 5.
  --reuse-existing
      Upload the newest local snapshot in data/indexes/<run_id>/snapshots.
  --upload
      Upload the snapshot directory and update indexes/latest.json.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --qdrant-url)
      QDRANT_URL="$2"
      shift 2
      ;;
    --collection-name)
      COLLECTION_NAME="$2"
      shift 2
      ;;
    --output-root)
      OUTPUT_ROOT="$2"
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
    --blob-prefix)
      BLOB_PREFIX="$2"
      shift 2
      ;;
    --timeout-seconds)
      TIMEOUT_SECONDS="$2"
      shift 2
      ;;
    --poll-interval-seconds)
      POLL_INTERVAL_SECONDS="$2"
      shift 2
      ;;
    --reuse-existing)
      REUSE_EXISTING=true
      shift
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

if [ -z "$COLLECTION_NAME" ]; then
  echo "Missing required argument: --collection-name"
  usage
  exit 1
fi

if [ -z "$BLOB_PREFIX" ]; then
  BLOB_PREFIX="indexes/$RUN_ID"
fi

if [ "$UPLOAD" = true ]; then
  if [ -z "$STORAGE_ACCOUNT" ]; then
    echo "Missing required argument for upload: --storage-account"
    exit 1
  fi

  if [ -z "$CONTAINER" ]; then
    echo "Missing required argument for upload: --container"
    exit 1
  fi
fi

RUN_DIR="$OUTPUT_ROOT/$RUN_ID"
SNAPSHOT_DIR="$RUN_DIR/snapshots"
MANIFEST="$RUN_DIR/manifest.json"
LATEST_POINTER="$RUN_DIR/latest.json"

mkdir -p "$SNAPSHOT_DIR"

echo "=== Qdrant Health Check ==="
curl -fsS "$QDRANT_URL/healthz" > /dev/null

echo "=== Creating Qdrant Snapshot ==="
echo "qdrant url: $QDRANT_URL"
echo "collection: $COLLECTION_NAME"
echo "run id: $RUN_ID"
echo "snapshot dir: $SNAPSHOT_DIR"
echo "timeout seconds: $TIMEOUT_SECONDS"
echo "poll interval seconds: $POLL_INTERVAL_SECONDS"

SNAPSHOT_PATH=""

if [ "$REUSE_EXISTING" = true ]; then
  SNAPSHOT_PATH="$(find "$SNAPSHOT_DIR" -maxdepth 1 -type f | sort | tail -n 1)"

  if [ -z "$SNAPSHOT_PATH" ]; then
    echo "No existing snapshot found in: $SNAPSHOT_DIR"
    exit 1
  fi

  echo "Reusing existing snapshot: $SNAPSHOT_PATH"
else
  write_remote_stage "snapshotting"
  SNAPSHOT_PATH="$(
python - <<PY
from pathlib import Path
import sys

sys.path.insert(0, str(Path.cwd()))

from src.embeddings.utils.qdrant_snapshot import (
    QdrantSnapshotConfig,
    create_and_download_snapshot,
)

path = create_and_download_snapshot(
    QdrantSnapshotConfig(
        qdrant_url="$QDRANT_URL",
        collection_name="$COLLECTION_NAME",
        output_dir=Path("$SNAPSHOT_DIR"),
        timeout_seconds=int("$TIMEOUT_SECONDS"),
        poll_interval_seconds=float("$POLL_INTERVAL_SECONDS"),
    )
)

print(path)
PY
)"
fi

SNAPSHOT_SIZE_BYTES="$(wc -c < "$SNAPSHOT_PATH" | tr -d ' ')"
CREATED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

cat > "$MANIFEST" <<EOF
{
  "run_id": "$RUN_ID",
  "stage": "qdrant_snapshot",
  "created_at_utc": "$CREATED_AT",
  "qdrant_url": "$QDRANT_URL",
  "collection_name": "$COLLECTION_NAME",
  "blob_prefix": "$BLOB_PREFIX",
  "timeout_seconds": $TIMEOUT_SECONDS,
  "poll_interval_seconds": $POLL_INTERVAL_SECONDS,
  "reused_existing_snapshot": $REUSE_EXISTING,
  "snapshot_path": "$SNAPSHOT_PATH",
  "snapshot_size_bytes": $SNAPSHOT_SIZE_BYTES
}
EOF

cat > "$LATEST_POINTER" <<EOF
{
  "stage": "indexes",
  "run_id": "$RUN_ID",
  "prefix": "$BLOB_PREFIX",
  "manifest_path": "$BLOB_PREFIX/manifest.json",
  "updated_at_utc": "$CREATED_AT"
}
EOF

echo
echo "=== Snapshot Created ==="
echo "snapshot: $SNAPSHOT_PATH"
echo "manifest: $MANIFEST"
du -sh "$SNAPSHOT_PATH"

if [ "$UPLOAD" = true ]; then
  echo
  echo "=== Uploading Snapshot Artifacts to Azure Blob ==="
  echo "storage account: $STORAGE_ACCOUNT"
  echo "container: $CONTAINER"
  echo "blob prefix: $BLOB_PREFIX"
  write_remote_stage "uploading_snapshot"

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
    --name "indexes/latest.json" \
    --file "$LATEST_POINTER" \
    --overwrite true \
    --auth-mode login

  echo
  echo "Upload complete."
fi

echo
echo "=== Done ==="
echo "local run dir: $RUN_DIR"
if [ "$UPLOAD" = true ]; then
  echo "blob path: $CONTAINER/$BLOB_PREFIX"
  echo "latest pointer: $CONTAINER/indexes/latest.json"
fi
