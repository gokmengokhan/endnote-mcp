#!/usr/bin/env bash
# Build the endnote-mcp Claude Desktop Extension (.dxt).
#
# This produces a single cross-platform .dxt file that Claude Desktop can
# install. Dependencies are resolved at install time by uv (bundled with
# Claude Desktop), so no per-platform builds are needed.
#
# Output:  dist/endnote-mcp.dxt
set -euo pipefail

cd "$(dirname "$0")/.."

DXT_DIR="dxt"
DIST_DIR="dist"
OUTPUT="$DIST_DIR/endnote-mcp.dxt"

if [ ! -f "$DXT_DIR/manifest.json" ]; then
  echo "error: $DXT_DIR/manifest.json missing — run from repo root" >&2
  exit 1
fi

# Sync the package source from src/endnote_mcp/ into dxt/src/endnote_mcp/.
# We re-copy on every build so the DXT always reflects the latest source.
echo "Syncing endnote_mcp package source..."
rm -rf "$DXT_DIR/src/endnote_mcp"
mkdir -p "$DXT_DIR/src"
cp -R "src/endnote_mcp" "$DXT_DIR/src/endnote_mcp"

# Strip caches from the synced copy.
find "$DXT_DIR/src/endnote_mcp" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
find "$DXT_DIR/src/endnote_mcp" -name "*.pyc" -delete 2>/dev/null || true

# Pack into a .dxt zip.
mkdir -p "$DIST_DIR"
rm -f "$OUTPUT"

(
  cd "$DXT_DIR"
  zip -rq "../$OUTPUT" . \
    -x "*.pyc" \
    -x "**/__pycache__/*" \
    -x ".venv/*" \
    -x "*.egg-info/*" \
    -x ".DS_Store"
)

SIZE=$(du -h "$OUTPUT" | cut -f1)
echo
echo "Built $OUTPUT ($SIZE)"
echo
echo "Install instructions:"
echo "  Double-click the .dxt file, or"
echo "  Claude Desktop → Settings → Extensions → Install Extension..."
