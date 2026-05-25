#!/usr/bin/env bash
set -euo pipefail

# Remote Azure VM job for rebuilding Qdrant from fresh processed rows and
# previously saved vector shards.

storageAccount="${storageAccount:-}"
container="${container:-}"
collectionName="${collectionName:-reverse_wiktionary_v5}"
expectedVectorSize="${expectedVectorSize:-768}"
repoDir="${repoDir:-/opt/reverse-wiktionary}"
codeArchiveBlob="${codeArchiveBlob:-}"
cloudRunId="${cloudRunId:-$(date -u +%Y%m%dT%H%M%SZ)}"
systemdUnit="${systemdUnit:-}"
rawRunId="${rawRunId:-latest}"
vectorRunId="${vectorRunId:-20260524T223236Z}"
spliceRunId="${spliceRunId:-}"
upsertBatchSize="${upsertBatchSize:-256}"
pointIdShardSize="${pointIdShardSize:-50000}"
startedAtUtc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
processedRunId=""
logFile="/tmp/reverse-wiktionary-splice-$cloudRunId.log"
statusFile="/tmp/reverse-wiktionary-splice-$cloudRunId-status.json"
stateFile="/tmp/reverse-wiktionary-splice-$cloudRunId-state.env"
qdrantStarted=false
stage="starting"
logUploaderPid=""
pythonBin="python"

for parameter in "$@"; do
  case "$parameter" in
    storageAccount=*) storageAccount="${parameter#storageAccount=}" ;;
    container=*) container="${parameter#container=}" ;;
    collectionName=*) collectionName="${parameter#collectionName=}" ;;
    expectedVectorSize=*) expectedVectorSize="${parameter#expectedVectorSize=}" ;;
    repoDir=*) repoDir="${parameter#repoDir=}" ;;
    codeArchiveBlob=*) codeArchiveBlob="${parameter#codeArchiveBlob=}" ;;
    cloudRunId=*)
      cloudRunId="${parameter#cloudRunId=}"
      logFile="/tmp/reverse-wiktionary-splice-$cloudRunId.log"
      statusFile="/tmp/reverse-wiktionary-splice-$cloudRunId-status.json"
      stateFile="/tmp/reverse-wiktionary-splice-$cloudRunId-state.env"
      ;;
    systemdUnit=*) systemdUnit="${parameter#systemdUnit=}" ;;
    rawRunId=*) rawRunId="${parameter#rawRunId=}" ;;
    vectorRunId=*) vectorRunId="${parameter#vectorRunId=}" ;;
    spliceRunId=*) spliceRunId="${parameter#spliceRunId=}" ;;
    upsertBatchSize=*) upsertBatchSize="${parameter#upsertBatchSize=}" ;;
    pointIdShardSize=*) pointIdShardSize="${parameter#pointIdShardSize=}" ;;
  esac
done

if [ -z "$storageAccount" ] || [ -z "$container" ]; then
  echo "Missing required storageAccount/container parameters"
  exit 1
fi

if [ -z "$spliceRunId" ]; then
  spliceRunId="$(date -u +%Y%m%dT%H%M%SZ)"
fi

write_state() {
  cat > "$stateFile" <<EOF
stage=$stage
splice_run_id=$spliceRunId
processed_run_id=$processedRunId
vector_run_id=$vectorRunId
EOF
}

