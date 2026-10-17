#!/usr/bin/env python3
"""Patch Magpie library.json: hinddian-memory MCP + self-contained embedded hooks.

Hook *definitions* (including full script payloads) sync via Magpie WebDAV LWW.
No /usr/local/lib and no HTTP bootstrap on other machines — `magpie webdav now`
alone is enough after DMIT pushes.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from embed_hooks import shell_command  # noqa: E402

LIB = Path(
    os.environ.get("MAGPIE_LIBRARY")
    or (Path.home() / ".config/magpie/library.json")
)
MCP_URL = os.environ.get("HINDDIAN_MCP_URL", "http://124.70.90.224/hinddian/mcp")
MEMORY_URL = os.environ.get("HINDDIAN_MEMORY_URL", "http://124.70.90.224/hinddian")


def main():
    if not LIB.exists():
        raise SystemExit(f"missing {LIB}")
    bak = LIB.with_suffix(LIB.suffix + f".bak.{int(time.time())}")
    shutil.copy2(LIB, bak)
    data = json.loads(LIB.read_text())
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

    ss = shell_command("session_start", memory_url=MEMORY_URL)
    te = shell_command("turn_end", memory_url=MEMORY_URL)
    hooks = [
        h
        for h in (data.get("hooks") or [])
        if h.get("name")
        not in (
            "hindsight-recall-remind",
            "hinddian-session-start",
            "hinddian-turn-end",
        )
    ]
    hooks.append(
        {
            "name": "hinddian-session-start",
            "description": (
                "SessionStart: routing + Magpie-local Jev should-recall; "
                "scripts embedded in command (WebDAV syncs them)"
            ),
            "event": "session-start",
            "command": ss,
            "agents": ["claude", "codex", "grok", "pi"],
            "timeout": 45,
        }
    )
    hooks.append(
        {
            "name": "hinddian-turn-end",
            "description": (
                "TurnEnd: Magpie-local Jev classify → push_draft; "
                "scripts embedded in command (WebDAV syncs them)"
            ),
            "event": "turn-end",
            "command": te,
            "agents": ["claude", "codex", "grok", "pi"],
            "timeout": 90,
        }
    )
    data["hooks"] = hooks
    LIB.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "ok": True,
                "backup": str(bak),
                "library": str(LIB),
                "mcp": [m.get("name") for m in data["mcp"]],
                "hooks": [h.get("name") for h in data["hooks"]],
                "cmd_lens": {
                    "session_start": len(ss),
                    "turn_end": len(te),
                },
                "embedded": True,
                "extract_dir": "~/.config/magpie/hinddian-hooks",
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
