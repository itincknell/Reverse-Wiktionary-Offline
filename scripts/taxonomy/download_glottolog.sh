#!/usr/bin/env bash
set -euo pipefail

# Download and cache the Glottolog languoid CSV used by taxonomy matching.

VERSION="5.3"
DEST_ROOT="data/reference/glottolog"
URL="https://glottolog.org/meta/downloads"
PYTHON_BIN="${PYTHON:-python3}"

usage() {
  cat <<'EOF'
Download Glottolog languoid CSV.

Optional:
  --version VERSION
      Defaults to 5.3.
  --dest-root PATH
      Defaults to data/reference/glottolog.
  --url URL
      Defaults to the Glottolog downloads page. If a direct zip URL is passed,
      it is used as-is.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --version)
      VERSION="$2"
      shift 2
      ;;
    --dest-root)
      DEST_ROOT="$2"
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

DEST_DIR="$DEST_ROOT/$VERSION"
ZIP_PATH="$DEST_DIR/glottolog_languoid.csv.zip"
CSV_PATH="$DEST_DIR/glottolog_languoid.csv"
METADATA_PATH="$DEST_DIR/metadata.json"

mkdir -p "$DEST_DIR"

if [ -f "$CSV_PATH" ]; then
  echo "Glottolog CSV already exists: $CSV_PATH"
  exit 0
fi

echo "=== Downloading Glottolog ==="
echo "version: $VERSION"
echo "url: $URL"
echo "destination: $DEST_DIR"

"$PYTHON_BIN" - "$URL" "$VERSION" "$ZIP_PATH" <<'PY'
import re
import sys
import urllib.request
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

source_url = sys.argv[1]
version = sys.argv[2]
zip_path = Path(sys.argv[3])

if source_url.endswith(".zip"):
    download_url = source_url
else:
    html = urllib.request.urlopen(source_url).read().decode("utf-8")
    version_pattern = re.compile(
        rf"Version {re.escape(version)}.*?glottolog_languoid\.csv\.zip",
        re.IGNORECASE | re.DOTALL,
    )
    match = version_pattern.search(html)
    if not match:
        raise SystemExit(f"Could not find Glottolog {version} languoid CSV link")

    section_start = html.rfind("<a", 0, match.end())
    section_end = html.find("</a>", match.end())
    anchor = html[section_start:section_end]
    href_match = re.search(r'href="([^"]+)"', anchor)
    if not href_match:
        raise SystemExit(f"Could not extract Glottolog {version} download href")
    download_url = urljoin(source_url, unescape(href_match.group(1)))

print(download_url)
with urllib.request.urlopen(download_url) as response:
    zip_path.write_bytes(response.read())
PY
"$PYTHON_BIN" - "$ZIP_PATH" "$CSV_PATH" <<'PY'
import sys
import zipfile
from pathlib import Path

zip_path = Path(sys.argv[1])
csv_path = Path(sys.argv[2])

with zipfile.ZipFile(zip_path) as archive:
    csv_members = [name for name in archive.namelist() if name.endswith(".csv")]
    if not csv_members:
        raise SystemExit(f"No CSV file found in {zip_path}")
    with archive.open(csv_members[0]) as source:
        csv_path.write_bytes(source.read())
PY

cat > "$METADATA_PATH" <<EOF
{
  "source": "Glottolog",
  "version": "$VERSION",
  "url": "$URL",
  "csv_path": "$CSV_PATH",
  "downloaded_at_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

echo "Downloaded: $CSV_PATH"
