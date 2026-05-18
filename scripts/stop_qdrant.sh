#!/usr/bin/env bash

set -euo pipefail

COMPOSE_FILE="compose/qdrant.yml"

docker compose -f "$COMPOSE_FILE" down
