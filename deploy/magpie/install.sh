#!/usr/bin/env bash
# One-shot: install hinddian Magpie hook scripts on this computer.
# Does NOT need Magpie WebDAV — library hook entries still come from sync.
# Usage (Linux/macOS with python3):
#   curl -fsSL http://124.70.90.224/hinddian-static/install.sh | bash
set -euo pipefail
BASE="${HINDDIAN_HOOKS_BASE:-http://124.70.90.224/hinddian-static}"
DIR="${HINDDIAN_MAGPIE_HOOK_DIR:-}"
if [[ -z "$DIR" ]]; then
  if mkdir -p /usr/local/lib/hinddian-magpie 2>/dev/null && \
     touch /usr/local/lib/hinddian-magpie/.write_test 2>/dev/null; then
    rm -f /usr/local/lib/hinddian-magpie/.write_test
    DIR=/usr/local/lib/hinddian-magpie
  else
    DIR="${HOME}/.local/lib/hinddian-magpie"
    mkdir -p "$DIR"
  fi
fi
export HINDDIAN_MAGPIE_HOOK_DIR="$DIR"
mkdir -p "$DIR"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
curl -fsSL "$BASE/magpie-hooks.tgz" -o "$TMP/hooks.tgz"
curl -fsSL "$BASE/HOOKS_VERSION" -o "$TMP/HOOKS_VERSION" || echo "0" >"$TMP/HOOKS_VERSION"
tar -xzf "$TMP/hooks.tgz" -C "$TMP"
# flatten
find "$TMP" -maxdepth 2 -type f \( -name '*.py' -o -name '*.sh' -o -name 'HOOKS_VERSION' \) -print0 | while IFS= read -r -d '' f; do
  cp -f "$f" "$DIR/"
done
chmod +x "$DIR"/*.py "$DIR"/*.sh 2>/dev/null || true
cp -f "$TMP/HOOKS_VERSION" "$DIR/HOOKS_VERSION"
cp -f "$TMP/HOOKS_VERSION" "$DIR/.version"
echo "installed hinddian-magpie hooks → $DIR ver=$(tr -d '[:space:]' <"$DIR/.version")"
# Optional: patch local library if present (same machine as Magpie config)
if [[ -f "${MAGPIE_LIBRARY:-$HOME/.config/magpie/library.json}" ]]; then
  if [[ -f "$DIR/apply_library.py" ]]; then
    python3 "$DIR/apply_library.py" || true
  fi
fi
echo "Next: Magpie WebDAV pull (or wait ~3m) so library hook entries match DMIT; then open a new session."
