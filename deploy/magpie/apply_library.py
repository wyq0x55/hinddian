#!/usr/bin/env python3
"""Patch Magpie library.json: hinddian-memory MCP + self-healing hooks.

Hook *definitions* sync via Magpie WebDAV (whole-file LWW). Hook *scripts*
do NOT — they live under /usr/local/lib/hinddian-magpie (or ~/.local/…).
Library commands therefore exec a remote bootstrap.py that installs/updates
the tarball from http://<huawei>/hinddian-static/ on first run / version bump.

Also copies sibling scripts into HOOK_DIR when this file is run from a checkout
or from HOOK_DIR itself (DMIT apply path).
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIB = Path(
    os.environ.get("MAGPIE_LIBRARY")
    or (Path.home() / ".config/magpie/library.json")
)
HOOK_DIR = Path(
    os.environ.get("HINDDIAN_MAGPIE_HOOK_DIR")
    or "/usr/local/lib/hinddian-magpie"
)
MCP_URL = os.environ.get("HINDDIAN_MCP_URL", "http://124.70.90.224/hinddian/mcp")
MEMORY_URL = os.environ.get("HINDDIAN_MEMORY_URL", "http://124.70.90.224/hinddian")
STATIC = os.environ.get(
    "HINDDIAN_HOOKS_BASE", "http://124.70.90.224/hinddian-static"
).rstrip("/")

SCRIPT_NAMES = (
    "bootstrap.py",
    "session_start.py",
    "turn_end.py",
    "jev.py",
    "apply_library.py",
    "disable_otel.py",
    "session-start.sh",
    "turn-end.sh",
    "HOOKS_VERSION",
)


def install_local_scripts() -> dict:
    """Copy deploy/magpie scripts into HOOK_DIR when present beside this file."""
    HOOK_DIR.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in SCRIPT_NAMES:
        src = HERE / name
        if not src.is_file():
            continue
        dst = HOOK_DIR / name
        if src.resolve() == dst.resolve():
            copied.append(name + " (already in place)")
            continue
        shutil.copy2(src, dst)
        if name.endswith((".py", ".sh")):
            dst.chmod(0o755)
        copied.append(name)
    ver_src = HERE / "HOOKS_VERSION"
    if ver_src.is_file():
        (HOOK_DIR / ".version").write_text(ver_src.read_text().strip() + "\n")
    return {"hook_dir": str(HOOK_DIR), "copied": copied}


def bootstrap_command(which: str) -> str:
    """Shell command Magpie runs; self-heals scripts via public static URL."""
    # which: session_start | turn_end
    boot = (
        f"python3 -c \"import urllib.request as u; "
        f"exec(u.urlopen('{STATIC}/bootstrap.py', timeout=30).read().decode())\" {which}"
    )
    return (
        f"HINDDIAN_MEMORY_URL={MEMORY_URL} "
        f"HINDDIAN_MCP_TOKEN=${{HINDDIAN_MCP_TOKEN:-${{HINDSIGHT_API_KEY:-}}}} "
        f"{boot}"
    )


def main():
    if not LIB.exists():
        raise SystemExit(f"missing {LIB}")
    installed = install_local_scripts()
    bak = LIB.with_suffix(LIB.suffix + f".bak.{int(time.time())}")
    shutil.copy2(LIB, bak)
    data = json.loads(LIB.read_text())
    # keep prior bearer if any (never print it)
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
                "SessionStart: routing from hinddian; Magpie-local Jev should-recall; "
                "scripts auto-install from hinddian-static on first run"
            ),
            "event": "session-start",
            "command": bootstrap_command("session_start"),
            "agents": ["claude", "codex", "grok", "pi"],
            "timeout": 45,
        }
    )
    hooks.append(
        {
            "name": "hinddian-turn-end",
            "description": (
                "TurnEnd: Magpie-local Jev classify → push_draft; "
                "scripts auto-install from hinddian-static"
            ),
            "event": "turn-end",
            "command": bootstrap_command("turn_end"),
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
                "install": installed,
                "mcp": [m.get("name") for m in data["mcp"]],
                "hooks": [h.get("name") for h in data["hooks"]],
                "hooks_static": STATIC,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
