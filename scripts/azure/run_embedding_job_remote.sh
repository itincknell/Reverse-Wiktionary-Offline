#!/usr/bin/env bash
set -euo pipefail

# Remote Azure VM job invoked by scripts/run_embeddings_on_azure_vm.sh.
#
# The VM is expected to have Azure CLI, Docker, jq, and the project repo
# archive supplied by the launcher. Keeping the remote job explicit makes the
# VM contract visible and avoids hiding infrastructure assumptions inside
# Python code.

storageAccount="${storageAccount:-}"
container="${container:-}"
processedRunId="${processedRunId:-latest}"
collectionName="${collectionName:-reverse_wiktionary_v1}"
modelName="${modelName:-sentence-transformers/all-mpnet-base-v2}"
repoDir="${repoDir:-/opt/reverse-wiktionary}"
codeArchiveBlob="${codeArchiveBlob:-}"
cloudRunId="${cloudRunId:-$(date -u +%Y%m%dT%H%M%SZ)}"
systemdUnit="${systemdUnit:-}"
repoPrepared="${repoPrepared:-false}"
prepareProcessedIfMissing="${prepareProcessedIfMissing:-false}"
allowRawDownload="${allowRawDownload:-false}"
startedAtUtc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
embeddingRunId=""
logFile="/tmp/reverse-wiktionary-$cloudRunId.log"
statusFile="/tmp/reverse-wiktionary-$cloudRunId-status.json"
stateFile="/tmp/reverse-wiktionary-$cloudRunId-state.env"
qdrantStarted=false
stage="starting"
logUploaderPid=""
venvDir=""
pythonBin="python"

for parameter in "$@"; do
  case "$parameter" in
    storageAccount=*)
      storageAccount="${parameter#storageAccount=}"
      ;;
    container=*)
      container="${parameter#container=}"
      ;;
    processedRunId=*)
      processedRunId="${parameter#processedRunId=}"
      ;;
    collectionName=*)
      collectionName="${parameter#collectionName=}"
      ;;
    modelName=*)
      modelName="${parameter#modelName=}"
      ;;
    repoDir=*)
      repoDir="${parameter#repoDir=}"
      ;;
    codeArchiveBlob=*)
      codeArchiveBlob="${parameter#codeArchiveBlob=}"
      ;;
    cloudRunId=*)
      cloudRunId="${parameter#cloudRunId=}"
      logFile="/tmp/reverse-wiktionary-$cloudRunId.log"
      statusFile="/tmp/reverse-wiktionary-$cloudRunId-status.json"
      stateFile="/tmp/reverse-wiktionary-$cloudRunId-state.env"
      ;;
    systemdUnit=*)
      systemdUnit="${parameter#systemdUnit=}"
      ;;
    repoPrepared=*)
      repoPrepared="${parameter#repoPrepared=}"
      ;;
    prepareProcessedIfMissing=*)
      prepareProcessedIfMissing="${parameter#prepareProcessedIfMissing=}"
      ;;
    allowRawDownload=*)
      allowRawDownload="${parameter#allowRawDownload=}"
      ;;
  esac
done

if [ -z "$storageAccount" ] || [ -z "$container" ]; then
  echo "Missing required storageAccount/container parameters"
  exit 1
fi

write_state() {
  cat > "$stateFile" <<EOF
stage=$stage
embedding_run_id=$embeddingRunId
EOF
}

current_state_value() {
  local key="$1"
  local default="$2"

  if [ ! -f "$stateFile" ]; then
    echo "$default"
    return
  fi

  awk -F= -v key="$key" -v default="$default" '$1 == key { print $2; found=1 } END { if (!found) print default }' "$stateFile"
}

qdrant_collection_field() {
  local field="$1"
  local collection_json

  collection_json="$(curl -fsS "http://localhost:6333/collections/$collectionName" 2>/dev/null || true)"

  if [ -z "$collection_json" ]; then
    echo "null"
    return
  fi

  echo "$collection_json" | jq -r "$field // null"
}

