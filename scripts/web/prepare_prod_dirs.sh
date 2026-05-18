#!/usr/bin/env bash
set -euo pipefail

ROOT="${REVERSE_WIKTIONARY_DATA_ROOT:-/mnt/reverse-wiktionary}"
APP_DIR="${REVERSE_WIKTIONARY_APP_DIR:-/opt/reverse-wiktionary/app}"

mkdir -p "$APP_DIR"
mkdir -p "$ROOT/qdrant/storage"
mkdir -p "$ROOT/redis/data"
mkdir -p "$ROOT/logs/nginx"
mkdir -p "$ROOT/snapshots"

echo "app dir: $APP_DIR"
echo "data root: $ROOT"

