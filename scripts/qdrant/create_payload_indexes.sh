#!/usr/bin/env bash
set -euo pipefail

# Create the payload indexes required by the serving layer.

QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
COLLECTION_NAME=""

usage() {
  sed -n '3,36p' "$0"
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

create_index() {
  local field_name="$1"

  curl -fsS -X PUT \
    "$QDRANT_URL/collections/$COLLECTION_NAME/index?wait=true" \
    -H "Content-Type: application/json" \
    --data "{\"field_name\":\"$field_name\",\"field_schema\":\"keyword\"}" \
    >/dev/null

  echo "payload index ready: $field_name"
}

create_index "lang"
create_index "pos"

