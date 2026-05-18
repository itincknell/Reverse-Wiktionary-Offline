#!/usr/bin/env bash
set -euo pipefail

WEB_URL="${WEB_URL:-http://127.0.0.1:8000}"

curl -fsS "$WEB_URL/health" | jq .

