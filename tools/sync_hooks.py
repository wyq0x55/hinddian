#!/usr/bin/env python3
"""Generate every distributed copy of the host-hook scripts from their single source.

Sources (edit these):
  hooks/*.py                               hook runtime (stdlib only)
  src/hinddian/jev.py                      Jev gate (also imported by the server)
  adapters/magpie/skills/hinddian-hooks/   Magpie-only installer files (SKILL.md, install.*, embed_hooks.py)

Generated (never edit by hand):
  plugins/hinddian/scripts/                Claude Code / Codex plugin
  adapters/magpie/skills/hinddian-hooks/   Magpie skill pack (core scripts + HOOKS_VERSION)
  skills/hinddian-hooks/                   mirror probed by Magpie's GitHub skill discovery

usage: python tools/sync_hooks.py [--check]
--check exits 1 (and lists the files) when any copy is out of date — CI runs this.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = {
    "hookcfg.py": ROOT / "hooks/hookcfg.py",
    "extract.py": ROOT / "hooks/extract.py",
    "session_buf.py": ROOT / "hooks/session_buf.py",
    "finalize.py": ROOT / "hooks/finalize.py",
    "session_start.py": ROOT / "hooks/session_start.py",
    "turn_end.py": ROOT / "hooks/turn_end.py",
    "mcp_bridge.py": ROOT / "hooks/mcp_bridge.py",
    "setup.py": ROOT / "hooks/setup.py",
    "prompt_recall.py": ROOT / "hooks/prompt_recall.py",
    "jev.py": ROOT / "src/hinddian/jev.py",
}
MAGPIE_SKILL = ROOT / "adapters/magpie/skills/hinddian-hooks"
MAGPIE_EXTRA = ("SKILL.md", "embed_hooks.py", "install.py", "install.ps1")


def _lf(data: bytes) -> bytes:
    # Compare/hash as committed (LF), so a core.autocrlf=true checkout agrees with CI.
    return data.replace(b"\r\n", b"\n")


def hooks_version() -> str:
    h = hashlib.sha256()
    for name in sorted(CORE):
        h.update(name.encode() + b"\0" + _lf(CORE[name].read_bytes()))
    return "h-" + h.hexdigest()[:12]


def plan() -> dict[Path, bytes]:
    core = {name: src.read_bytes() for name, src in CORE.items()}
    ver = (hooks_version() + "\n").encode()
    out: dict[Path, bytes] = {}
    for name, data in core.items():
        out[ROOT / "plugins/hinddian/scripts" / name] = data
        out[MAGPIE_SKILL / name] = data
        out[ROOT / "skills/hinddian-hooks" / name] = data
    out[MAGPIE_SKILL / "HOOKS_VERSION"] = ver
    out[ROOT / "skills/hinddian-hooks/HOOKS_VERSION"] = ver
    for name in MAGPIE_EXTRA:
        out[ROOT / "skills/hinddian-hooks" / name] = (MAGPIE_SKILL / name).read_bytes()
    return out


def strays(want: dict[Path, bytes]) -> list[Path]:
    """Files in a generated dir that no source produces (left over from a rename)."""
    keep = set(want) | {MAGPIE_SKILL / n for n in MAGPIE_EXTRA}
    dirs = {p.parent for p in want}
    return sorted(p for d in dirs for p in d.iterdir() if p.is_file() and p not in keep and p.suffix in (".py", ".ps1", ""))


def main(argv: list[str]) -> int:
    check = "--check" in argv
    want = plan()
    stale = [p for p, data in want.items() if not p.is_file() or _lf(p.read_bytes()) != _lf(data)]
    extra = strays(want)
    if check:
        for p in stale:
            print(f"out of date: {p.relative_to(ROOT)}")
        for p in extra:
            print(f"stray file:  {p.relative_to(ROOT)}")
        if stale or extra:
            print("run: python tools/sync_hooks.py", file=sys.stderr)
            return 1
        return 0
    for p in stale:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(want[p])
        print(f"wrote {p.relative_to(ROOT)}")
    for p in extra:
        p.unlink()
        print(f"removed {p.relative_to(ROOT)}")
    print(f"HOOKS_VERSION {hooks_version()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
