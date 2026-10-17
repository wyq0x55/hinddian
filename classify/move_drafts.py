"""Move all 项目/*/待入库/*.md drafts out of the vault into DRAFTS/<project>/ (inferred). Reserve holdout."""
import sys, re, shutil, pathlib, json
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from infer_project import infer
VAULT = pathlib.Path("/srv/obsidian/vault"); D = pathlib.Path("/var/lib/hinddian/drafts")
HOLD = int(sys.argv[1]) if len(sys.argv) > 1 else 30
moved = {}
items = []
for f in VAULT.glob("项目/*/待入库/*.md"):
    if f.name == "README.md": continue
    t = f.read_text(errors="ignore")
    m = re.search(r"^- 时间：(\S+)", t, re.M)
    items.append((f, infer(t), m.group(1) if m else f.name))
ut = sorted([i for i in items if i[1] == "ut-agent"], key=lambda i: i[2])
hold = {i[0] for i in ut[-HOLD:]} if HOLD else set()
for f, p, _ in items:
    dest = D / ("holdout/" + p if f in hold else p.replace("/", "-"))
    dest.mkdir(parents=True, exist_ok=True)
    shutil.move(str(f), dest / f.name)
    k = str(dest.relative_to(D)); moved[k] = moved.get(k, 0) + 1
print(json.dumps(moved, ensure_ascii=False, indent=1))
