#!/usr/bin/env bash
set -euo pipefail

# Verify the payload indexes required by the serving layer.

QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
COLLECTION_NAME=""

usage() {
  sed -n '3,33p' "$0"
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

collection_json="$(curl -fsS "$QDRANT_URL/collections/$COLLECTION_NAME")"

for field_name in lang pos; do
  data_type="$(
    jq -r --arg field_name "$field_name" \
      '.result.payload_schema[$field_name].data_type // empty' \
      <<< "$collection_json"
  )"

  if [ "$data_type" != "keyword" ]; then
    echo "Missing keyword payload index: $field_name"
    exit 1
  fi

  echo "payload index verified: $field_name"
done