state_value() {
  local key="$1"
  local fallback="$2"

  if [ ! -f "$stateFile" ]; then
    echo "$fallback"
    return
  fi

  awk -F= -v key="$key" -v fallback="$fallback" '$1 == key { print $2; found=1 } END { if (!found) print fallback }' "$stateFile"
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
  local updated_at_utc
  local current_stage
  local current_processed_run_id
  local qdrant_points
  local qdrant_indexed
  local qdrant_status
  local qdrant_queue

  if [ "$status" = "succeeded" ] && [ "$exit_code" -ne 0 ]; then
    status="failed"
  fi

  updated_at_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  current_stage="$(state_value stage "$stage")"
  current_processed_run_id="$(state_value processed_run_id "$processedRunId")"
  qdrant_points="$(qdrant_collection_field '.result.points_count')"
  qdrant_indexed="$(qdrant_collection_field '.result.indexed_vectors_count')"
  qdrant_status="$(qdrant_collection_field '.result.status')"
  qdrant_queue="$(qdrant_collection_field '.result.update_queue.length')"

  jq -n \
    --arg cloud_run_id "$cloudRunId" \
    --arg splice_run_id "$spliceRunId" \
    --arg processed_run_id "$current_processed_run_id" \
    --arg vector_run_id "$vectorRunId" \
    --arg started_at_utc "$startedAtUtc" \
    --arg updated_at_utc "$updated_at_utc" \
    --arg stage "$current_stage" \
    --arg status "$status" \
    --arg storage_account "$storageAccount" \
    --arg container "$container" \
    --arg collection_name "$collectionName" \
    --arg expected_vector_size "$expectedVectorSize" \
    --arg code_archive_blob "$codeArchiveBlob" \
    --arg repo_dir "$repoDir" \
    --arg systemd_unit "$systemdUnit" \
    --arg qdrant_status "$qdrant_status" \
    --arg log_path "logs/$cloudRunId/remote_splice_job.log" \
    --arg status_path "logs/$cloudRunId/status.json" \
    --argjson exit_code "$exit_code" \
    --argjson qdrant_points_count "$qdrant_points" \
    --argjson qdrant_indexed_vectors_count "$qdrant_indexed" \
    --argjson qdrant_update_queue_length "$qdrant_queue" \
    '{
      cloud_run_id: $cloud_run_id,
      splice_run_id: $splice_run_id,
      processed_run_id: (if $processed_run_id == "" then null else $processed_run_id end),
      vector_run_id: $vector_run_id,
      started_at_utc: $started_at_utc,
      updated_at_utc: $updated_at_utc,
      finished_at_utc: (if $status == "running" then null else $updated_at_utc end),
      stage: $stage,
      status: $status,
      exit_code: $exit_code,
      storage_account: $storage_account,
      container: $container,
      collection_name: $collection_name,
      expected_vector_size: ($expected_vector_size | tonumber),
      code_archive_blob: $code_archive_blob,
      repo_dir: $repo_dir,
      systemd_unit: (if $systemd_unit == "" then null else $systemd_unit end),
      qdrant_status: (if $qdrant_status == "null" then null else $qdrant_status end),
      qdrant_points_count: $qdrant_points_count,
      qdrant_indexed_vectors_count: $qdrant_indexed_vectors_count,
      qdrant_update_queue_length: $qdrant_update_queue_length,
      log_path: $log_path,
      status_path: $status_path,
      processed_prefix: (
        if $processed_run_id == "" then null
        else "processed/\($processed_run_id)"
        end
      ),
      splice_manifest_path: "splices/\($splice_run_id)/manifest.json",
      snapshot_prefix: "indexes/\($splice_run_id)"
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
    --name "logs/$cloudRunId/remote_splice_job.log" \
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

echo "=== Remote Splice Job ==="
echo "repo: $repoDir"
echo "storage account: $storageAccount"
echo "container: $container"
echo "collection: $collectionName"
echo "expected vector size: $expectedVectorSize"
echo "raw run id: $rawRunId"
echo "vector run id: $vectorRunId"
echo "splice run id: $spliceRunId"
echo "code archive: $codeArchiveBlob"
echo "cloud run id: $cloudRunId"

cd "$repoDir"

set_stage "installing_dependencies"
if [ -x "$repoDir/.venv/bin/python" ]; then
  pythonBin="$repoDir/.venv/bin/python"
else
  python -m venv "$repoDir/.venv"
  pythonBin="$repoDir/.venv/bin/python"
  "$pythonBin" -m pip install --upgrade pip
fi
"$pythonBin" -m pip install -r requirements.txt
export PATH="$repoDir/.venv/bin:$PATH"

if [ "$rawRunId" != "latest" ]; then
  if [ ! -d "data/raw/$rawRunId" ]; then
    echo "Raw run not found: data/raw/$rawRunId"
    exit 1
  fi

  ln -sfn "$rawRunId" data/raw/latest
fi

if [ ! -f "data/raw/latest/wiktionary.jsonl" ]; then
  echo "Raw input missing: data/raw/latest/wiktionary.jsonl"
  exit 1
fi

if [ ! -d "data/embeddings/$vectorRunId/vectors" ]; then
  echo "Vector directory missing: data/embeddings/$vectorRunId/vectors"
  exit 1
fi

processedRunId="$(date -u +%Y%m%dT%H%M%SZ)"
write_state

set_stage "parsing_raw"
"$pythonBin" ./src/embeddings/parse_wiktionary.py \
  --input data/raw/latest/wiktionary.jsonl \
  --output-root data/processed \
  --manifest "data/processed/$processedRunId/manifest.json" \
  --run-id "$processedRunId"

set_stage "uploading_processed"
./scripts/upload_processed_to_blob.sh \
  --root-dir data/processed \
  --run-id "$processedRunId" \
  --storage-account "$storageAccount" \
  --container "$container"

set_stage "starting_qdrant"
./scripts/start_qdrant.sh
qdrantStarted=true

set_stage "splicing_vectors"
"$pythonBin" -u ./src/embeddings/splice_embeddings.py \
  --processed-dir "data/processed/$processedRunId" \
  --vector-dir "data/embeddings/$vectorRunId/vectors" \
  --output-root data/splices \
  --collection-name "$collectionName" \
  --run-id "$spliceRunId" \
  --point-id-shard-size "$pointIdShardSize" \
  --upsert-batch-size "$upsertBatchSize" \
  --recreate-collection \
  --on-disk-payload \
  --expected-vector-size "$expectedVectorSize" \
  --progress-every 100000

set_stage "uploading_splice_manifest"
az storage blob upload \
  --account-name "$storageAccount" \
  --container-name "$container" \
  --name "splices/$spliceRunId/manifest.json" \
  --file "data/splices/$spliceRunId/manifest.json" \
  --overwrite true \
  --auth-mode login \
  --output none

set_stage "creating_payload_indexes"
REVWIK_STAGE_FILE="$stateFile" \
REVWIK_EMBEDDING_RUN_ID="$spliceRunId" \
  ./scripts/qdrant/create_payload_indexes.sh \
  --collection-name "$collectionName" \
  --qdrant-url http://localhost:6333

REVWIK_STAGE_FILE="$stateFile" \
REVWIK_EMBEDDING_RUN_ID="$spliceRunId" \
  ./scripts/qdrant/check_payload_indexes.sh \
  --collection-name "$collectionName" \
  --qdrant-url http://localhost:6333

set_stage "quantizing"
./scripts/qdrant/apply_scalar_quantization.sh \
  --collection-name "$collectionName" \
  --qdrant-url http://localhost:6333 \
  --quantile 0.99 \
  --always-ram true \
  --on-disk true

set_stage "waiting_for_qdrant"
./scripts/qdrant/wait_collection_ready.sh \
  --collection-name "$collectionName" \
  --qdrant-url http://localhost:6333 \
  --timeout-seconds 3600 \
  --poll-interval-seconds 30

set_stage "snapshotting"
REVWIK_STAGE_FILE="$stateFile" \
REVWIK_EMBEDDING_RUN_ID="$spliceRunId" \
  ./scripts/store_qdrant_snapshot.sh \
  --collection-name "$collectionName" \
  --run-id "$spliceRunId" \
  --timeout-seconds 3600 \
  --poll-interval-seconds 5 \
  --upload \
  --storage-account "$storageAccount" \
  --container "$container"

set_stage "succeeded"

echo
echo "Remote splice job complete."
echo "cloud run id: $cloudRunId"
echo "processed run id: $processedRunId"
echo "splice run id: $spliceRunId"
echo "log path: logs/$cloudRunId/remote_splice_job.log"
echo "status path: logs/$cloudRunId/status.json"
