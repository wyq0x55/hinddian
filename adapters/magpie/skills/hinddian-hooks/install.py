#!/usr/bin/env python3
"""Install the hinddian capture hooks on this Magpie host.

WebDAV does NOT sync Hooks (upstream). After pulling the skill via WebDAV
(or GitHub skill install), run this once on each computer.

"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
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


def main() -> int:
    lib_path = find_library()
    emb = load_embed()
    # Prefer scripts shipped inside this skill folder
    src_dir = HERE if (HERE / "jev.py").is_file() else Path(emb.__file__).resolve().parent
    hooks = emb.hook_defs(src_dir=src_dir)
    bak = lib_path.with_suffix(lib_path.suffix + f".bak.{int(time.time())}")
    shutil.copy2(lib_path, bak)
    data = json.loads(lib_path.read_text(encoding="utf-8"))
    if isinstance(data.get("mcp"), list):
        data["mcp"] = [entry for entry in data["mcp"] if entry.get("name") != "hinddian-memory"]
    kept = [h for h in (data.get("hooks") or []) if h.get("name") not in HOOK_NAMES]
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
