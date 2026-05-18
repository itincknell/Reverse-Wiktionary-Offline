#!/usr/bin/env bash
set -euo pipefail

# Run the serving benchmark cases used for VM sizing and capture local artifacts.

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
COLLECTION_NAME="${COLLECTION_NAME:-reverse_wiktionary_v1}"
RUN_ID="${RUN_ID:-sizing-$(date -u +%Y%m%dT%H%M%SZ)}"
OUTPUT_ROOT="${OUTPUT_ROOT:-runs/web_smoke}"
ITERATIONS="20"
CONCURRENCY="4"
LIMIT="10"
STORAGE_ACCOUNT=""
CONTAINER=""

usage() {
  cat <<'EOF'
Run serving benchmark cases used for VM sizing and capture local artifacts.

Optional:
  --base-url URL
      Defaults to BASE_URL or http://127.0.0.1:8000.
  --qdrant-url URL
      Defaults to QDRANT_URL or http://localhost:6333.
  --collection-name NAME
      Defaults to reverse_wiktionary_v1.
  --run-id RUN_ID
      Defaults to sizing-<UTC timestamp>.
  --output-root PATH
      Defaults to runs/web_smoke.
  --iterations N
      Defaults to 20.
  --concurrency N
      Defaults to 4.
  --limit N
      Defaults to 10.
  --storage-account NAME
      Upload artifacts when paired with --container.
  --container NAME
      Upload artifacts when paired with --storage-account.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --base-url)
      BASE_URL="$2"
      shift 2
      ;;
    --qdrant-url)
      QDRANT_URL="$2"
      shift 2
      ;;
    --collection-name)
      COLLECTION_NAME="$2"
      shift 2
      ;;
    --run-id)
      RUN_ID="$2"
      shift 2
      ;;
    --output-root)
      OUTPUT_ROOT="$2"
      shift 2
      ;;
    --iterations)
      ITERATIONS="$2"
      shift 2
      ;;
    --concurrency)
      CONCURRENCY="$2"
      shift 2
      ;;
    --limit)
      LIMIT="$2"
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

RUN_DIR="$OUTPUT_ROOT/$RUN_ID"
mkdir -p "$RUN_DIR"

write_json() {
  local output_path="$1"
  shift
  "$@" > "$output_path"
}

echo "=== Capturing Baseline Artifacts ==="
date -u +"%Y-%m-%dT%H:%M:%SZ" > "$RUN_DIR/started_at_utc.txt"
write_json "$RUN_DIR/qdrant_collection.json" \
  curl -fsS "$QDRANT_URL/collections/$COLLECTION_NAME"
sudo docker stats --no-stream > "$RUN_DIR/docker_stats.txt" || docker stats --no-stream > "$RUN_DIR/docker_stats.txt" || true
ps aux --sort=-rss | head -30 > "$RUN_DIR/top_rss_processes.txt" || true
df -h > "$RUN_DIR/disk_usage.txt" || true

echo "=== Benchmark: unfiltered ==="
python3 scripts/web/benchmark_search.py \
  --base-url "$BASE_URL" \
  --routes api \
  --iterations "$ITERATIONS" \
  --concurrency "$CONCURRENCY" \
  --limit "$LIMIT" \
  --output "$RUN_DIR/benchmark-unfiltered.json" \
  --samples-output "$RUN_DIR/benchmark-unfiltered-samples.json"

echo "=== Benchmark: English filter ==="
python3 scripts/web/benchmark_search.py \
  --base-url "$BASE_URL" \
  --routes api \
  --iterations "$ITERATIONS" \
  --concurrency "$CONCURRENCY" \
  --limit "$LIMIT" \
  --langs English \
  --output "$RUN_DIR/benchmark-english.json" \
  --samples-output "$RUN_DIR/benchmark-english-samples.json"

echo "=== Benchmark: French filter ==="
python3 scripts/web/benchmark_search.py \
  --base-url "$BASE_URL" \
  --routes api \
  --iterations "$ITERATIONS" \
  --concurrency "$CONCURRENCY" \
  --limit "$LIMIT" \
  --langs French \
  --output "$RUN_DIR/benchmark-french.json" \
  --samples-output "$RUN_DIR/benchmark-french-samples.json"

echo "=== Capturing Final Artifacts ==="
date -u +"%Y-%m-%dT%H:%M:%SZ" > "$RUN_DIR/finished_at_utc.txt"
write_json "$RUN_DIR/qdrant_collection_after.json" \
  curl -fsS "$QDRANT_URL/collections/$COLLECTION_NAME"
sudo docker stats --no-stream > "$RUN_DIR/docker_stats_after.txt" || docker stats --no-stream > "$RUN_DIR/docker_stats_after.txt" || true
ps aux --sort=-rss | head -30 > "$RUN_DIR/top_rss_processes_after.txt" || true

if [ -n "$STORAGE_ACCOUNT" ] && [ -n "$CONTAINER" ]; then
  echo "=== Uploading Benchmark Artifacts ==="
  az storage blob upload-batch \
    --account-name "$STORAGE_ACCOUNT" \
    --destination "$CONTAINER" \
    --destination-path "logs/web_smoke/$RUN_ID" \
    --source "$RUN_DIR" \
    --auth-mode login \
    --overwrite \
    --output table
fi

echo
echo "Benchmark artifacts: $RUN_DIR"
