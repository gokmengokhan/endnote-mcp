#!/usr/bin/env bash
# Build the endnote-mcp MCP bundle (.mcpb).
#
# Produces a single cross-platform .mcpb file that Claude Desktop and other
# MCP host apps can install by double-click. Dependencies are resolved at
# install time by uv (bundled with the host), so no per-platform builds.
#
# The format was previously called DXT and used the .dxt extension; it was
# renamed to MCPB (MCP Bundles) upstream. See modelcontextprotocol/mcpb.
#
# Output:  dist/endnote-mcp.mcpb
set -euo pipefail

cd "$(dirname "$0")/.."

BUNDLE_DIR="mcpb"
DIST_DIR="dist"
OUTPUT="$DIST_DIR/endnote-mcp.mcpb"
IGNORE_FILE="$BUNDLE_DIR/.mcpbignore"

if [ ! -f "$BUNDLE_DIR/manifest.json" ]; then
  echo "error: $BUNDLE_DIR/manifest.json missing — run from repo root" >&2
  exit 1
fi

# The manifest version must track the package, or the bundle reports a version
# the code inside it does not match.
python3 scripts/check_version.py

# Sync the package source from src/endnote_mcp/ into mcpb/src/endnote_mcp/.
# Re-copied on every build so the bundle always reflects the latest source.
echo "Syncing endnote_mcp package source..."
rm -rf "$BUNDLE_DIR/src/endnote_mcp"
mkdir -p "$BUNDLE_DIR/src"
cp -R "src/endnote_mcp" "$BUNDLE_DIR/src/endnote_mcp"

# Strip caches from the synced copy.
find "$BUNDLE_DIR/src/endnote_mcp" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
find "$BUNDLE_DIR/src/endnote_mcp" -name "*.pyc" -delete 2>/dev/null || true

# Translate .mcpbignore into zip exclude patterns, so the ignore file is the
# single source of truth rather than decoration next to a hardcoded list.
EXCLUDES=()
while IFS= read -r pattern || [ -n "$pattern" ]; do
  pattern="${pattern%%#*}"                     # strip comments
  pattern="$(echo "$pattern" | xargs || true)" # trim whitespace
  [ -z "$pattern" ] && continue
  if [[ "$pattern" == */ ]]; then
    EXCLUDES+=("-x" "${pattern}*" "-x" "*/${pattern}*")
  else
    EXCLUDES+=("-x" "$pattern" "-x" "*/$pattern")
  fi
done < "$IGNORE_FILE"

echo "Excluding ${#EXCLUDES[@]} pattern(s) from $IGNORE_FILE"

mkdir -p "$DIST_DIR"
rm -f "$OUTPUT"

(
  cd "$BUNDLE_DIR"
  zip -rq "../$OUTPUT" . "${EXCLUDES[@]}"
)

SIZE=$(du -h "$OUTPUT" | cut -f1)
echo
echo "Built $OUTPUT ($SIZE)"
echo
echo "Install instructions:"
echo "  Double-click the .mcpb file, or"
echo "  Claude Desktop → Settings → Extensions → Install Extension..."
