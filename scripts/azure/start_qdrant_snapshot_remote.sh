#!/usr/bin/env bash
set -euo pipefail

# Short Azure Run Command entrypoint for rerunning Qdrant snapshot/upload.

storageAccount="${storageAccount:-}"
container="${container:-}"
collectionName="${collectionName:-reverse_wiktionary_v1}"
repoDir="${repoDir:-/opt/reverse-wiktionary}"
runId="${runId:-$(date -u +%Y%m%dT%H%M%SZ)}"
timeoutSeconds="${timeoutSeconds:-3600}"
pollIntervalSeconds="${pollIntervalSeconds:-5}"
reuseExisting="${reuseExisting:-false}"
startQdrant="${startQdrant:-true}"

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

if [ ! -f "$repoDir/scripts/azure/store_qdrant_snapshot_remote.sh" ]; then
  echo "Snapshot helper not found in VM repo: $repoDir/scripts/azure/store_qdrant_snapshot_remote.sh"
  exit 1
fi

unit_name="reverse-wiktionary-snapshot-$runId"

echo "=== Starting Background Snapshot Job ==="
echo "unit: $unit_name"
echo "run id: $runId"

systemd-run \
  --unit "$unit_name" \
  --description "Reverse Wiktionary Qdrant snapshot job $runId" \
  --property "WorkingDirectory=$repoDir" \
  /usr/bin/env bash "$repoDir/scripts/azure/store_qdrant_snapshot_remote.sh" \
    storageAccount="$storageAccount" \
    container="$container" \
    collectionName="$collectionName" \
    repoDir="$repoDir" \
    runId="$runId" \
    timeoutSeconds="$timeoutSeconds" \
    pollIntervalSeconds="$pollIntervalSeconds" \
    reuseExisting="$reuseExisting" \
    startQdrant="$startQdrant"

echo
echo "Snapshot job submitted."
echo "status: logs/snapshot-$runId/status.json"
echo "log: logs/snapshot-$runId/remote_snapshot_job.log"
