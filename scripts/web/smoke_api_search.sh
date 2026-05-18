#!/usr/bin/env bash
set -euo pipefail

WEB_URL="${WEB_URL:-http://127.0.0.1:8000}"
QUERY="${QUERY:-a book listing words and their meanings}"

curl -fsS \
  -X POST "$WEB_URL/api/v1/search" \
  -H "Content-Type: application/json" \
  --data "$(jq -n --arg query "$QUERY" '{
    query: $query,
    langs: [],
    pos: [],
    limit: 5,
    offset: 0
  }')" \
  | jq .

