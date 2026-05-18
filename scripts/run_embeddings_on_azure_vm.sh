#!/usr/bin/env bash
set -euo pipefail

# Start an existing Azure VM and submit the offline embedding job as a
# background systemd unit. The VM is left running by default so the job can
# continue after Azure Run Command returns. Deallocate the VM only after the
# Blob status artifact reports a terminal state.

RESOURCE_GROUP=""
VM_NAME=""
STORAGE_ACCOUNT=""
CONTAINER=""
PROCESSED_RUN_ID="latest"
COLLECTION_NAME="reverse_wiktionary_v1"
MODEL_NAME="sentence-transformers/all-mpnet-base-v2"
VM_REPO_DIR="/opt/reverse-wiktionary"
JOB_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
CODE_ARCHIVE_BLOB="code/$JOB_RUN_ID/repo.tar.gz"
LOCAL_ARCHIVE=""
PREPARE_PROCESSED_IF_MISSING=false
ALLOW_RAW_DOWNLOAD=false

usage() {
  cat <<'EOF'
Package the repo, upload it to Blob, and submit the offline embedding job to an
existing Azure VM as a background systemd unit.

Required:
  --resource-group NAME
  --vm-name NAME
  --storage-account NAME
  --container NAME

Optional:
  --processed-run-id RUN_ID
      Defaults to latest.
  --collection-name NAME
      Defaults to reverse_wiktionary_v1.
  --model-name NAME
      Defaults to sentence-transformers/all-mpnet-base-v2.
  --vm-repo-dir PATH
      Defaults to /opt/reverse-wiktionary.
  --prepare-processed-if-missing
      Prepare processed shards from raw Blob data when processed is missing.
  --allow-raw-download
      Allow Kaikki download if both processed and raw Blob artifacts are missing.
  --leave-running
      Accepted for compatibility; the background job always requires the VM to stay running.
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
    --processed-run-id)
      PROCESSED_RUN_ID="$2"
      shift 2
      ;;
    --collection-name)
      COLLECTION_NAME="$2"
      shift 2
      ;;
    --model-name)
      MODEL_NAME="$2"
      shift 2
      ;;
    --vm-repo-dir)
      VM_REPO_DIR="$2"
      shift 2
      ;;
    --leave-running)
      # Accepted for compatibility with the earlier synchronous launcher.
      shift
      ;;
    --prepare-processed-if-missing)
      PREPARE_PROCESSED_IF_MISSING=true
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

if [ -z "$RESOURCE_GROUP" ] || [ -z "$VM_NAME" ]; then
  echo "Missing required arguments: --resource-group and --vm-name"
  exit 1
fi

if [ -z "$STORAGE_ACCOUNT" ] || [ -z "$CONTAINER" ]; then
  echo "Missing required arguments: --storage-account and --container"
  exit 1
fi

cleanup() {
  if [ -n "$LOCAL_ARCHIVE" ]; then
    rm -f "$LOCAL_ARCHIVE"
  fi
}

trap cleanup EXIT

LOCAL_ARCHIVE="$(mktemp).tar.gz"

echo "=== Packaging Repo ==="
echo "archive blob: $CONTAINER/$CODE_ARCHIVE_BLOB"

tar -czf "$LOCAL_ARCHIVE" \
  --exclude ".git" \
  --exclude ".DS_Store" \
  --exclude "data" \
  --exclude "revwik" \
  --exclude ".venv" \
  --exclude "qdrant_storage" \
  --exclude "out" \
  --exclude "__pycache__" \
  .

az storage blob upload \
  --account-name "$STORAGE_ACCOUNT" \
  --container-name "$CONTAINER" \
  --name "$CODE_ARCHIVE_BLOB" \
  --file "$LOCAL_ARCHIVE" \
  --overwrite true \
  --auth-mode login

echo "=== Starting VM ==="
az vm start \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME"

echo
echo "=== Submitting Remote Embedding Job ==="
az vm run-command invoke \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME" \
  --command-id RunShellScript \
  --scripts @scripts/azure/start_embedding_job_remote.sh \
  --parameters \
    storageAccount="$STORAGE_ACCOUNT" \
    container="$CONTAINER" \
    processedRunId="$PROCESSED_RUN_ID" \
    collectionName="$COLLECTION_NAME" \
    modelName="$MODEL_NAME" \
    repoDir="$VM_REPO_DIR" \
    codeArchiveBlob="$CODE_ARCHIVE_BLOB" \
    cloudRunId="$JOB_RUN_ID" \
    prepareProcessedIfMissing="$PREPARE_PROCESSED_IF_MISSING" \
    allowRawDownload="$ALLOW_RAW_DOWNLOAD"

echo
echo "=== Cloud Run Artifacts ==="
echo "cloud run id: $JOB_RUN_ID"
echo "code archive: $CONTAINER/$CODE_ARCHIVE_BLOB"
echo "log: $CONTAINER/logs/$JOB_RUN_ID/remote_embedding_job.log"
echo "status: $CONTAINER/logs/$JOB_RUN_ID/status.json"
echo
echo "Download live status:"
echo "az storage blob download --account-name \"$STORAGE_ACCOUNT\" --container-name \"$CONTAINER\" --name \"logs/$JOB_RUN_ID/status.json\" --file /tmp/reverse-wiktionary-$JOB_RUN_ID-status.json --auth-mode login --overwrite && jq . /tmp/reverse-wiktionary-$JOB_RUN_ID-status.json"
