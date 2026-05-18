#!/usr/bin/env bash

set -euo pipefail

# Download and prepare the Kaikki/Wiktextract JSONL dump.
#
# Interactive default:
#   If no existing dump is found, download/decompress without prompting.
#   If an existing timestamped dump is found, ask whether to download a new copy.
#
# Scripted modes:
#   --use-existing
#       Never download a new copy if a timestamped dump already exists.
#       Ensure the latest existing compressed dump is decompressed.
#
#   --download-new
#       Always download a new copy into a fresh timestamped folder.
#
#   --yes
#       Non-interactive default-yes mode. Equivalent to choosing to download
#       a new copy when prompted.
#
#   --root-dir PATH
#       Override the root output directory.
#
#   --url URL
#       Override the source download URL.
#
# Examples:
#   ./scripts/download_wiktionary_dump.sh
#   ./scripts/download_wiktionary_dump.sh --use-existing
#   ./scripts/download_wiktionary_dump.sh --download-new
#   ./scripts/download_wiktionary_dump.sh --yes

URL="https://kaikki.org/dictionary/raw-wiktextract-data.jsonl.gz"
ROOT_DIR="data/raw"
GZ_NAME="raw-wiktextract-data.jsonl.gz"
JSONL_NAME="wiktionary.jsonl"
LATEST_LINK=""
MODE="interactive"

usage() {
  sed -n '5,38p' "$0"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --use-existing)
      MODE="use-existing"
      shift
      ;;
    --download-new)
      MODE="download-new"
      shift
      ;;
    --yes|-y)
      MODE="download-new"
      shift
      ;;
    --root-dir)
      ROOT_DIR="$2"
      shift 2
      ;;
    --url)
      URL="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

LATEST_LINK="$ROOT_DIR/latest"

timestamp_to_date() {
  local ts="$1"

  if date -u -d "${ts:0:8} ${ts:9:6}" "+%Y-%m-%d %H:%M:%S UTC" >/dev/null 2>&1; then
    date -u -d "${ts:0:8} ${ts:9:6}" "+%Y-%m-%d %H:%M:%S UTC"
  else
    date -j -u -f "%Y%m%dT%H%M%SZ" "$ts" "+%Y-%m-%d %H:%M:%S UTC"
  fi
}

latest_run_id() {
  if [ ! -d "$ROOT_DIR" ]; then
    return 0
  fi

  find "$ROOT_DIR" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; \
    | grep -E '^[0-9]{8}T[0-9]{6}Z$' \
    | sort \
    | tail -n 1
}

write_metadata() {
  local out_dir="$1"
  local gz_path="$out_dir/$GZ_NAME"
  local jsonl_path="$out_dir/$JSONL_NAME"
  local metadata_path="$out_dir/metadata.json"

  local compressed_size
  local uncompressed_size
  local updated_at

  compressed_size="$(wc -c < "$gz_path" | tr -d ' ')"
  uncompressed_size="$(wc -c < "$jsonl_path" | tr -d ' ')"
  updated_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  cat > "$metadata_path" <<EOF
{
  "source_url": "$URL",
  "updated_at_utc": "$updated_at",
  "compressed_path": "$gz_path",
  "uncompressed_path": "$jsonl_path",
  "compressed_size_bytes": $compressed_size,
  "uncompressed_size_bytes": $uncompressed_size
}
EOF
}

ensure_decompressed() {
  local out_dir="$1"
  local gz_path="$out_dir/$GZ_NAME"
  local jsonl_path="$out_dir/$JSONL_NAME"
  local tmp_path="$jsonl_path.tmp"

  if [ ! -f "$gz_path" ]; then
    echo "Missing compressed file: $gz_path"
    exit 1
  fi

  if [ -f "$jsonl_path" ]; then
    echo "Uncompressed file already exists: $jsonl_path"
    return 0
  fi

  echo "Validating compressed file..."
  gzip -t "$gz_path"

  echo "Decompressing..."
  rm -f "$tmp_path"
  gunzip -c "$gz_path" > "$tmp_path"
  mv "$tmp_path" "$jsonl_path"
}

download_new() {
  local run_id
  local out_dir
  local gz_path

  run_id="$(date -u +%Y%m%dT%H%M%SZ)"
  out_dir="$ROOT_DIR/$run_id"
  gz_path="$out_dir/$GZ_NAME"

  mkdir -p "$out_dir"

  echo "Downloading new dump..."
  echo "Output directory: $out_dir"

  curl -L "$URL" -o "$gz_path"

  ensure_decompressed "$out_dir"
  write_metadata "$out_dir"

  rm -f "$LATEST_LINK"
  ln -s "$run_id" "$LATEST_LINK"

  echo "Done."
  echo "Output directory: $out_dir"
  echo "Latest symlink: $LATEST_LINK"
  du -sh "$out_dir/$GZ_NAME" "$out_dir/$JSONL_NAME"
}

use_existing() {
  local run_id="$1"
  local out_dir="$ROOT_DIR/$run_id"

  ensure_decompressed "$out_dir"
  write_metadata "$out_dir"

  rm -f "$LATEST_LINK"
  ln -s "$run_id" "$LATEST_LINK"

  echo "Done."
  echo "Using existing directory: $out_dir"
  echo "Latest symlink: $LATEST_LINK"
  du -sh "$out_dir/$GZ_NAME" "$out_dir/$JSONL_NAME"
}

mkdir -p "$ROOT_DIR"

EXISTING_RUN_ID="$(latest_run_id || true)"

if [ -z "$EXISTING_RUN_ID" ]; then
  download_new
  exit 0
fi

if [ "$MODE" = "download-new" ]; then
  download_new
  exit 0
fi

if [ "$MODE" = "use-existing" ]; then
  use_existing "$EXISTING_RUN_ID"
  exit 0
fi

EXISTING_DIR="$ROOT_DIR/$EXISTING_RUN_ID"
EXISTING_DATE="$(timestamp_to_date "$EXISTING_RUN_ID")"

echo "Existing dump detected:"
echo "$EXISTING_DIR"
echo "$EXISTING_DATE"

if [ -f "$EXISTING_DIR/$GZ_NAME" ]; then
  echo "Compressed file exists: $EXISTING_DIR/$GZ_NAME"
fi

if [ -f "$EXISTING_DIR/$JSONL_NAME" ]; then
  echo "Uncompressed file exists: $EXISTING_DIR/$JSONL_NAME"
else
  echo "Uncompressed file missing; keeping this dump will decompress it."
fi

read -r -p "Download a new copy? [y/N] " CONFIRM

if [[ "$CONFIRM" =~ ^[Yy]$ ]]; then
  download_new
  exit 0
fi

use_existing "$EXISTING_RUN_ID"