upload_run_artifacts() {
  local exit_code="$1"
  local status="${2:-succeeded}"
  local finished_at_utc
  local current_stage
  local current_embedding_run_id
  local qdrant_points
  local qdrant_indexed
  local qdrant_status
  local qdrant_queue

  if [ "$status" = "succeeded" ] && [ "$exit_code" -ne 0 ]; then
    status="failed"
  fi

  finished_at_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  current_stage="$(current_state_value stage "$stage")"
  current_embedding_run_id="$(current_state_value embedding_run_id "$embeddingRunId")"
  qdrant_points="$(qdrant_collection_field '.result.points_count')"
  qdrant_indexed="$(qdrant_collection_field '.result.indexed_vectors_count')"
  qdrant_status="$(qdrant_collection_field '.result.status')"
  qdrant_queue="$(qdrant_collection_field '.result.update_queue.length')"

  jq -n \
    --arg cloud_run_id "$cloudRunId" \
    --arg embedding_run_id "$current_embedding_run_id" \
    --arg started_at_utc "$startedAtUtc" \
    --arg updated_at_utc "$finished_at_utc" \
    --arg stage "$current_stage" \
    --arg status "$status" \
    --arg storage_account "$storageAccount" \
    --arg container "$container" \
    --arg processed_run_id "$processedRunId" \
    --arg collection_name "$collectionName" \
    --arg model_name "$modelName" \
    --arg code_archive_blob "$codeArchiveBlob" \
    --arg repo_dir "$repoDir" \
    --arg systemd_unit "$systemdUnit" \
    --arg prepare_processed_if_missing "$prepareProcessedIfMissing" \
    --arg allow_raw_download "$allowRawDownload" \
    --arg qdrant_status "$qdrant_status" \
    --arg log_path "logs/$cloudRunId/remote_embedding_job.log" \
    --arg status_path "logs/$cloudRunId/status.json" \
    --argjson exit_code "$exit_code" \
    --argjson qdrant_points_count "$qdrant_points" \
    --argjson qdrant_indexed_vectors_count "$qdrant_indexed" \
    --argjson qdrant_update_queue_length "$qdrant_queue" \
    '{
      cloud_run_id: $cloud_run_id,
      embedding_run_id: (if $embedding_run_id == "" then null else $embedding_run_id end),
      started_at_utc: $started_at_utc,
      updated_at_utc: $updated_at_utc,
      finished_at_utc: (if $status == "running" then null else $updated_at_utc end),
      stage: $stage,
      status: $status,
      exit_code: $exit_code,
      storage_account: $storage_account,
      container: $container,
      processed_run_id: $processed_run_id,
      collection_name: $collection_name,
      model_name: $model_name,
      code_archive_blob: $code_archive_blob,
      repo_dir: $repo_dir,
      systemd_unit: (if $systemd_unit == "" then null else $systemd_unit end),
      prepare_processed_if_missing: ($prepare_processed_if_missing == "true"),
      allow_raw_download: ($allow_raw_download == "true"),
      qdrant_status: (if $qdrant_status == "null" then null else $qdrant_status end),
      qdrant_points_count: $qdrant_points_count,
      qdrant_indexed_vectors_count: $qdrant_indexed_vectors_count,
      qdrant_update_queue_length: $qdrant_update_queue_length,
      log_path: $log_path,
      status_path: $status_path,
      embedding_manifest_path: (
        if $embedding_run_id == "" then null
        else "embeddings/\($embedding_run_id)/manifest.json"
        end
      ),
      snapshot_prefix: (
        if $embedding_run_id == "" then null
        else "indexes/\($embedding_run_id)"
        end
      )
    }' > "$statusFile"

  az storage blob upload \
    --account-name "$storageAccount" \
    --container-name "$container" \
    --name "logs/$cloudRunId/status.json" \
    --file "$statusFile" \
    --overwrite true \
    --auth-mode login \
    --output none || true

  az storage blob upload \
    --account-name "$storageAccount" \
    --container-name "$container" \
    --name "logs/$cloudRunId/remote_embedding_job.log" \
    --file "$logFile" \
    --overwrite true \
    --auth-mode login \
    --output none || true
}

set_stage() {
  stage="$1"
  write_state
  echo
  echo "=== Stage: $stage ==="
  upload_run_artifacts 0 "running"
}

periodic_upload_loop() {
  while true; do
    upload_run_artifacts 0 "running"
    sleep 60
  done
}

cleanup() {
  local exit_code="$?"

  if [ -n "$logUploaderPid" ]; then
    kill "$logUploaderPid" 2>/dev/null || true
  fi

  upload_run_artifacts "$exit_code"

  if [ "$qdrantStarted" = true ]; then
    ./scripts/stop_qdrant.sh || true
  fi

  exit "$exit_code"
}

trap cleanup EXIT

