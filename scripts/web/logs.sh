#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-deploy/web/compose.prod.yml}"
SERVICE="${1:-web}"

docker compose -f "$COMPOSE_FILE" logs -f "$SERVICE"

