#!/usr/bin/env bash
set -euo pipefail
ROOT="${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-}}"
if [[ -z "$ROOT" ]]; then
  ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fi
export HINDDIAN_MEMORY_URL="${HINDDIAN_MEMORY_URL:-http://124.70.90.224/hinddian}"
export PYTHONPATH="$ROOT/scripts${PYTHONPATH:+:$PYTHONPATH}"
# Prefer py -3 on Windows Git Bash / py launcher if present
if command -v py >/dev/null 2>&1; then
  exec py -3 "$ROOT/scripts/session_start.py"
elif command -v python3 >/dev/null 2>&1; then
  exec python3 "$ROOT/scripts/session_start.py"
else
  exec python "$ROOT/scripts/session_start.py"
fi
