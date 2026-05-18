#!/usr/bin/env bash

set -euo pipefail

QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
COLLECTION_NAME="${COLLECTION_NAME:-reverse_wiktionary_test}"
MODEL_NAME="${MODEL_NAME:-sentence-transformers/all-MiniLM-L6-v2}"
OUTPUT="data/embeddings/quality_report.json"

echo "=== Qdrant Health Check ==="
curl -fsS "$QDRANT_URL/healthz" > /dev/null

echo "=== Running Embedding Quality Sanity Check ==="

python ./src/embeddings/evaluate_embedding_quality.py \
  --qdrant-url "$QDRANT_URL" \
  --collection-name "$COLLECTION_NAME" \
  --model-name "$MODEL_NAME" \
  --device auto \
  --top-k 10 \
  --output "$OUTPUT"

echo
echo "=== Report Preview ==="
jq '.summary' "$OUTPUT"