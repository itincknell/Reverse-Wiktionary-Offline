#!/usr/bin/env bash

set -euo pipefail

PROCESSED_DIR="data/processed/latest"
EMBEDDINGS_ROOT="data/embeddings"
QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"

COLLECTION_NAME="reverse_wiktionary_test"
MODEL_NAME="sentence-transformers/all-MiniLM-L6-v2"

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
BATCH_SIZE=32
QUEUE_SIZE=2
MAX_SHARDS=1
LIMIT_ROWS=200
POINT_ID_SHARD_SIZE=50000

if [ ! -d "$PROCESSED_DIR" ]; then
  echo "Processed latest directory not found: $PROCESSED_DIR"
  echo "Run the preprocessing script first."
  exit 1
fi

if ! compgen -G "$PROCESSED_DIR/shard_*.jsonl" > /dev/null; then
  echo "No processed shard files found in: $PROCESSED_DIR"
  exit 1
fi

echo "=== Qdrant Health Check ==="
curl -fsS "$QDRANT_URL/healthz" || {
  echo
  echo "Qdrant is not reachable at $QDRANT_URL"
  echo "Start it with something like:"
  echo "docker run -d --name qdrant -p 6333:6333 -v \"\$(pwd)/qdrant_storage:/qdrant/storage\" qdrant/qdrant"
  exit 1
}

echo
echo "=== Running Embedding Test ==="

python ./src/embeddings/generate_embeddings.py \
  --processed-dir "$PROCESSED_DIR" \
  --output-root "$EMBEDDINGS_ROOT" \
  --qdrant-url "$QDRANT_URL" \
  --collection-name "$COLLECTION_NAME" \
  --model-name "$MODEL_NAME" \
  --device auto \
  --batch-size "$BATCH_SIZE" \
  --queue-size "$QUEUE_SIZE" \
  --point-id-shard-size "$POINT_ID_SHARD_SIZE" \
  --recreate-collection \
  --run-id "$RUN_ID" \
  --max-shards "$MAX_SHARDS" \
  --limit-rows "$LIMIT_ROWS" \
  --progress-every 5000

MANIFEST="$EMBEDDINGS_ROOT/$RUN_ID/manifest.json"

echo
echo "=== Manifest Check ==="

if [ ! -f "$MANIFEST" ]; then
  echo "Expected manifest not found: $MANIFEST"
  exit 1
fi

jq . "$MANIFEST" > /dev/null

jq '{
  run_id,
  processed_run_id,
  model,
  qdrant,
  config,
  metrics,
  shards
}' "$MANIFEST"

echo
echo "=== Validate Manifest Metrics ==="

ROWS_EMBEDDED="$(jq -r '.metrics.rows_embedded' "$MANIFEST")"
SHARDS_COMPLETED="$(jq -r '.metrics.shards_completed' "$MANIFEST")"

if [ "$ROWS_EMBEDDED" -le 0 ]; then
  echo "Expected rows_embedded > 0, got $ROWS_EMBEDDED"
  exit 1
fi

if [ "$SHARDS_COMPLETED" -le 0 ]; then
  echo "Expected shards_completed > 0, got $SHARDS_COMPLETED"
  exit 1
fi

echo "rows_embedded: $ROWS_EMBEDDED"
echo "shards_completed: $SHARDS_COMPLETED"

echo
echo "=== Validate Qdrant Collection ==="

curl -fsS "$QDRANT_URL/collections/$COLLECTION_NAME" | jq .

POINT_COUNT="$(curl -fsS "$QDRANT_URL/collections/$COLLECTION_NAME" | jq -r '.result.points_count // .result.vectors_count // 0')"

echo "qdrant reported point count: $POINT_COUNT"

if [ "$POINT_COUNT" -le 0 ]; then
  echo "Expected Qdrant point count > 0"
  exit 1
fi

echo
echo "=== Smoke Search ==="

curl -fsS \
  -X POST "$QDRANT_URL/collections/$COLLECTION_NAME/points/scroll" \
  -H "Content-Type: application/json" \
  -d '{"limit": 3, "with_payload": true, "with_vector": false}' | jq .

echo
echo "=== Test Complete ==="
echo "run id: $RUN_ID"
echo "manifest: $MANIFEST"
echo "collection: $COLLECTION_NAME"