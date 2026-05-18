#!/usr/bin/env bash
set -euo pipefail

# Azure Run Command payload for web/API smoke testing.

storageAccount="${storageAccount:-}"
container="${container:-}"
codeArchiveBlob="${codeArchiveBlob:-}"
repoDir="${repoDir:-/opt/reverse-wiktionary-web-smoke}"
collectionName="${collectionName:-reverse_wiktionary_v1}"
modelName="${modelName:-sentence-transformers/all-mpnet-base-v2}"
qdrantHnswEf="${qdrantHnswEf:-512}"
qdrantAcornMaxSelectivity="${qdrantAcornMaxSelectivity:-1.0}"
searchExactFiltered="${searchExactFiltered:-false}"
runId="${runId:-$(date -u +%Y%m%dT%H%M%SZ)}"

for parameter in "$@"; do
  case "$parameter" in
    storageAccount=*) storageAccount="${parameter#storageAccount=}" ;;
    container=*) container="${parameter#container=}" ;;
    codeArchiveBlob=*) codeArchiveBlob="${parameter#codeArchiveBlob=}" ;;
    repoDir=*) repoDir="${parameter#repoDir=}" ;;
    collectionName=*) collectionName="${parameter#collectionName=}" ;;
    modelName=*) modelName="${parameter#modelName=}" ;;
    qdrantHnswEf=*) qdrantHnswEf="${parameter#qdrantHnswEf=}" ;;
    qdrantAcornMaxSelectivity=*) qdrantAcornMaxSelectivity="${parameter#qdrantAcornMaxSelectivity=}" ;;
    searchExactFiltered=*) searchExactFiltered="${parameter#searchExactFiltered=}" ;;
    runId=*) runId="${parameter#runId=}" ;;
  esac
done

if [ -z "$storageAccount" ] || [ -z "$container" ] || [ -z "$codeArchiveBlob" ]; then
  echo "Missing required storageAccount/container/codeArchiveBlob parameters"
  exit 1
fi

archivePath="/tmp/reverse-wiktionary-web-smoke-$runId.tar.gz"
webLog="/tmp/reverse-wiktionary-web-smoke-$runId.log"

echo "=== Azure Identity ==="
az login --identity --output none

echo "=== Download Code Archive ==="
az storage blob download \
  --account-name "$storageAccount" \
  --container-name "$container" \
  --name "$codeArchiveBlob" \
  --file "$archivePath" \
  --auth-mode login \
  --overwrite

echo "=== Stop Existing Web App ==="
pkill -f "uvicorn src.web.app:app" >/dev/null 2>&1 || true

echo "=== Extract Repo ==="
rm -rf "$repoDir"
mkdir -p "$repoDir"
tar --no-same-owner -xzf "$archivePath" -C "$repoDir"
cd "$repoDir"

echo "=== Python Environment ==="
python -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "=== Stage Language Taxonomy ==="
mkdir -p data/processed/latest
az storage blob download \
  --account-name "$storageAccount" \
  --container-name "$container" \
  --name "processed/latest.json" \
  --file /tmp/reverse-wiktionary-processed-latest.json \
  --auth-mode login \
  --overwrite \
  --output none

processedRunId="$(jq -r '.run_id' /tmp/reverse-wiktionary-processed-latest.json)"
if [ -z "$processedRunId" ] || [ "$processedRunId" = "null" ]; then
  echo "Could not determine processed run id from processed/latest.json"
  exit 1
fi

az storage blob download \
  --account-name "$storageAccount" \
  --container-name "$container" \
  --name "processed/$processedRunId/language_taxonomy.json" \
  --file data/processed/latest/language_taxonomy.json \
  --auth-mode login \
  --overwrite \
  --output none
echo "taxonomy: processed/$processedRunId/language_taxonomy.json"

az storage blob download \
  --account-name "$storageAccount" \
  --container-name "$container" \
  --name "processed/$processedRunId/serving_metadata.json" \
  --file data/processed/latest/serving_metadata.json \
  --auth-mode login \
  --overwrite \
  --output none
echo "serving metadata: processed/$processedRunId/serving_metadata.json"

