#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"
HOST="${HINDDIAN_HOST:-127.0.0.1}"
PORT="${HINDDIAN_PORT:-8787}"
env_file=()
if [[ -f .env ]]; then env_file=(--env-file .env); fi
# Local dev: allow requests without tokens when neither credential is set.
if [[ -z "${HINDDIAN_MCP_TOKEN:-}" && -z "${AUTH_TOKEN:-}" ]]; then export HINDDIAN_ALLOW_NO_AUTH="${HINDDIAN_ALLOW_NO_AUTH:-true}"; fi
exec python3 -m uvicorn hinddian.api:app --host "$HOST" --port "$PORT" --reload "${env_file[@]}"
