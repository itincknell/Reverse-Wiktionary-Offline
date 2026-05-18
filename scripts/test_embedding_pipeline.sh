#!/usr/bin/env bash
set -euo pipefail

./scripts/start_qdrant.sh

# Always stop the local Qdrant container, while preserving the test failure
# status from any command above or below this trap.
trap './scripts/stop_qdrant.sh' EXIT

./scripts/test_generate_embeddings.sh
