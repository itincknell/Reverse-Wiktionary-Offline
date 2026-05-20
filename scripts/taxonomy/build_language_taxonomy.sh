#!/usr/bin/env bash
set -euo pipefail

# Build language taxonomy artifacts from a local processed metadata file.

SERVING_METADATA=""
OUTPUT_DIR=""
GLOTTOLOG_VERSION="5.3"
GLOTTOLOG_CSV=""
OVERRIDES="src/taxonomy/language_taxonomy_overrides.json"
AUTO_THRESHOLD="0.96"
REVIEW_THRESHOLD="0.75"
STREAM_REVIEWS=false
PYTHON_BIN="${PYTHON:-python3}"

usage() {
  cat <<'EOF'
Build language taxonomy artifacts from processed metadata.

Required:
  --serving-metadata PATH

Optional:
  --output-dir PATH
      Defaults to the processed metadata directory.
  --glottolog-version VERSION
      Defaults to 5.3.
  --glottolog-csv PATH
      Defaults to data/reference/glottolog/<version>/glottolog_languoid.csv.
  --overrides PATH
      Defaults to src/taxonomy/language_taxonomy_overrides.json.
  --auto-threshold FLOAT
      Fuzzy match score required for automatic selectable matches.
      Defaults to 0.96.
  --review-threshold FLOAT
      Fuzzy match score required to emit a non-selectable review candidate.
      Defaults to 0.75.
  --stream-reviews
      Print JSONL review/unmatched candidates while matching.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --serving-metadata)
      SERVING_METADATA="$2"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --glottolog-version)
      GLOTTOLOG_VERSION="$2"
      shift 2
      ;;
    --glottolog-csv)
      GLOTTOLOG_CSV="$2"
      shift 2
      ;;
    --overrides)
      OVERRIDES="$2"
      shift 2
      ;;
    --auto-threshold)
      AUTO_THRESHOLD="$2"
      shift 2
      ;;
    --review-threshold)
      REVIEW_THRESHOLD="$2"
      shift 2
      ;;
    --stream-reviews)
      STREAM_REVIEWS=true
      shift
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

if [ -z "$SERVING_METADATA" ]; then
  echo "Missing required argument: --serving-metadata"
  exit 1
fi

if [ ! -f "$SERVING_METADATA" ]; then
  echo "Serving metadata not found: $SERVING_METADATA"
  exit 1
fi

if [ -z "$OUTPUT_DIR" ]; then
  OUTPUT_DIR="$(dirname "$SERVING_METADATA")"
fi

if [ -z "$GLOTTOLOG_CSV" ]; then
  GLOTTOLOG_CSV="data/reference/glottolog/$GLOTTOLOG_VERSION/glottolog_languoid.csv"
fi

if [ ! -f "$GLOTTOLOG_CSV" ]; then
  scripts/taxonomy/download_glottolog.sh --version "$GLOTTOLOG_VERSION"
fi

ARGS=(
  -m src.taxonomy.build_language_taxonomy
  --serving-metadata "$SERVING_METADATA" \
  --glottolog-csv "$GLOTTOLOG_CSV" \
  --output-dir "$OUTPUT_DIR" \
  --overrides "$OVERRIDES" \
  --glottolog-version "$GLOTTOLOG_VERSION" \
  --auto-threshold "$AUTO_THRESHOLD" \
  --review-threshold "$REVIEW_THRESHOLD"
)

if [ "$STREAM_REVIEWS" = true ]; then
  ARGS+=(--stream-reviews)
fi

"$PYTHON_BIN" "${ARGS[@]}"
