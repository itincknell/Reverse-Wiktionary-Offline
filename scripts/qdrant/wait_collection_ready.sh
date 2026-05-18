#!/usr/bin/env bash
set -euo pipefail

QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
COLLECTION_NAME=""
TIMEOUT_SECONDS=3600
POLL_INTERVAL_SECONDS=30

usage() {
  cat <<'EOF'
Wait for a Qdrant collection to reach a steady state.

Required:
  --collection-name NAME

Optional:
  --qdrant-url URL
      Defaults to QDRANT_URL or http://localhost:6333.
  --timeout-seconds SECONDS
      Defaults to 3600.
  --poll-interval-seconds SECONDS
      Defaults to 30.
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
    --timeout-seconds)
      TIMEOUT_SECONDS="$2"
      shift 2
      ;;
    --poll-interval-seconds)
      POLL_INTERVAL_SECONDS="$2"
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

deadline=$((SECONDS + TIMEOUT_SECONDS))

while [ "$SECONDS" -lt "$deadline" ]; do
  collection_json="$(curl -fsS "$QDRANT_URL/collections/$COLLECTION_NAME")"
  status="$(jq -r '.result.status // "unknown"' <<< "$collection_json")"
  optimizer_status="$(jq -r '.result.optimizer_status // "unknown"' <<< "$collection_json")"
  queue_length="$(jq -r '.result.update_queue.length // 0' <<< "$collection_json")"
  points_count="$(jq -r '.result.points_count // 0' <<< "$collection_json")"
  indexed_count="$(jq -r '.result.indexed_vectors_count // 0' <<< "$collection_json")"

  echo "status=$status optimizer=$optimizer_status queue=$queue_length points=$points_count indexed=$indexed_count"

  if [ "$status" = "green" ] && [ "$queue_length" = "0" ]; then
    case "$optimizer_status" in
      ok|green|true)
        exit 0
        ;;
    esac
  fi

  sleep "$POLL_INTERVAL_SECONDS"
done

echo "Timed out waiting for collection to settle: $COLLECTION_NAME"
exit 1
