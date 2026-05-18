#!/usr/bin/env bash
set -euo pipefail

# Rerun only the Qdrant snapshot/upload stage on an existing Azure VM.

RESOURCE_GROUP=""
VM_NAME=""
STORAGE_ACCOUNT=""
CONTAINER=""
COLLECTION_NAME="reverse_wiktionary_v1"
VM_REPO_DIR="/opt/reverse-wiktionary"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
TIMEOUT_SECONDS=3600
POLL_INTERVAL_SECONDS=5
REUSE_EXISTING=false
START_QDRANT=true

usage() {
  cat <<'EOF'
Rerun only the Qdrant snapshot/upload stage on an existing Azure VM.

Required:
  --resource-group NAME
  --vm-name NAME
  --storage-account NAME
  --container NAME

Optional:
  --collection-name NAME
      Defaults to reverse_wiktionary_v1.
  --vm-repo-dir PATH
      Defaults to /opt/reverse-wiktionary.
  --run-id RUN_ID
      Defaults to current UTC timestamp.
  --timeout-seconds SECONDS
      Defaults to 3600.
  --poll-interval-seconds SECONDS
      Defaults to 5.
  --reuse-existing
      Upload the newest local snapshot for the run instead of creating one.
  --no-start-qdrant
      Assume Qdrant is already running on the VM.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --resource-group)
      RESOURCE_GROUP="$2"
      shift 2
      ;;
    --vm-name)
      VM_NAME="$2"
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
    --collection-name)
      COLLECTION_NAME="$2"
      shift 2
      ;;
    --vm-repo-dir)
      VM_REPO_DIR="$2"
      shift 2
      ;;
    --run-id)
      RUN_ID="$2"
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
    --no-start-qdrant)
      START_QDRANT=false
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

if [ -z "$RESOURCE_GROUP" ] || [ -z "$VM_NAME" ]; then
  echo "Missing required arguments: --resource-group and --vm-name"
  exit 1
fi

if [ -z "$STORAGE_ACCOUNT" ] || [ -z "$CONTAINER" ]; then
  echo "Missing required arguments: --storage-account and --container"
  exit 1
fi

echo "=== Starting VM ==="
az vm start \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME"

echo
echo "=== Submitting Snapshot Upload Job ==="
az vm run-command invoke \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME" \
  --command-id RunShellScript \
  --scripts @scripts/azure/start_qdrant_snapshot_remote.sh \
  --parameters \
    storageAccount="$STORAGE_ACCOUNT" \
    container="$CONTAINER" \
    collectionName="$COLLECTION_NAME" \
    repoDir="$VM_REPO_DIR" \
    runId="$RUN_ID" \
    timeoutSeconds="$TIMEOUT_SECONDS" \
    pollIntervalSeconds="$POLL_INTERVAL_SECONDS" \
    reuseExisting="$REUSE_EXISTING" \
    startQdrant="$START_QDRANT"

echo
echo "=== Snapshot Artifacts ==="
echo "run id: $RUN_ID"
echo "snapshot prefix: $CONTAINER/indexes/$RUN_ID"
echo "log: $CONTAINER/logs/snapshot-$RUN_ID/remote_snapshot_job.log"
echo "status: $CONTAINER/logs/snapshot-$RUN_ID/status.json"
