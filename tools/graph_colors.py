"""Regenerate .obsidian/graph.json color groups from vault dirs.
usage: graph_colors.py [vault]   # default HC_VAULT or /srv/obsidian/vault
Colors: fixed palette, hashed by path so a project keeps the same colour across regenerations.
"""
import hashlib, json, os, pathlib, sys
VAULT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("HC_VAULT", "/srv/obsidian/vault"))
OWNER = os.environ.get("HC_OWNER", "obsidian")
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

def groups():
    used, out = set(), [{"query": "path:技巧", "color": {"a": 1, "rgb": TIPS}},
                        {"query": "path:00-系统", "color": {"a": 1, "rgb": SYS}}]
    used |= {TIPS, SYS, ARCH}
    pdir = VAULT / "项目"
    if pdir.exists():
        for d in sorted(pdir.iterdir()):
            if d.is_dir() and not d.name.startswith(("_", ".")):
                q = f"path:项目/{d.name}"
                out.append({"query": q, "color": {"a": 1, "rgb": color_for(q, used)}})
    out.append({"query": "path:_归档", "color": {"a": 1, "rgb": ARCH}})
    return out

def main():
    cfg = {"showTags": True, "showOrphans": True, "showArrow": True,
           "colorGroups": groups(), "search": "-path:_归档"}
    odir = VAULT / ".obsidian"; odir.mkdir(parents=True, exist_ok=True)
    path = odir / "graph.json"
    # Preserve other keys Obsidian may have written.
    if path.exists():
        try:
            old = json.loads(path.read_text()); old.update(cfg); cfg = old
            cfg["colorGroups"] = groups(); cfg["search"] = "-path:_归档"
        except Exception: pass
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
    try:
        import shutil; shutil.chown(path, OWNER, OWNER); shutil.chown(odir, OWNER, OWNER)
    except Exception: pass
    print(json.dumps([{"query": g["query"], "rgb": f"#{g['color']['rgb']:06x}"} for g in cfg["colorGroups"]], ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()
