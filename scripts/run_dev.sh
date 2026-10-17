#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"
HOST="${HINDDIAN_HOST:-127.0.0.1}"
PORT="${HINDDIAN_PORT:-8787}"
mkdir -p data
exec python3 -m uvicorn hinddian.api:app --host "$HOST" --port "$PORT" --reload
