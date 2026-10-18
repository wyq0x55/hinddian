#!/usr/bin/env python3
"""One-step local install: Magpie Hooks + hinddian-memory MCP.

WebDAV does NOT sync Hooks (upstream). After pulling the skill via WebDAV
(or GitHub skill install), run this once on each computer.

DMIT remains library SoT via apply_library.py — do NOT run apply_library here.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
MCP_URL = os.environ.get("HINDDIAN_MCP_URL", "http://124.70.90.224/hinddian/mcp")
MCP_NAME = "hinddian-memory"
HOOK_NAMES = {"hinddian-session-start", "hinddian-turn-end"}


def magpie_dirs() -> list[Path]:
    home = Path.home()
    out: list[Path] = []
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        out.append(Path(xdg) / "magpie")
    out.append(home / ".config" / "magpie")
    appdata = os.environ.get("APPDATA")
    local = os.environ.get("LOCALAPPDATA")
    if appdata:
        out.append(Path(appdata) / "magpie")
    if local:
        out.append(Path(local) / "magpie")
    for env in ("MAGPIE_DATA", "MAGPIE_HOME"):
        v = os.environ.get(env)
        if v:
            out.append(Path(v))
    seen, uniq = set(), []
    for p in out:
        r = str(p)
        if r not in seen:
            seen.add(r)
            uniq.append(p)
    return uniq


def find_library() -> Path:
    env = os.environ.get("MAGPIE_LIBRARY")
    if env and Path(env).is_file():
        return Path(env)
    for d in magpie_dirs():
        p = d / "library.json"
        if p.is_file():
            return p
    raise SystemExit(
        "Magpie library.json not found. Checked:\n  "
        + "\n  ".join(str(d / "library.json") for d in magpie_dirs())
        + "\nOpen Magpie once, or set MAGPIE_LIBRARY=...\\library.json"
    )


def load_embed():
    sys.path.insert(0, str(HERE))
    for cand in (HERE, HERE.parent):
        if (cand / "embed_hooks.py").is_file() and (cand / "jev.py").is_file():
            sys.path.insert(0, str(cand))
            break
    import embed_hooks  # type: ignore

    return embed_hooks


def ensure_mcp(data: dict) -> dict:
    bearer = None
    for m in data.get("mcp") or []:
        h = (m.get("headers") or {}).get("Authorization") or ""
        if h.lower().startswith("bearer "):
            bearer = h.split(" ", 1)[1].strip()
            break
    env_tok = (os.environ.get("HINDDIAN_MCP_TOKEN") or os.environ.get("HINDSIGHT_API_KEY") or "").strip()
    if env_tok:
        bearer = env_tok
    agents = ["claude", "codex", "grok", "pi", "cursor", "gemini"]
    new_mcp = [m for m in (data.get("mcp") or []) if m.get("name") not in ("hindsight", MCP_NAME)]
    entry = {
        "name": MCP_NAME,
        "transport": "http",
        "url": MCP_URL,
        "agents": agents,
    }
    if bearer:
        entry["headers"] = {"Authorization": f"Bearer {bearer}"}
    new_mcp.insert(0, entry)
    data["mcp"] = new_mcp
    return {"mcp": MCP_NAME, "url": MCP_URL, "bearer": bool(bearer)}


def main() -> int:
    lib_path = find_library()
    emb = load_embed()
    # Prefer scripts shipped inside this skill folder
    src_dir = HERE if (HERE / "jev.py").is_file() else Path(emb.__file__).resolve().parent
    hooks = emb.hook_defs(src_dir=src_dir)
    bak = lib_path.with_suffix(lib_path.suffix + f".bak.{int(time.time())}")
    shutil.copy2(lib_path, bak)
    data = json.loads(lib_path.read_text(encoding="utf-8"))
    mcp_info = ensure_mcp(data)
    names = {h["name"] for h in hooks}
    kept = [h for h in (data.get("hooks") or []) if h.get("name") not in names]
    data["hooks"] = kept + hooks
    # ensure skill listed (no absolute path)
    skills = [s for s in (data.get("skills") or []) if s.get("name") != "hinddian-hooks"]
    skills.append({"name": "hinddian-hooks", "agents": ["claude", "codex", "grok", "cursor", "gemini"]})
    data["skills"] = skills
    lib_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    hook_names = [h["name"] for h in data["hooks"] if h.get("name") in HOOK_NAMES]
    print(
        json.dumps(
            {
                "ok": True,
                "library": str(lib_path),
                "backup": str(bak),
                "hooks": hook_names,
                "all_hooks": [h.get("name") for h in data["hooks"]],
                "mcp": mcp_info,
                "python": emb.python_bin(),
                "ver": emb.hooks_version(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print()
    print("Next: Magpie → Library → Hooks should list hinddian-session-start / hinddian-turn-end.")
    print("Then: magpie library sync")
    print("Do not run apply_library.py on this PC (DMIT is SoT).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
