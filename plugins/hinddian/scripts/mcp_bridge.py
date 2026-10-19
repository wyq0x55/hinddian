"""stdio MCP server that forwards to the hinddian-memory HTTP endpoint (stdlib only).

Hosts launch it as a local command (`python3 scripts/mcp_bridge.py`), so the plugin needs no
URL in its MCP config — the URL and token come from hookcfg (env / plugin options /
~/.config/hinddian/config.json), the same place the hooks read. Before setup it still starts
and answers, telling the agent which command the user should run.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hookcfg  # noqa: E402

SETUP = hookcfg.HERE / "setup.py"


def _hint() -> str:
    why = hookcfg.transport_problem() or "server unreachable"
    return f"hinddian-memory is not ready: {why}. Ask the user to run: python3 \"{SETUP}\""


def _local(msg: dict) -> dict | None:
    """Answers while unconfigured/unreachable, so the host doesn't mark the server broken."""
    mid, method = msg.get("id"), msg.get("method")
    if mid is None:
        return None
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "hinddian-memory", "version": "bridge"},
            "instructions": _hint(),
        }}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": []}}
    if method == "tools/call":
        return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": _hint()}], "isError": True}}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": _hint()}}


def _forward(raw: bytes) -> bytes | None:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if hookcfg.token():
        headers["Authorization"] = f"Bearer {hookcfg.token()}"
    r = urllib.request.Request(hookcfg.memory_url() + "/mcp", data=raw, headers=headers, method="POST")
    with urllib.request.urlopen(r, timeout=120, context=hookcfg._ssl_context()) as resp:
        body = resp.read()
    return body if body.strip() else None


def handle(line: str) -> str | None:
    try:
        msg = json.loads(line)
    except ValueError:
        return json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
    if hookcfg.transport_problem() is None:
        try:
            out = _forward(line.encode())
            return out.decode() if out else None
        except urllib.error.HTTPError as e:
            reason = f"HTTP {e.code} from server" + (" (check token: run setup.py --check)" if e.code in (401, 403) else "")
        except Exception as e:  # noqa: BLE001 — any network failure degrades to a local answer
            reason = f"{type(e).__name__}: {e}"
        sys.stderr.write(f"hinddian bridge: {reason}\n")
    msgs = msg if isinstance(msg, list) else [msg]
    out = [r for r in (_local(m) for m in msgs if isinstance(m, dict)) if r]
    if not out:
        return None
    return json.dumps(out if isinstance(msg, list) else out[0], ensure_ascii=False)


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        out = handle(line)
        if out:
            sys.stdout.write(out.replace("\n", " ") + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
