#!/usr/bin/env bash
set -euo pipefail

# Azure Run Command entrypoint for starting a background splice job.

storageAccount="${storageAccount:-}"
container="${container:-}"
collectionName="${collectionName:-reverse_wiktionary_v5}"
expectedVectorSize="${expectedVectorSize:-768}"
repoDir="${repoDir:-/opt/reverse-wiktionary}"
codeArchiveBlob="${codeArchiveBlob:-}"
cloudRunId="${cloudRunId:-$(date -u +%Y%m%dT%H%M%SZ)}"
rawRunId="${rawRunId:-latest}"
vectorRunId="${vectorRunId:-20260524T223236Z}"
spliceRunId="${spliceRunId:-$cloudRunId}"
upsertBatchSize="${upsertBatchSize:-256}"
pointIdShardSize="${pointIdShardSize:-50000}"

for parameter in "$@"; do
  case "$parameter" in
    storageAccount=*) storageAccount="${parameter#storageAccount=}" ;;
    container=*) container="${parameter#container=}" ;;
    collectionName=*) collectionName="${parameter#collectionName=}" ;;
    expectedVectorSize=*) expectedVectorSize="${parameter#expectedVectorSize=}" ;;
    repoDir=*) repoDir="${parameter#repoDir=}" ;;
    codeArchiveBlob=*) codeArchiveBlob="${parameter#codeArchiveBlob=}" ;;
    cloudRunId=*) cloudRunId="${parameter#cloudRunId=}" ;;
    rawRunId=*) rawRunId="${parameter#rawRunId=}" ;;
    vectorRunId=*) vectorRunId="${parameter#vectorRunId=}" ;;
    spliceRunId=*) spliceRunId="${parameter#spliceRunId=}" ;;
    upsertBatchSize=*) upsertBatchSize="${parameter#upsertBatchSize=}" ;;
    pointIdShardSize=*) pointIdShardSize="${parameter#pointIdShardSize=}" ;;
  esac
done

if [ -z "$storageAccount" ] || [ -z "$container" ] || [ -z "$codeArchiveBlob" ]; then
  echo "Missing required storageAccount/container/codeArchiveBlob parameters"
  exit 1
fi

if [ -z "$repoDir" ] || [ "$repoDir" = "/" ]; then
  echo "Refusing unsafe repoDir: $repoDir"
  exit 1
fi

echo "=== Azure Managed Identity Login ==="
az login --identity --output none

echo "=== Preparing Repo Archive ==="
echo "repo: $repoDir"
echo "code archive: $container/$codeArchiveBlob"

archive_path="$(mktemp).tar.gz"

if [ -f "$repoDir/compose/qdrant.yml" ]; then
  docker compose -f "$repoDir/compose/qdrant.yml" down || true
fi

mkdir -p "$repoDir"

find "$repoDir" -mindepth 1 -maxdepth 1 \
  ! -name data \
  ! -name .venv \
  -exec rm -rf {} +

az storage blob download \
  --account-name "$storageAccount" \
  --container-name "$container" \
  --name "$codeArchiveBlob" \
  --file "$archive_path" \
  --auth-mode login \
  --output none

tar -xzf "$archive_path" -C "$repoDir"
rm -f "$archive_path"

unit_name="reverse-wiktionary-splice-$cloudRunId"

echo "=== Starting Background Splice Job ==="
echo "unit: $unit_name"
echo "cloud run id: $cloudRunId"
echo "splice run id: $spliceRunId"

systemd-run \
  --unit "$unit_name" \
  --description "Reverse Wiktionary splice job $cloudRunId" \
  --property "WorkingDirectory=$repoDir" \
  /usr/bin/env bash "$repoDir/scripts/azure/run_splice_job_remote.sh" \
    storageAccount="$storageAccount" \
    container="$container" \
    collectionName="$collectionName" \
    expectedVectorSize="$expectedVectorSize" \
    repoDir="$repoDir" \
    codeArchiveBlob="$codeArchiveBlob" \
    cloudRunId="$cloudRunId" \
    systemdUnit="$unit_name" \
    rawRunId="$rawRunId" \
    vectorRunId="$vectorRunId" \
    spliceRunId="$spliceRunId" \
    upsertBatchSize="$upsertBatchSize" \
    pointIdShardSize="$pointIdShardSize"

echo
echo "Job submitted."
echo "status: logs/$cloudRunId/status.json"
echo "log: logs/$cloudRunId/remote_splice_job.log"
