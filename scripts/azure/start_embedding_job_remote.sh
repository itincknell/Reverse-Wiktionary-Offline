#!/usr/bin/env bash
set -euo pipefail

# Azure Run Command entrypoint for starting a background embedding job.

storageAccount="${storageAccount:-}"
container="${container:-}"
processedRunId="${processedRunId:-latest}"
collectionName="${collectionName:-reverse_wiktionary_v2}"
modelName="${modelName:-sentence-transformers/distiluse-base-multilingual-cased-v2}"
expectedVectorSize="${expectedVectorSize:-512}"
repoDir="${repoDir:-/opt/reverse-wiktionary}"
codeArchiveBlob="${codeArchiveBlob:-}"
cloudRunId="${cloudRunId:-$(date -u +%Y%m%dT%H%M%SZ)}"
prepareProcessedIfMissing="${prepareProcessedIfMissing:-false}"
prepareProcessedFromRaw="${prepareProcessedFromRaw:-false}"
allowRawDownload="${allowRawDownload:-false}"
resumeEmbeddingRunId="${resumeEmbeddingRunId:-}"

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
    expectedVectorSize=*)
      expectedVectorSize="${parameter#expectedVectorSize=}"
      ;;
    repoDir=*)
      repoDir="${parameter#repoDir=}"
      ;;
    codeArchiveBlob=*)
      codeArchiveBlob="${parameter#codeArchiveBlob=}"
      ;;
    cloudRunId=*)
      cloudRunId="${parameter#cloudRunId=}"
      ;;
    prepareProcessedIfMissing=*)
      prepareProcessedIfMissing="${parameter#prepareProcessedIfMissing=}"
      ;;
    prepareProcessedFromRaw=*)
      prepareProcessedFromRaw="${parameter#prepareProcessedFromRaw=}"
      ;;
    allowRawDownload=*)
      allowRawDownload="${parameter#allowRawDownload=}"
      ;;
    resumeEmbeddingRunId=*)
      resumeEmbeddingRunId="${parameter#resumeEmbeddingRunId=}"
      ;;
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

rm -rf "$repoDir"
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

unit_name="reverse-wiktionary-$cloudRunId"

echo "=== Starting Background Embedding Job ==="
echo "unit: $unit_name"
echo "cloud run id: $cloudRunId"

systemd-run \
  --unit "$unit_name" \
  --description "Reverse Wiktionary offline embedding job $cloudRunId" \
  --property "WorkingDirectory=$repoDir" \
  /usr/bin/env bash "$repoDir/scripts/azure/run_embedding_job_remote.sh" \
    storageAccount="$storageAccount" \
    container="$container" \
    processedRunId="$processedRunId" \
    collectionName="$collectionName" \
    modelName="$modelName" \
    expectedVectorSize="$expectedVectorSize" \
    repoDir="$repoDir" \
    codeArchiveBlob="$codeArchiveBlob" \
    cloudRunId="$cloudRunId" \
    systemdUnit="$unit_name" \
    repoPrepared=true \
    prepareProcessedIfMissing="$prepareProcessedIfMissing" \
    prepareProcessedFromRaw="$prepareProcessedFromRaw" \
    allowRawDownload="$allowRawDownload" \
    resumeEmbeddingRunId="$resumeEmbeddingRunId"

echo
echo "Job submitted."
echo "status: logs/$cloudRunId/status.json"
echo "log: logs/$cloudRunId/remote_embedding_job.log"
