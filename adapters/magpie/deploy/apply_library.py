#!/usr/bin/env python3
"""Patch Magpie library.json on the vault host: MCP + hooks + hinddian-hooks skill (WebDAV-carried).

Hooks themselves are NOT in Magpie WebDAV Bundle — the skill is, so other PCs
pull the skill then run install.py once to populate Hooks UI.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

LIB = Path(os.environ.get("MAGPIE_LIBRARY") or (Path.home() / ".config/magpie/library.json"))
MCP_URL = (os.environ.get("HINDDIAN_MCP_URL") or (
    (os.environ.get("HINDDIAN_MEMORY_URL") or "").rstrip("/") + "/mcp" if os.environ.get("HINDDIAN_MEMORY_URL") else ""
)).strip()
if not MCP_URL:
    raise SystemExit("set HINDDIAN_MCP_URL (or HINDDIAN_MEMORY_URL), e.g. https://<host>:8444/hinddian/mcp")
def _skill_src() -> Path:
    """Skill pack next to this adapter (adapters/magpie/skills), else the repo-root mirror."""
    candidates = [
        HERE.parent / "skills" / "hinddian-hooks",
        HERE.parents[2] / "skills" / "hinddian-hooks",
    ]
    for c in candidates:
        if (c / "SKILL.md").is_file():
            return c
    return candidates[0]

SKILL_SRC = _skill_src()
SKILL_NAME = "hinddian-hooks"
sys.path.insert(0, str(SKILL_SRC))  # embed_hooks ships with the skill pack
from embed_hooks import hook_defs, hooks_version  # noqa: E402


def install_skill(magpie_cfg: Path) -> dict:
    skills_root = magpie_cfg / "library" / "skills" / SKILL_NAME
    skills_root.parent.mkdir(parents=True, exist_ok=True)
    if skills_root.exists():
        shutil.rmtree(skills_root)
    shutil.copytree(SKILL_SRC, skills_root)
    return {"skill_dir": str(skills_root), "files": sorted(p.name for p in skills_root.iterdir())}


def main():
    if not LIB.exists():
        raise SystemExit(f"missing {LIB}")
    if not SKILL_SRC.is_dir():
        raise SystemExit(f"missing skill pack {SKILL_SRC}")
    magpie_cfg = LIB.parent
    skill_info = install_skill(magpie_cfg)
    bak = LIB.with_suffix(LIB.suffix + f".bak.{int(time.time())}")
    shutil.copy2(LIB, bak)
    data = json.loads(LIB.read_text())
    bearer = None
    for m in data.get("mcp") or []:
        h = (m.get("headers") or {}).get("Authorization") or ""
        if h.lower().startswith("bearer "):
            bearer = h.split(" ", 1)[1].strip()
            break
    new_mcp = [m for m in (data.get("mcp") or []) if m.get("name") not in ("hindsight", "hinddian-memory")]
    entry = {
        "name": "hinddian-memory",
        "transport": "http",
        "url": MCP_URL,
        "agents": ["claude", "codex", "grok", "pi", "cursor", "gemini"],
    }
    if bearer:
        entry["headers"] = {"Authorization": f"Bearer {bearer}"}
    new_mcp.insert(0, entry)
    data["mcp"] = new_mcp

    hooks = hook_defs()
    names = {h["name"] for h in hooks}
    data["hooks"] = [h for h in (data.get("hooks") or []) if h.get("name") not in names] + hooks

    skills = [s for s in (data.get("skills") or []) if s.get("name") != SKILL_NAME]
    # No absolute Source.Dir — skill lives in library/skills/hinddian-hooks and
    # WebDAV carries its files; Windows Put writes them without linking to the vault host paths.
    skills.append({
        "name": SKILL_NAME,
        "agents": ["claude", "codex", "grok", "cursor", "gemini"],
    })
    data["skills"] = skills

    # Patch instructions with one-time Windows note (keep existing text, append marker block)
    # Instructions live in library/instructions.md — update that file if present
    instr = magpie_cfg / "library" / "instructions.md"
    marker = "<!-- hinddian-hooks-install -->"
    note = (
        f"\n{marker}\n"
        "## hinddian Magpie adapter install (other computers)\n\n"
        "Magpie WebDAV **does not sync Hooks**. After `magpie webdav now`, run the skill installer once "
        "(writes Hooks + ensures MCP `hinddian-memory`):\n\n"
        "- Windows: `& $env:USERPROFILE\\.config\\magpie\\library\\skills\\hinddian-hooks\\install.ps1`\n"
        "- Linux/macOS: `python3 ~/.config/magpie/library/skills/hinddian-hooks/install.py`\n\n"
        "Hooks panel: `hinddian-session-start` + `hinddian-turn-end`. "
        "Memory writes are **session drafts** (Jev local→cloud only; fail → no write). hinddian core is host-agnostic; this is the optional Magpie adapter.\n"
        f"{marker}\n"
    )
    if instr.is_file():
        text = instr.read_text(encoding="utf-8")
        if marker in text:
            pre, _, rest = text.partition(marker)
            _, _, rest2 = rest.partition(marker)
            # drop old block between markers
            text = pre.rstrip() + note + rest2.lstrip("\n")
        else:
            text = text.rstrip() + note
        instr.write_text(text, encoding="utf-8")

    LIB.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "ok": True,
        "backup": str(bak),
        "hooks": [h["name"] for h in data["hooks"]],
        "cmd_lens": {h["name"]: len(h["command"]) for h in data["hooks"]},
        "skill": skill_info,
        "ver": hooks_version(),
        "webdav_carries_hooks": False,
        "webdav_carries_skill": True,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
