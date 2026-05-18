#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-deploy/web/compose.prod.yml}"

docker compose -f "$COMPOSE_FILE" ps

