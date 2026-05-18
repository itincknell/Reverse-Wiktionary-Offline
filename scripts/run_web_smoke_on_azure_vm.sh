#!/usr/bin/env bash
set -euo pipefail

# Package the current repo and run a web/API smoke test on an existing Azure VM.

RESOURCE_GROUP=""
VM_NAME=""
STORAGE_ACCOUNT=""
CONTAINER=""
COLLECTION_NAME="reverse_wiktionary_v1"
MODEL_NAME="sentence-transformers/all-mpnet-base-v2"
QDRANT_HNSW_EF="512"
QDRANT_ACORN_MAX_SELECTIVITY="1.0"
SEARCH_EXACT_FILTERED="false"
VM_REPO_DIR="/opt/reverse-wiktionary-web-smoke"
JOB_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
CODE_ARCHIVE_BLOB="code/web-smoke-$JOB_RUN_ID/repo.tar.gz"
LOCAL_ARCHIVE=""

usage() {
  cat <<'EOF'
Run a web/API smoke test on an existing Azure VM.

Required:
  --resource-group NAME
  --vm-name NAME
  --storage-account NAME
  --container NAME

Optional:
  --collection-name NAME
      Defaults to reverse_wiktionary_v1.
  --model-name NAME
      Defaults to sentence-transformers/all-mpnet-base-v2.
  --vm-repo-dir PATH
      Defaults to /opt/reverse-wiktionary-web-smoke.
  --qdrant-hnsw-ef N
      Query-time HNSW exploration parameter. Defaults to 512.
  --qdrant-acorn-max-selectivity N
      ACORN selectivity threshold for filtered searches. Defaults to 1.0.
  --search-exact-filtered
      Use exact Qdrant search for filtered searches.
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
    --model-name)
      MODEL_NAME="$2"
      shift 2
      ;;
    --vm-repo-dir)
      VM_REPO_DIR="$2"
      shift 2
      ;;
    --qdrant-hnsw-ef)
      QDRANT_HNSW_EF="$2"
      shift 2
      ;;
    --qdrant-acorn-max-selectivity)
      QDRANT_ACORN_MAX_SELECTIVITY="$2"
      shift 2
      ;;
    --search-exact-filtered)
      SEARCH_EXACT_FILTERED="true"
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

LC_ALL=C COPYFILE_DISABLE=1 tar --no-xattrs -czf "$LOCAL_ARCHIVE" \
  --exclude ".git" \
  --exclude ".DS_Store" \
  --exclude "._*" \
  --exclude "data" \
  --exclude "revwik" \
  --exclude ".venv" \
  --exclude "tmp" \
  --exclude "tree" \
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
echo "=== Running Remote Web Smoke ==="
az vm run-command invoke \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME" \
  --command-id RunShellScript \
  --scripts @scripts/azure/run_web_smoke_remote.sh \
  --parameters \
    storageAccount="$STORAGE_ACCOUNT" \
    container="$CONTAINER" \
    codeArchiveBlob="$CODE_ARCHIVE_BLOB" \
    repoDir="$VM_REPO_DIR" \
    collectionName="$COLLECTION_NAME" \
    modelName="$MODEL_NAME" \
    qdrantHnswEf="$QDRANT_HNSW_EF" \
    qdrantAcornMaxSelectivity="$QDRANT_ACORN_MAX_SELECTIVITY" \
    searchExactFiltered="$SEARCH_EXACT_FILTERED" \
    runId="$JOB_RUN_ID"

echo
echo "=== Web Smoke Complete ==="
echo "run id: $JOB_RUN_ID"
echo "code archive: $CONTAINER/$CODE_ARCHIVE_BLOB"
echo "benchmark artifacts: $CONTAINER/logs/web_smoke/$JOB_RUN_ID"
