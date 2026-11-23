"""Regenerate .obsidian/graph.json color groups from vault dirs.
usage: graph_colors.py [vault]
Colors: fixed palette, hashed by path so a project keeps the same colour across regenerations.
"""
import hashlib, json, os, pathlib, shutil, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from hinddian import note_format, paths
# Distinct, readable-on-dark palette (no near-greys). Order is preference for first N projects by name.
PALETTE = [0x3399FF, 0x66CC66, 0xFF9933, 0xCC66FF, 0xFF6688, 0x33CCCC, 0xFFCC33, 0x6688FF, 0x99CC33, 0xFF66CC]
SYS = 0xAAAAAA; TIPS = 0xFFAA00; ARCH = 0x666666

def color_for(path: str, used: set) -> int:
    """Prefer a free palette slot hashed from path; if taken, walk to the next free one."""
    h = int(hashlib.sha1(path.encode()).hexdigest()[:8], 16)
    for i in range(len(PALETTE)):
        c = PALETTE[(h + i) % len(PALETTE)]
        if c not in used:
            used.add(c); return c
    return PALETTE[h % len(PALETTE)]

def groups(vault):
    used, out = set(), [{"query": "path:技巧", "color": {"a": 1, "rgb": TIPS}},
                        {"query": "path:00-系统", "color": {"a": 1, "rgb": SYS}}]
    used |= {TIPS, SYS, ARCH}
    pdir = vault / "项目"
    if pdir.exists():
        for d in sorted(pdir.iterdir()):
            if d.is_dir() and not d.is_symlink() and not d.name.startswith(("_", ".")):
                q = f"path:项目/{d.name}"
                out.append({"query": q, "color": {"a": 1, "rgb": color_for(q, used)}})
    out.append({"query": "path:_归档", "color": {"a": 1, "rgb": ARCH}})
    return out

def main(vault=None):
    vault = vault or paths.vault_dir()
    colors = groups(vault)
    cfg = {"showTags": True, "showOrphans": True, "showArrow": True,
           "colorGroups": colors, "search": "-path:_归档"}
    odir = vault / ".obsidian"
    path = odir / "graph.json"
    if not path.resolve().is_relative_to(vault.resolve()):
        raise note_format.UnsafePath("graph settings escape the vault")
    # Preserve other keys Obsidian may have written.
    if path.exists():
        try:
            old = json.loads(path.read_text()); old.update(cfg); cfg = old
        except Exception: pass
    note_format.write_atomic(path, json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
    if owner := os.environ.get("HC_OWNER"):
        try:
            shutil.chown(path, owner, owner)
            shutil.chown(odir, owner, owner)
        except OSError:
            pass
    return [{"query": group["query"], "rgb": f"#{group['color']['rgb']:06x}"} for group in colors]

if __name__ == "__main__":
    vault = pathlib.Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else None
    print(json.dumps(main(vault), ensure_ascii=False, indent=1))