echo "=== Start Redis ==="
docker rm -f reverse-wiktionary-redis-smoke >/dev/null 2>&1 || true
docker run -d \
  --name reverse-wiktionary-redis-smoke \
  -p 6379:6379 \
  redis:7 \
  redis-server --appendonly yes >/dev/null

echo "=== Ensure Qdrant ==="
if ! curl -fsS http://localhost:6333/healthz >/dev/null 2>&1; then
  qdrantStorage="/opt/reverse-wiktionary/data/qdrant/storage"

  if [ ! -d "$qdrantStorage" ]; then
    echo "Qdrant is not running and storage was not found: $qdrantStorage"
    exit 1
  fi

  docker rm -f reverse-wiktionary-qdrant-smoke >/dev/null 2>&1 || true
  docker run -d \
    --name reverse-wiktionary-qdrant-smoke \
    -p 6333:6333 \
    -p 6334:6334 \
    -v "$qdrantStorage:/qdrant/storage" \
    qdrant/qdrant:latest >/dev/null
fi

for _ in $(seq 1 90); do
  if curl -fsS http://localhost:6333/healthz >/dev/null 2>&1; then
    break
  fi

  sleep 2
done

curl -fsS "http://localhost:6333/collections/$collectionName" \
  | jq '{status: .result.status, points: .result.points_count, indexed: .result.indexed_vectors_count, queue: .result.update_queue.length}'

echo "=== Start Web App ==="
APP_ENV=development \
COLLECTION_NAME="$collectionName" \
MODEL_NAME="$modelName" \
MODEL_DEVICE=auto \
QDRANT_URL=http://localhost:6333 \
QDRANT_HNSW_EF="$qdrantHnswEf" \
QDRANT_ACORN_MAX_SELECTIVITY="$qdrantAcornMaxSelectivity" \
SEARCH_EXACT_FILTERED="$searchExactFiltered" \
REDIS_URL=redis://localhost:6379/0 \
DEFAULT_LIMIT=5 \
MAX_LIMIT=25 \
LOG_LEVEL=INFO \
SECURE_COOKIES=false \
nohup .venv/bin/uvicorn src.web.app:app --host 127.0.0.1 --port 8000 --workers 1 \
  > "$webLog" 2>&1 &

echo "web log: $webLog"

echo "=== Wait For Health ==="
for _ in $(seq 1 180); do
  if curl -fsS http://127.0.0.1:8000/health >/tmp/reverse-wiktionary-web-health.json 2>/dev/null; then
    jq . /tmp/reverse-wiktionary-web-health.json
    break
  fi

  sleep 2
done

if [ ! -s /tmp/reverse-wiktionary-web-health.json ]; then
  echo "Web health check failed"
  tail -n 120 "$webLog" || true
  exit 1
fi

echo "=== API Search Smoke ==="
curl -fsS \
  -X POST http://127.0.0.1:8000/api/v1/search \
  -H "Content-Type: application/json" \
  --data '{"query":"a book listing words and their meanings","langs":["English"],"pos":["noun"],"limit":5,"offset":0}' \
  | tee /tmp/reverse-wiktionary-web-search.json \
  | jq '{query, limit, offset, has_more, result_count: (.results | length), first_result: .results[0]}'

echo "=== Benchmark Smoke ==="
mkdir -p "runs/web_smoke/$runId"
.venv/bin/python scripts/web/benchmark_search.py \
  --base-url http://127.0.0.1:8000 \
  --routes api ui \
  --iterations 1 \
  --concurrency 1 \
  --limit 5 \
  --output "runs/web_smoke/$runId/benchmark.json" \
  --samples-output "runs/web_smoke/$runId/benchmark_samples.json"

echo "=== Upload Web Smoke Artifacts ==="
az storage blob upload-batch \
  --account-name "$storageAccount" \
  --destination "$container" \
  --destination-path "logs/web_smoke/$runId" \
  --source "runs/web_smoke/$runId" \
  --auth-mode login \
  --overwrite \
  --output table

az storage blob upload \
  --account-name "$storageAccount" \
  --container-name "$container" \
  --name "logs/web_smoke/$runId/web.log" \
  --file "$webLog" \
  --auth-mode login \
  --overwrite \
  --output table

echo "=== Web Log Tail ==="
tail -n 80 "$webLog" || true
