#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-deploy/web/compose.local.yml}"

docker compose -f "$COMPOSE_FILE" down

