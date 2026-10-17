#!/usr/bin/env python3
"""Write hinddian hooks into *this computer's* Magpie library.json, then remind to sync.

Why: Magpie WebDAV/backup intentionally does NOT carry hooks yet
(https://github.com/yetone/magpie — library.Bundle has no Hooks field).
MCP/skills/instructions sync; hooks stay empty on other PCs until this runs once.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def magpie_dirs() -> list[Path]:
    home = Path.home()
    out: list[Path] = []
    # Magpie installed mode (all OS): ~/.config/magpie  or $XDG_CONFIG_HOME/magpie
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        out.append(Path(xdg) / "magpie")
    out.append(home / ".config" / "magpie")
    # Windows extras often checked by users
    appdata = os.environ.get("APPDATA")
    local = os.environ.get("LOCALAPPDATA")
    if appdata:
        out.append(Path(appdata) / "magpie")
    if local:
        out.append(Path(local) / "magpie")
    # Portable: data/ beside magpie.exe (env hint)
    for env in ("MAGPIE_DATA", "MAGPIE_HOME"):
        v = os.environ.get(env)
        if v:
            out.append(Path(v))
    # de-dupe
    seen = set()
    uniq = []
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
    # Prefer sibling embed_hooks.py (skill or deploy/magpie)
    sys.path.insert(0, str(HERE))
    # scripts may sit beside install or in parent
    for cand in (HERE, HERE.parent):
        if (cand / "embed_hooks.py").is_file() and (cand / "jev.py").is_file():
            sys.path.insert(0, str(cand))
            break
    import embed_hooks  # type: ignore
    return embed_hooks


def main() -> int:
    lib_path = find_library()
    emb = load_embed()
    hooks = emb.hook_defs(src_dir=Path(emb.__file__).resolve().parent)
    bak = lib_path.with_suffix(lib_path.suffix + f".bak.{int(time.time())}")
    shutil.copy2(lib_path, bak)
    data = json.loads(lib_path.read_text(encoding="utf-8"))
    names = {h["name"] for h in hooks}
    kept = [h for h in (data.get("hooks") or []) if h.get("name") not in names]
    data["hooks"] = kept + hooks
    lib_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "library": str(lib_path),
        "backup": str(bak),
        "hooks": [h["name"] for h in data["hooks"]],
        "python": emb.python_bin(),
        "ver": emb.hooks_version(),
    }, ensure_ascii=False, indent=2))
    print()
    print("Next: open Magpie → Library → Hooks — you should see hinddian-session-start / hinddian-turn-end.")
    print("Then run:  magpie library sync")
    print("(WebDAV still will NOT push hooks to other PCs — run this install on each PC once.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
