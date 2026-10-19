"""Batch distillation trial: group drafts by inferred project, send ONE batch to pi (vault host, magpie group/auto-flash),
get 3-8 merged atomic notes back as JSON. Read-only on drafts.
usage: batch_distill.py build <drafts_dir> <projects.json> <project> <out_prompt.txt>
       batch_distill.py write <pi_output.txt> <trial_root> <project>
"""
import sys, re, json, pathlib, datetime

SECTIONS = ("DECISIONS", "LESSONS")
PER_DRAFT = 600
CAP = 40

def extract(text):
    out = []
    for sec in SECTIONS:
        m = re.search(rf"^## {sec}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
        if m and m.group(1).strip():
            out.append(f"[{sec}]\n" + m.group(1).strip())
    return "\n".join(out)

def sid(name, text):
    m = re.search(r"ingested_from: (\S+)", text)
    return (m.group(1) if m else name).removesuffix(".json").removesuffix("-otlp")

PROMPT = """你是笔记库整理员。下面是同一项目「{proj}」的 {n} 份会话提炼草稿（只含 DECISIONS/LESSONS）。
它们来自不同会话，单看每份都很碎。请做**跨会话归纳**：
1. 找出反复出现（≥2 份草稿）的主题；一次性排障、单个 issue 的进度、具体行号/文件名细节一律丢弃。
2. 合并成 3-8 条可长期复用的原子笔记，每条 type 为 decision（已定的工程约定）或 lesson（踩坑/经验）。
3. 笔记之间如有关联，用 related 填对方的 slug。
4. 不写任何密钥、token、口令。
只输出一个 JSON，不要其它文字：
{{"notes":[{{"slug":"英文小写-连字符","title":"中文短标题","type":"decision|lesson","tags":["..."],
"scene":"场景","practice":"做法（可多行 - 列表）","reason":"理由","related":["其他slug"],"sources":["草稿编号如 S03"]}}],
"themes":["一句话概括每个反复主题"]}}

草稿：
{body}
"""

def build(ddir, pj, proj, out):
    proj_map = json.load(open(pj))
    files = [f for f, p in sorted(proj_map.items()) if p == proj]
    scored = []
    for f in files:
        t = (pathlib.Path(ddir) / f).read_text(errors="ignore")
        ex = extract(t)
        if len(ex) > 200:
            scored.append((f, t, ex))
    # spread across time: take evenly spaced samples instead of the first N
    step = max(1, len(scored) // CAP)
    pick = scored[::step][:CAP]
    body, idx = [], {}
    for i, (f, t, ex) in enumerate(pick, 1):
        k = f"S{i:02d}"
        idx[k] = {"file": f, "session": sid(f, t)}
        body.append(f"### {k}\n{ex[:PER_DRAFT]}")
    pathlib.Path(out).write_text(PROMPT.format(proj=proj, n=len(pick), body="\n\n".join(body)))
    json.dump(idx, open(out + ".idx.json", "w"), ensure_ascii=False, indent=1)
    print(f"{len(files)} drafts in project, {len(scored)} non-trivial, picked {len(pick)}; prompt {len(pathlib.Path(out).read_bytes())} bytes")

def write(piout, root, proj, idx_path):
    raw = pathlib.Path(piout).read_text()
    data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
    idx = json.load(open(idx_path))
    folder = {"decision": "决策", "lesson": "经验"}
    titles = {n["slug"]: n["title"] for n in data["notes"]}
    today = datetime.date.today().isoformat()
    for n in data["notes"]:
        sub = folder.get(n["type"], "经验")
        p = pathlib.Path(root, "项目", proj, sub, n["title"].replace("/", "／") + ".md")
        p.parent.mkdir(parents=True, exist_ok=True)
        rel = [f"[[项目/{proj}/{folder.get(next((m['type'] for m in data['notes'] if m['slug']==r), 'lesson'),'经验')}/{titles[r]}|{titles[r]}]]"
               for r in n.get("related", []) if r in titles and r != n["slug"]]
        srcs = sorted({idx[s]["session"] for s in n.get("sources", []) if s in idx})
        fm = ["---", f"id: proj/{proj}/{n['type']}/{n['slug']}", f"type: {n['type']}", f"project: {proj}",
              "tags: [" + ", ".join(n.get("tags", [])) + "]", "status: active", "supersedes: []",
              "related: [" + ", ".join(f'"{r}"' for r in rel) + "]",
              "sources: [" + ", ".join(srcs) + "]", f"updated: {today}", "origin: batch-distill", "---"]
        body = [f"# {n['title']}", "", f"> 项目：[[项目/{proj}/README|{proj}]] · 批量归纳自 {len(srcs)} 个会话", "",
                "## 场景", n["scene"], "", "## 做法", n["practice"], "", "## 理由", n["reason"], ""]
        if rel:
            body += ["## 相关", *[f"- {r}" for r in rel], ""]
        p.write_text("\n".join(fm + body))
        print("wrote", p)
    pathlib.Path(root, "项目", proj, ".batch-themes.json").write_text(json.dumps(data.get("themes", []), ensure_ascii=False, indent=1))

if __name__ == "__main__":
    if sys.argv[1] == "build": build(*sys.argv[2:6])
    else: write(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
