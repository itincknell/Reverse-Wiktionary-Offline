#!/usr/bin/env bash
set -euo pipefail

# Package the current repo and submit a CPU splice job to an existing Azure VM.

RESOURCE_GROUP=""
VM_NAME=""
STORAGE_ACCOUNT=""
CONTAINER=""
COLLECTION_NAME="reverse_wiktionary_v5"
EXPECTED_VECTOR_SIZE="768"
VM_REPO_DIR="/opt/reverse-wiktionary"
RAW_RUN_ID="latest"
VECTOR_RUN_ID="20260524T223236Z"
UPSERT_BATCH_SIZE="256"
POINT_ID_SHARD_SIZE="50000"
JOB_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
SPLICE_RUN_ID="$JOB_RUN_ID"
CODE_ARCHIVE_BLOB="code/$JOB_RUN_ID/repo.tar.gz"
LOCAL_ARCHIVE=""

usage() {
  cat <<'EOF'
Package the repo, upload it to Blob, and submit a splice job to an existing
Azure VM as a background systemd unit.

The splice job reparses raw Wiktionary data on the VM, pairs the new processed
rows with saved vector shards, rebuilds Qdrant, and uploads a new snapshot. It
does not regenerate or upload embedding vectors.

Required:
  --resource-group NAME
  --vm-name NAME
  --storage-account NAME
  --container NAME

Optional:
  --collection-name NAME
      Defaults to reverse_wiktionary_v5.
  --expected-vector-size N
      Expected saved vector dimension. Defaults to 768.
  --vm-repo-dir PATH
      Defaults to /opt/reverse-wiktionary.
  --raw-run-id RUN_ID
      Raw run to parse on the VM. Defaults to latest.
  --vector-run-id RUN_ID
      Existing embedding vector run. Defaults to 20260524T223236Z.
  --splice-run-id RUN_ID
      New splice/index run ID. Defaults to the cloud job run ID.
  --upsert-batch-size N
      Qdrant upsert batch size. Defaults to 256.
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
    --expected-vector-size)
      EXPECTED_VECTOR_SIZE="$2"
      shift 2
      ;;
    --vm-repo-dir)
      VM_REPO_DIR="$2"
      shift 2
      ;;
    --raw-run-id)
      RAW_RUN_ID="$2"
      shift 2
      ;;
    --vector-run-id)
      VECTOR_RUN_ID="$2"
      shift 2
      ;;
    --splice-run-id)
      SPLICE_RUN_ID="$2"
      shift 2
      ;;
    --upsert-batch-size)
      UPSERT_BATCH_SIZE="$2"
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
echo "=== Submitting Remote Splice Job ==="
az vm run-command invoke \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME" \
  --command-id RunShellScript \
  --scripts @scripts/azure/start_splice_job_remote.sh \
  --parameters \
    storageAccount="$STORAGE_ACCOUNT" \
    container="$CONTAINER" \
    collectionName="$COLLECTION_NAME" \
    expectedVectorSize="$EXPECTED_VECTOR_SIZE" \
    repoDir="$VM_REPO_DIR" \
    codeArchiveBlob="$CODE_ARCHIVE_BLOB" \
    cloudRunId="$JOB_RUN_ID" \
    rawRunId="$RAW_RUN_ID" \
    vectorRunId="$VECTOR_RUN_ID" \
    spliceRunId="$SPLICE_RUN_ID" \
    upsertBatchSize="$UPSERT_BATCH_SIZE" \
    pointIdShardSize="$POINT_ID_SHARD_SIZE"

echo
echo "=== Cloud Run Artifacts ==="
echo "cloud run id: $JOB_RUN_ID"
echo "splice run id: $SPLICE_RUN_ID"
echo "code archive: $CONTAINER/$CODE_ARCHIVE_BLOB"
echo "log: $CONTAINER/logs/$JOB_RUN_ID/remote_splice_job.log"
echo "status: $CONTAINER/logs/$JOB_RUN_ID/status.json"
echo
echo "Download live status:"
echo "az storage blob download --account-name \"$STORAGE_ACCOUNT\" --container-name \"$CONTAINER\" --name \"logs/$JOB_RUN_ID/status.json\" --file /tmp/reverse-wiktionary-$JOB_RUN_ID-status.json --auth-mode login --overwrite && jq . /tmp/reverse-wiktionary-$JOB_RUN_ID-status.json"
