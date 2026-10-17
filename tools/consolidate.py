"""Consolidate near-duplicate notes of one project: similarity hints + model judgment -> merge into winner, mark others superseded.
usage: consolidate.py <project> [--dry-run]"""
import sys, json, itertools
sys.path.insert(0, "/opt/hinddian-classify/src")
import hinddian_batch as h

proj = sys.argv[1]; dry = "--dry-run" in sys.argv
notes = h.load_notes()
for n in notes.values(): h.resolve_ids(n, notes)
pool = [n for n in notes.values() if n["project"] == proj and n["type"] in ("decision", "lesson") and n["status"] == "active"]
G = {n["id"]: h._grams(n["title"] + n["scene"] + n["practice"]) for n in pool}
pairs = sorted(((len(G[a["id"]] & G[b["id"]]) / (len(G[a["id"]] | G[b["id"]]) or 1), a["id"], b["id"]) for a, b in itertools.combinations(pool, 2)), reverse=True)
hints = [f"{s:.2f} {a} <> {b}" for s, a, b in pairs[:60] if s >= 0.12]
listing = "\n".join(f"- id={n['id']} [{n['type']}] {n['title']} :: {n['practice'][:220].replace(chr(10), ' ')}" for n in pool)
prompt = f"""你在整理项目「{proj}」的原子笔记库（{len(pool)} 条），目标：合并近似重复或过碎的笔记，让每条更有力。
规则：只合并讲的是**同一个主题/约定**的笔记；不同主题不要硬合。每组 2-5 条，选最好的作为 winner（保留其 id），
给出合并后完整的 title/scene/practice/reason（吸收所有成员要点，去掉重复）。最多 15 组。不写任何密钥。
只输出 JSON：{{"groups":[{{"winner":"id","members":["其余被合并的 id"],"title":"中文标题","scene":"...","practice":"- ...","reason":"...","why":"一句话说明为何合并"}}]}}

相似度提示（bigram Jaccard，越高越像）：
{chr(10).join(hints)}

笔记列表：
{listing}
"""
data = None
for _ in range(3):
    try: data = h.parse_json(h.chat(prompt)); break
    except Exception as e: err = e
if data is None: sys.exit(f"model failed: {err}")
out, used = [], set()
for g in data.get("groups", [])[:15]:
    w = g.get("winner"); ms = [m for m in g.get("members", []) if m in notes and m != w and m not in used]
    if w not in notes or w in used or not ms or notes[w]["project"] != proj: continue
    used |= {w, *ms}
    W = notes[w]
    if not dry:
        W.update(title=W["title"], scene=g.get("scene") or W["scene"], practice=g.get("practice") or W["practice"],
                 reason=g.get("reason") or W["reason"], updated=h.today())
        if g.get("title"): W["title"] = h.safe(g["title"])
        for m in ms:
            M = notes[m]
            W["sources"] = sorted(set(W["sources"]) | set(M["sources"]))
            W["related"] = [r for r in dict.fromkeys(W["related"] + M["related"]) if r not in ms and r != w]
            W["tags"] = list(dict.fromkeys(W["tags"] + M["tags"]))
            if m not in W["supersedes"]: W["supersedes"].append(m)
            M["status"] = "superseded"; M["superseded_by"] = w
            M["related"] = [r for r in M["related"] if r != w]
    out.append({"winner": w, "winner_title": g.get("title") or W["title"], "members": [notes[m]["title"] for m in ms], "member_ids": ms, "why": g.get("why", "")})
if not dry:
    # members referenced elsewhere: point related links to the winner
    win = {m: g["winner"] for g in out for m in g["member_ids"]}
    for n in notes.values():
        if n["type"] in ("tip", "decision", "lesson") and n["status"] == "active":
            n["related"] = [r for r in dict.fromkeys(win.get(r, r) for r in n["related"]) if r != n["id"]]
    for n in notes.values():
        if n["type"] in ("tip", "decision", "lesson"):
            new = h.render(n, notes)
            if new != n["text"]: h.write_file(n["path"], new)
    h.rebuild_hubs()
print(json.dumps(out, ensure_ascii=False, indent=1))