touch "$logFile"
write_state
exec > >(tee -a "$logFile") 2>&1

echo "=== Azure Managed Identity Login ==="
az login --identity --output none
periodic_upload_loop &
logUploaderPid="$!"

echo "=== Remote Embedding Job ==="
echo "repo: $repoDir"
echo "storage account: $storageAccount"
echo "container: $container"
echo "processed run id: $processedRunId"
echo "collection: $collectionName"
echo "model: $modelName"
echo "code archive: $codeArchiveBlob"
echo "cloud run id: $cloudRunId"
echo "repo prepared: $repoPrepared"
echo "prepare processed if missing: $prepareProcessedIfMissing"
echo "allow raw download: $allowRawDownload"

if [ "$repoPrepared" != true ] && [ -n "$codeArchiveBlob" ]; then
  set_stage "preparing_repo"
  archive_path="$(mktemp).tar.gz"

  mkdir -p "$repoDir"

  az storage blob download \
    --account-name "$storageAccount" \
    --container-name "$container" \
    --name "$codeArchiveBlob" \
    --file "$archive_path" \
    --auth-mode login \
    --output none

  tar -xzf "$archive_path" -C "$repoDir"
  rm -f "$archive_path"
fi

cd "$repoDir"

set_stage "installing_dependencies"
venvDir="$repoDir/.venv"
python -m venv "$venvDir"
pythonBin="$venvDir/bin/python"
"$pythonBin" -m pip install --upgrade pip
"$pythonBin" -m pip install -r requirements.txt
export PATH="$venvDir/bin:$PATH"

ensure_args=(
  --storage-account "$storageAccount"
  --container "$container"
  --processed-run-id "$processedRunId"
)

if [ "$prepareProcessedIfMissing" = true ]; then
  ensure_args+=(--prepare-if-missing)
fi

if [ "$allowRawDownload" = true ]; then
  ensure_args+=(--allow-raw-download)
fi

set_stage "ensuring_processed_input"
REVWIK_STAGE_FILE="$stateFile" \
  ./scripts/ensure_processed_input.sh "${ensure_args[@]}"

set_stage "starting_qdrant"
./scripts/start_qdrant.sh
qdrantStarted=true

embeddingRunId="$(date -u +%Y%m%dT%H%M%SZ)"
write_state

set_stage "embedding"
"$pythonBin" -u ./src/embeddings/generate_embeddings.py \
  --processed-dir data/processed/latest \
  --output-root data/embeddings \
  --collection-name "$collectionName" \
  --model-name "$modelName" \
  --device auto \
  --batch-size 128 \
  --queue-size 4 \
  --point-id-shard-size 50000 \
  --recreate-collection \
  --run-id "$embeddingRunId" \
  --progress-every 100000

set_stage "creating_payload_indexes"
REVWIK_STAGE_FILE="$stateFile" \
REVWIK_EMBEDDING_RUN_ID="$embeddingRunId" \
  ./scripts/qdrant/create_payload_indexes.sh \
  --collection-name "$collectionName" \
  --qdrant-url http://localhost:6333

REVWIK_STAGE_FILE="$stateFile" \
REVWIK_EMBEDDING_RUN_ID="$embeddingRunId" \
  ./scripts/qdrant/check_payload_indexes.sh \
  --collection-name "$collectionName" \
  --qdrant-url http://localhost:6333

set_stage "snapshotting"
REVWIK_STAGE_FILE="$stateFile" \
REVWIK_EMBEDDING_RUN_ID="$embeddingRunId" \
  ./scripts/store_qdrant_snapshot.sh \
  --collection-name "$collectionName" \
  --run-id "$embeddingRunId" \
  --timeout-seconds 3600 \
  --poll-interval-seconds 5 \
  --upload \
  --storage-account "$storageAccount" \
  --container "$container"

set_stage "uploading_embedding_manifest"
az storage blob upload \
  --account-name "$storageAccount" \
  --container-name "$container" \
  --name "embeddings/$embeddingRunId/manifest.json" \
  --file "data/embeddings/$embeddingRunId/manifest.json" \
  --overwrite true \
  --auth-mode login

set_stage "succeeded"

echo
echo "Remote embedding job complete."
echo "cloud run id: $cloudRunId"
echo "embedding run id: $embeddingRunId"
echo "log path: logs/$cloudRunId/remote_embedding_job.log"
echo "status path: logs/$cloudRunId/status.json"
