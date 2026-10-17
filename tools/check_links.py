"""Verify every [[wikilink]] in a vault resolves (full path or unique basename). Exit 1 on broken links."""
import re, sys, pathlib
root = pathlib.Path(sys.argv[1])
files = [p for p in root.rglob("*.md") if ".obsidian" not in p.parts]
paths = {str(p.relative_to(root))[:-3] for p in files}
names = {}
for p in paths: names.setdefault(pathlib.Path(p).name, []).append(p)
bad, total = [], 0
for f in files:
    if "_归档" in f.parts: continue
    for m in re.findall(r"\[\[([^\]|#]+)", f.read_text()):
        total += 1
        t = m.strip()
        if t not in paths and len(names.get(t, [])) != 1:
            bad.append((str(f.relative_to(root)), t))
print(f"{total} links checked, {len(bad)} broken")
for b in bad: print("  BROKEN", *b)
sys.exit(1 if bad else 0)
