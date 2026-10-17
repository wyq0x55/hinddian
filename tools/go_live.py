"""Replace live vault content with staging (minimal churn: overwrite changed, delete missing). Keeps .git/.obsidian.
Moves *.bak* files and _trash dirs out of the vault into BAK first. usage: go_live.py <staging> <live> <bakdir>"""
import sys, os, shutil, pathlib, hashlib
S, L, B = map(pathlib.Path, sys.argv[1:4])
KEEP = {".git", ".obsidian", ".trash", ".gitignore"}
B.mkdir(parents=True, exist_ok=True)
moved = 0
for p in list(L.rglob("*")):
    if any(x in KEEP for x in p.relative_to(L).parts): continue
    if p.exists() and (".bak" in p.name or p.name == "_trash"):
        dest = B / p.relative_to(L); dest.parent.mkdir(parents=True, exist_ok=True); shutil.move(str(p), dest); moved += 1
h = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
want = {p.relative_to(S) for p in S.rglob("*") if p.is_file() and not any(x in KEEP for x in p.relative_to(S).parts)}
wrote = 0
for rel in sorted(want):
    src, dst = S / rel, L / rel
    if dst.exists() and h(src) == h(dst): continue
    dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(src, dst); wrote += 1
deleted = 0
for p in sorted(L.rglob("*"), reverse=True):
    rel = p.relative_to(L)
    if any(x in KEEP for x in rel.parts): continue
    if p.is_file() and rel not in want: p.unlink(); deleted += 1
    elif p.is_dir() and not any(p.iterdir()): p.rmdir()
for p in [L, *L.rglob("*")]:
    if ".git" in p.relative_to(L).parts: continue
    shutil.chown(p, "obsidian", "obsidian")
print(f"bak moved {moved}, wrote {wrote}, deleted {deleted}")
