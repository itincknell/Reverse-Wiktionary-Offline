#!/usr/bin/env bash

set -euo pipefail

COMPOSE_FILE="deploy/compose/qdrant.yml"

docker compose -f "$COMPOSE_FILE" up -d

echo
echo "=== Waiting for Qdrant ==="

until curl -fsS http://localhost:6333/healthz > /dev/null; do
  sleep 1
  echo "waiting for qdrant..."
done

echo
echo "Qdrant is healthy."
echo "HTTP: http://localhost:6333"
echo "Storage: ./qdrant_storage"