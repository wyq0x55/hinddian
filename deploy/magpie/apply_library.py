#!/usr/bin/env python3
"""Patch Magpie library.json: swap raw Hindsight MCP → hinddian-memory; install hooks.
Preserves existing Authorization Bearer value in-place (never prints it).
Pull-first: Magpie sync should be pulled on other machines before this if conflict risk.
"""
from __future__ import annotations
import json, shutil, time
from pathlib import Path

LIB = Path("/root/.config/magpie/library.json")
HOOK_DIR = Path("/usr/local/lib/hinddian-magpie")
MCP_URL = "http://124.70.90.224/hinddian/mcp"
MEMORY_URL = "http://124.70.90.224/hinddian"

def main():
    if not LIB.exists():
        raise SystemExit(f"missing {LIB}")
    bak = LIB.with_suffix(LIB.suffix + f".bak.{int(time.time())}")
    shutil.copy2(LIB, bak)
    data = json.loads(LIB.read_text())
    # keep prior bearer if any
    bearer = None
    for m in data.get("mcp") or []:
        h = (m.get("headers") or {}).get("Authorization") or ""
        if h.lower().startswith("bearer "):
            bearer = h.split(" ", 1)[1].strip()
            break
    new_mcp = []
    for m in data.get("mcp") or []:
        if m.get("name") in ("hindsight", "hinddian-memory"):
            continue
        new_mcp.append(m)
    entry = {
        "name": "hinddian-memory",
        "transport": "http",
        "url": MCP_URL,
        "agents": ["claude", "codex", "grok", "pi"],
    }
    if bearer:
        entry["headers"] = {"Authorization": f"Bearer {bearer}"}
    new_mcp.insert(0, entry)
    data["mcp"] = new_mcp

    hooks = [h for h in (data.get("hooks") or []) if h.get("name") not in (
        "hindsight-recall-remind", "hinddian-session-start", "hinddian-turn-end"
    )]
    hooks.append({
        "name": "hinddian-session-start",
        "description": "SessionStart: inject routing tables + Jev should-recall gate via hinddian-memory",
        "event": "session-start",
        "command": f"HINDDIAN_MEMORY_URL={MEMORY_URL} HINDDIAN_MCP_TOKEN=${{HINDDIAN_MCP_TOKEN:-${{HINDSIGHT_API_KEY:-}}}} python3 {HOOK_DIR}/session_start.py",
        "agents": ["claude", "codex", "grok", "pi"],
        "timeout": 25,
    })
    hooks.append({
        "name": "hinddian-turn-end",
        "description": "TurnEnd: Jev/LLM classify this turn only → push_draft (no full-session write)",
        "event": "turn-end",
        "command": f"HINDDIAN_MEMORY_URL={MEMORY_URL} HINDDIAN_MCP_TOKEN=${{HINDDIAN_MCP_TOKEN:-${{HINDSIGHT_API_KEY:-}}}} python3 {HOOK_DIR}/turn_end.py",
        "agents": ["claude", "codex", "grok", "pi"],
        "timeout": 60,
    })
    data["hooks"] = hooks
    LIB.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"ok": True, "backup": str(bak), "mcp": [m.get("name") for m in data["mcp"]], "hooks": [h.get("name") for h in data["hooks"]]}))

if __name__ == "__main__":
    main()
