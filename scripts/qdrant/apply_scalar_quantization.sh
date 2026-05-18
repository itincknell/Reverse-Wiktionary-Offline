#!/usr/bin/env bash
set -euo pipefail

# Enable scalar int8 quantization for an existing Qdrant collection.
#
# This is intended for serving-size experiments. The default mode keeps
# quantized vectors in RAM and moves original float vectors to disk, which is
# the first configuration to test when reducing RAM without changing embeddings.

QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
COLLECTION_NAME=""
QUANTILE="0.99"
ALWAYS_RAM="true"
ON_DISK="true"
TIMEOUT_SECONDS="300"

usage() {
  cat <<'EOF'
Enable scalar int8 quantization for an existing Qdrant collection.

Required:
  --collection-name NAME

Optional:
  --qdrant-url URL
      Defaults to QDRANT_URL or http://localhost:6333.
  --quantile N
      Defaults to 0.99.
  --always-ram true|false
      Keep quantized vectors in RAM. Defaults to true.
  --on-disk true|false
      Move original vectors to disk. Defaults to true.
  --timeout-seconds SECONDS
      Qdrant update request timeout. Defaults to 300.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --qdrant-url)
      QDRANT_URL="$2"
      shift 2
      ;;
    --collection-name)
      COLLECTION_NAME="$2"
      shift 2
      ;;
    --quantile)
      QUANTILE="$2"
      shift 2
      ;;
    --always-ram)
      ALWAYS_RAM="$2"
      shift 2
      ;;
    --on-disk)
      ON_DISK="$2"
      shift 2
      ;;
    --timeout-seconds)
      TIMEOUT_SECONDS="$2"
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

if [ -z "$COLLECTION_NAME" ]; then
  echo "Missing required argument: --collection-name"
  exit 1
fi

echo "=== Current Collection Config ==="
curl -fsS "$QDRANT_URL/collections/$COLLECTION_NAME" \
  | jq '.result.config | {params, hnsw_config, quantization_config}'

echo
echo "=== Applying Scalar Quantization ==="
curl -fsS -X PATCH \
  "$QDRANT_URL/collections/$COLLECTION_NAME?timeout=$TIMEOUT_SECONDS" \
  -H "Content-Type: application/json" \
  --data "{
    \"vectors\": {
      \"\": {
        \"on_disk\": $ON_DISK
      }
    },
    \"quantization_config\": {
      \"scalar\": {
        \"type\": \"int8\",
        \"quantile\": $QUANTILE,
        \"always_ram\": $ALWAYS_RAM
      }
    }
  }" \
  | jq .

echo
echo "=== Updated Collection Config ==="
curl -fsS "$QDRANT_URL/collections/$COLLECTION_NAME" \
  | jq '.result | {status, optimizer_status, points_count, indexed_vectors_count, segments_count, config: .config}'

cat <<EOF

Monitor optimization:
  watch -n 15 'curl -fsS "$QDRANT_URL/collections/$COLLECTION_NAME" | jq "{status: .result.status, optimizer: .result.optimizer_status, points: .result.points_count, indexed: .result.indexed_vectors_count, segments: .result.segments_count, quantization: .result.config.quantization_config, vectors: .result.config.params.vectors}"'

After optimization is stable, restart Qdrant before measuring RSS:
  docker restart reverse-wiktionary-qdrant-smoke
EOF
