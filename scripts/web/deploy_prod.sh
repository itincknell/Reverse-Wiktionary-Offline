#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-deploy/web/compose.prod.yml}"
WEB_URL="${WEB_URL:-http://127.0.0.1}"

./scripts/web/prepare_prod_dirs.sh

docker compose -f "$COMPOSE_FILE" up -d --build

echo "waiting for web health..."
for _ in $(seq 1 60); do
  if curl -fsS "$WEB_URL/health" >/dev/null; then
    curl -fsS "$WEB_URL/health" | jq .
    exit 0
  fi

  sleep 2
done

echo "web health check failed: $WEB_URL/health"
docker compose -f "$COMPOSE_FILE" ps
docker compose -f "$COMPOSE_FILE" logs --tail 100 web
exit 1

