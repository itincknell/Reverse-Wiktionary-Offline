#!/usr/bin/env bash
set -euo pipefail

# Remote Azure VM helper for rerunning Qdrant snapshot/upload without
# regenerating embeddings.

storageAccount="${storageAccount:-}"
container="${container:-}"
collectionName="${collectionName:-reverse_wiktionary_v1}"
repoDir="${repoDir:-/opt/reverse-wiktionary}"
runId="${runId:-$(date -u +%Y%m%dT%H%M%SZ)}"
timeoutSeconds="${timeoutSeconds:-3600}"
pollIntervalSeconds="${pollIntervalSeconds:-5}"
reuseExisting="${reuseExisting:-false}"
startQdrant="${startQdrant:-true}"
qdrantStarted=false
stage="starting"

for parameter in "$@"; do
  case "$parameter" in
    storageAccount=*)
      storageAccount="${parameter#storageAccount=}"
      ;;
    container=*)
      container="${parameter#container=}"
      ;;
    collectionName=*)
      collectionName="${parameter#collectionName=}"
      ;;
    repoDir=*)
      repoDir="${parameter#repoDir=}"
      ;;
    runId=*)
      runId="${parameter#runId=}"
      ;;
    timeoutSeconds=*)
      timeoutSeconds="${parameter#timeoutSeconds=}"
      ;;
    pollIntervalSeconds=*)
      pollIntervalSeconds="${parameter#pollIntervalSeconds=}"
      ;;
    reuseExisting=*)
      reuseExisting="${parameter#reuseExisting=}"
      ;;
    startQdrant=*)
      startQdrant="${parameter#startQdrant=}"
      ;;
  esac
done

if [ -z "$storageAccount" ] || [ -z "$container" ]; then
  echo "Missing required storageAccount/container parameters"
  exit 1
fi

logFile="/tmp/reverse-wiktionary-snapshot-$runId.log"
statusFile="/tmp/reverse-wiktionary-snapshot-$runId-status.json"
startedAtUtc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
logUploaderPid=""

touch "$logFile"
exec > >(tee -a "$logFile") 2>&1

upload_status() {
  local exit_code="$1"
  local status="$2"
  local updated_at_utc

  updated_at_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  jq -n \
    --arg run_id "$runId" \
    --arg started_at_utc "$startedAtUtc" \
    --arg updated_at_utc "$updated_at_utc" \
    --arg status "$status" \
    --arg stage "$stage" \
    --arg storage_account "$storageAccount" \
    --arg container "$container" \
    --arg collection_name "$collectionName" \
    --arg repo_dir "$repoDir" \
    --arg log_path "logs/snapshot-$runId/remote_snapshot_job.log" \
    --arg status_path "logs/snapshot-$runId/status.json" \
    --arg snapshot_prefix "indexes/$runId" \
    --argjson exit_code "$exit_code" \
    '{
      run_id: $run_id,
      started_at_utc: $started_at_utc,
      updated_at_utc: $updated_at_utc,
      finished_at_utc: (if $status == "running" then null else $updated_at_utc end),
      status: $status,
      stage: $stage,
      exit_code: $exit_code,
      storage_account: $storage_account,
      container: $container,
      collection_name: $collection_name,
      repo_dir: $repo_dir,
      log_path: $log_path,
      status_path: $status_path,
      snapshot_prefix: $snapshot_prefix
    }' > "$statusFile"

  az storage blob upload \
    --account-name "$storageAccount" \
    --container-name "$container" \
    --name "logs/snapshot-$runId/status.json" \
    --file "$statusFile" \
    --overwrite true \
    --auth-mode login \
    --output none || true

  az storage blob upload \
    --account-name "$storageAccount" \
    --container-name "$container" \
    --name "logs/snapshot-$runId/remote_snapshot_job.log" \
    --file "$logFile" \
    --overwrite true \
    --auth-mode login \
    --output none || true
}

periodic_upload_loop() {
  while true; do
    upload_status 0 "running"
    sleep 60
  done
}

cleanup() {
  local exit_code="$?"
  local status="succeeded"

  if [ "$exit_code" -ne 0 ]; then
    status="failed"
  fi

  if [ -n "$logUploaderPid" ]; then
    kill "$logUploaderPid" 2>/dev/null || true
  fi

  upload_status "$exit_code" "$status"

  if [ "$qdrantStarted" = true ]; then
    ./scripts/stop_qdrant.sh || true
  fi

  exit "$exit_code"
}

trap cleanup EXIT

echo "=== Azure Managed Identity Login ==="
az login --identity --output none
upload_status 0 "running"
periodic_upload_loop &
logUploaderPid="$!"

cd "$repoDir"

stage="installing_dependencies"
if [ -x "$repoDir/.venv/bin/python" ]; then
  export PATH="$repoDir/.venv/bin:$PATH"
else
  python -m venv "$repoDir/.venv"
  "$repoDir/.venv/bin/python" -m pip install --upgrade pip
  "$repoDir/.venv/bin/python" -m pip install -r requirements.txt
  export PATH="$repoDir/.venv/bin:$PATH"
fi

if [ "$startQdrant" = true ]; then
  stage="starting_qdrant"
  ./scripts/start_qdrant.sh
  qdrantStarted=true
fi

if [ "$reuseExisting" != true ]; then
  stage="creating_payload_indexes"
  ./scripts/qdrant/create_payload_indexes.sh \
    --collection-name "$collectionName" \
    --qdrant-url http://localhost:6333

  ./scripts/qdrant/check_payload_indexes.sh \
    --collection-name "$collectionName" \
    --qdrant-url http://localhost:6333
fi

snapshot_args=(
  --collection-name "$collectionName"
  --run-id "$runId"
  --timeout-seconds "$timeoutSeconds"
  --poll-interval-seconds "$pollIntervalSeconds"
  --upload
  --storage-account "$storageAccount"
  --container "$container"
)

if [ "$reuseExisting" = true ]; then
  snapshot_args+=(--reuse-existing)
fi

stage="snapshotting"
./scripts/store_qdrant_snapshot.sh "${snapshot_args[@]}"

echo
echo "Snapshot upload complete."
echo "run id: $runId"
echo "log path: logs/snapshot-$runId/remote_snapshot_job.log"
echo "status path: logs/snapshot-$runId/status.json"
