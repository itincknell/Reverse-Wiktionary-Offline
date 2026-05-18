#!/usr/bin/env bash

set -euo pipefail

COMPOSE_FILE="deploy/compose/qdrant.yml"

docker compose -f "$COMPOSE_FILE" down