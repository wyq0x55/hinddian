"""Split legacy DECISIONS/LESSONS/PROJECT_STATE + agent使用技巧.md into atomic, wikilinked notes. Run on a COPY.
usage: restructure.py <vault_copy_root>
"""
import re, sys, pathlib, datetime, shutil

ROOT = pathlib.Path(sys.argv[1])
TODAY = datetime.date.today().isoformat()
FOLDER = {"decision": "决策", "lesson": "经验"}
notes = []   # dicts: path(rel, no .md), id, type, project, title, tags, status, supersedes, related, sources, scene, practice, reason

# hand-curated relations / supersession for the trial (keyed by legacy code)
SUPERSEDE = {("笔记系统", "D-006"): ["D-002", "D-005"]}   # Magpie MCP 改 hindsight 取代 obsidian-vault MCP
RELATED = {("笔记系统", "L-005"): ["D-004"], ("笔记系统", "L-006"): ["D-005", "D-006"], ("笔记系统", "L-003"): ["D-001"],
           ("笔记系统", "L-004"): ["D-004"], ("笔记系统", "D-004"): ["D-003"], ("WorkBuddy签到", "L-004"): ["D-001", "L-003"],
           ("WorkBuddy签到", "L-002"): ["D-002"]}
TIP_RELATED = {"Magpie 进程与插件宿主：用 Get-CimInstance 反查": ["工具装在哪：用运行中进程反查真实路径"],
               "Windows 上用 pwsh 而非 powershell": ["工具装在哪：用运行中进程反查真实路径"]}

def safe(t): return re.sub(r'[\\/:*?"<>|]', "-", t).strip()

SLUGS = {
 ("笔记系统","D-001"):"livesync-over-tailscale", ("笔记系统","D-002"):"agent-rw-via-vault-mcp",
 ("笔记系统","D-003"):"adopt-orbital-conventions-only", ("笔记系统","D-004"):"per-project-dirs-light-session-start",
 ("笔记系统","D-005"):"magpie-vault-mcp-public-https", ("笔记系统","D-006"):"magpie-memory-mcp-hindsight-recall",
 ("笔记系统","L-001"):"livesync-must-replicate-once", ("笔记系统","L-002"):"vps-memory-limits",
 ("笔记系统","L-003"):"no-secrets-in-notes", ("笔记系统","L-004"):"short-session-start-hook",
 ("笔记系统","L-005"):"global-state-conflicts", ("笔记系统","L-006"):"no-loopback-in-magpie-library",
 ("WorkBuddy签到","D-001"):"per-account-env-staggered-cron", ("WorkBuddy签到","D-002"):"separate-cn-intl-domains",
 ("WorkBuddy签到","L-001"):"activate-buddy-in-app-first", ("WorkBuddy签到","L-002"):"intl-campaign-may-be-off",
 ("WorkBuddy签到","L-003"):"no-tokens-in-notes", ("WorkBuddy签到","L-004"):"check-refresh-before-relogin",
}
TIP_SLUGS = {"子 Agent 并行委派与 Token 节约":"subagent-parallel-delegation-token-saving",
 "Windows 上用 pwsh 而非 powershell":"windows-use-pwsh-not-powershell",
 "RTK 压缩命令输出：批量执行，慎用 bypass":"rtk-batch-commands-avoid-bypass",
 "工具装在哪：用运行中进程反查真实路径":"find-tool-path-from-running-process",
 "Magpie 进程与插件宿主：用 Get-CimInstance 反查":"magpie-process-inspect-cim",
 "从运行中的可执行文件反查未公开内部 API":"find-internal-api-from-running-binary"}
def slug(proj, code):
    return SLUGS[(proj, code)]

def kv(block, key):
    m = re.search(rf"\*\*{key}[：:]?\*\*[：:]?\s*(.*?)(?=\n- \*\*|\Z)", block, re.S)
    return m.group(1).strip() if m else ""

def parse_sections(text):
    return re.findall(r"^## (.+?)\n(.*?)(?=^## |\Z)", text, re.M | re.S)

def split_project(proj):
    pdir = ROOT / "项目" / proj
    out = {}
    d = (pdir / "DECISIONS.md").read_text() if (pdir / "DECISIONS.md").exists() else ""
    for head, body in parse_sections(d):
        m = re.match(r"(D-\d+)\s*·\s*(.+?)(?:（(\d{4}-\d\d-\d\d)）)?$", head.strip())
        code, title, date = m.group(1), m.group(2), m.group(3) or TODAY
        out[code] = dict(type="decision", code=code, title=title, updated=date,
                         scene="", practice=kv(body, "决定"), reason=kv(body, "理由"), extra=kv(body, "影响"))
    l = (pdir / "LESSONS.md").read_text() if (pdir / "LESSONS.md").exists() else ""
    n = 0
    for head, body in parse_sections(l):
        m = re.match(r"(L-\d+)\s*·\s*(.+)$", head.strip())
        if m: code, title = m.group(1), m.group(2)
        else:  # unnumbered "## 2026-10-17 · xxx" entries get the next number
            code, title = f"L-{n+1:03d}", head.split("·", 1)[-1].strip()
        n = int(code[2:])
        lines = [x[2:].strip() for x in body.strip().splitlines() if x.startswith("- ")]
        out[code] = dict(type="lesson", code=code, title=title, updated=TODAY,
                         scene=lines[0] if lines else "", practice="\n".join(f"- {x}" for x in lines[1:]) or "- （见场景）",
                         reason="", extra="")
    return out

def add(proj, e):
    e.update(project=proj, status="active", supersedes=[], related=[], sources=[], tags=[proj, e["type"]])
    e["id"] = f"proj/{proj}/{e['type']}/{slug(proj, e['code'])}"
    e["path"] = f"项目/{proj}/{FOLDER[e['type']]}/{safe(e['title'])}"
    notes.append(e)

projects = [p.name for p in (ROOT / "项目").iterdir() if p.is_dir() and not p.name.startswith("_")]
state = {}
for proj in projects:
    entries = split_project(proj)
    if proj == "笔记系统":  # state section "2026-10-17 Magpie MCP" is really a decision -> D-006
        entries["D-006"] = dict(type="decision", code="D-006", title="Magpie 记忆 MCP 改用 Hindsight Recall", updated="2026-10-17",
            scene="", practice="Magpie Library 中 `obsidian-vault` 换成 `hindsight` MCP；SessionStart 钩子改 Recall；vault MCP 不再随 Magpie 同步。",
            reason="Agent 记忆走 Hindsight 检索，Obsidian 只做人读真相源。", extra="")
    for e in entries.values(): add(proj, e)
    ps = ROOT / "项目" / proj / "PROJECT_STATE.md"
    state[proj] = ps.read_text() if ps.exists() else ""

bycode = {(n["project"], n["code"]): n for n in notes if n.get("code")}
link = lambda n: f"[[{n['path']}|{n['title']}]]"
for (proj, code), olds in SUPERSEDE.items():
    new = bycode[(proj, code)]
    for o in olds:
        old = bycode[(proj, o)]
        old["status"] = "superseded"; old["superseded_by"] = new
        new["supersedes"].append(old)
for (proj, code), rel in RELATED.items():
    if (proj, code) in bycode:
        for r in rel:
            a, b = bycode[(proj, code)], bycode[(proj, r)]
            a["related"].append(b); b["related"].append(a)

# tips
tips_src = (ROOT / "00-系统/agent使用技巧.md").read_text()
tips = {}
for head, body in parse_sections(tips_src):
    src = re.search(r"src=(\S+)", body)
    clean = re.sub(r"<!--.*?-->", "", body).strip()
    e = dict(type="tip", code="", title=head.strip(), updated=TODAY, project="", status="active", supersedes=[], related=[],
             sources=[pathlib.Path(src.group(1)).stem] if src else [], tags=["agent使用技巧"],
             scene=kv(clean, "场景"), practice=kv(clean, "做法"), reason=kv(clean, "理由"), extra=kv(clean, "推广"))
    e["id"] = "tip/" + TIP_SLUGS.get(e["title"], "tip-" + str(abs(hash(e["title"])) % 10**8))
    e["path"] = f"技巧/{safe(e['title'])}"
    tips[e["title"]] = e; notes.append(e)
for t, rel in TIP_RELATED.items():
    for r in rel:
        tips[t]["related"].append(tips[r]); tips[r]["related"].append(tips[t])

def render(n):
    fm = ["---", f"id: {n['id']}", f"type: {n['type']}", f"project: {n['project'] or 'global'}",
          "tags: [" + ", ".join(n["tags"]) + "]", f"status: {n['status']}",
          "supersedes: [" + ", ".join(f'"{link(o)}"' for o in n["supersedes"]) + "]",
          "related: [" + ", ".join(f'"{link(o)}"' for o in n["related"]) + "]",
          "sources: [" + ", ".join(n["sources"]) + "]", f"updated: {n['updated']}"]
    if not n.get("code") and n["type"]=="tip": pass
    if n.get("code"): fm.append(f"legacy_code: {n['code']}")
    fm.append("---")
    hub = f"[[项目/{n['project']}/README|{n['project']}]]" if n["project"] else "[[技巧/技巧|agent使用技巧]]"
    b = [f"# {n['title']}", "", f"> 所属：{hub}"]
    if n["status"] == "superseded":
        b.append(f"> ⚠️ 已被 {link(n['superseded_by'])} 取代")
    b += ["", "## 场景", n["scene"] or "（原条目未写，待补）", "", "## 做法", n["practice"] or "（待补）", "",
          "## 理由", n["reason"] or "（原条目未写，待补）", ""]
    if n["extra"]: b += ["## 影响 / 推广", n["extra"], ""]
    if n["supersedes"]: b += ["## 取代", *[f"- {link(o)}" for o in n["supersedes"]], ""]
    if n["related"]: b += ["## 相关", *[f"- {link(o)}" for o in n["related"]], ""]
    return "\n".join(fm + b)

# archive originals
arch = ROOT / "_归档" / f"旧格式-{TODAY}"
for proj in projects + ["_模板"]:
    for f in ("DECISIONS.md", "LESSONS.md", "PROJECT_STATE.md"):
        p = ROOT / "项目" / proj / f
        if p.exists():
            (arch / proj).mkdir(parents=True, exist_ok=True); shutil.move(p, arch / proj / f)
    w = ROOT / "项目" / proj / "待入库"
    if w.exists() and not any(w.iterdir()): w.rmdir()
for f in ("agent使用技巧.md", "INDEX.md"):
    (arch / "00-系统").mkdir(parents=True, exist_ok=True); shutil.move(ROOT / "00-系统" / f, arch / "00-系统" / f)

for n in notes:
    p = ROOT / (n["path"] + ".md"); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(render(n))

# project hubs (README = current state + links)
def strip_state(s):
    s = re.sub(r"^# .*\n", "", s); s = re.sub(r"^> \*\*写法.*\n", "", s, flags=re.M)
    return re.sub(r"^## 2026-10-17 Magpie MCP.*", "", s, flags=re.M | re.S).strip()
for proj in projects:
    pdir = ROOT / "项目" / proj
    mine = lambda t: sorted([n for n in notes if n["project"] == proj and n["type"] == t and n["status"] == "active"], key=lambda n: n["path"])
    old = [n for n in notes if n["project"] == proj and n["status"] == "superseded"]
    # include batch-distilled notes already present on disk
    extra = {t: sorted(str(p.relative_to(ROOT))[:-3] for p in (pdir / FOLDER[t]).glob("*.md")
                       if "origin: batch-distill" in p.read_text()) if (pdir / FOLDER[t]).exists() else [] for t in FOLDER}
    docs = sorted(p.stem for p in pdir.glob("*.md") if p.name != "README.md")
    out = ["---", f"id: proj/{proj}/readme", "type: state", f"project: {proj}", f"tags: [{proj}, hub]", "status: active",
           f"updated: {TODAY}", "---", f"# {proj}", "", "> 项目枢纽页：当前状态（覆盖写）+ 全部决策/经验链接。上级：[[00-系统/INDEX|INDEX]]", "",
           strip_state(state[proj]) or "（无状态）", "", "## 决策", *[f"- {link(n)}" for n in mine("decision")],
           *[f"- [[{p}|{pathlib.Path(p).name}]] 〔批量归纳〕" for p in extra["decision"]], "", "## 经验",
           *[f"- {link(n)}" for n in mine("lesson")], *[f"- [[{p}|{pathlib.Path(p).name}]] 〔批量归纳〕" for p in extra["lesson"]], ""]
    if old: out += ["## 已取代", *[f"- ~~{link(n)}~~" for n in old], ""]
    if docs: out += ["## 说明文档", *[f"- [[项目/{proj}/{d}|{d}]]" for d in docs], ""]
    (pdir / "README.md").write_text("\n".join(out))

# tips hub
th = ["---", "id: topic/agent-usage-tips", "type: hub", "project: global", "tags: [agent使用技巧, hub]", f"updated: {TODAY}", "---",
      "# agent使用技巧", "", "> 一条技巧一个文件；本页由脚本生成。上级：[[00-系统/INDEX|INDEX]]", "",
      *[f"- {link(t)} — {t['scene'][:40]}…" for t in tips.values()], ""]
(ROOT / "技巧").mkdir(exist_ok=True); (ROOT / "技巧/技巧.md").write_text("\n".join(th))

# generated INDEX
idx = ["---", "id: system/index", "type: hub", f"updated: {TODAY}", "generated: true", "---", "# 笔记库地图（INDEX）", "",
       "> 由 `tools/restructure.py` 生成，勿手改。Agent 开局走 Hindsight Recall；本页给人导航和图谱枢纽。", "",
       "## 全局", "- [[00-系统/ASKS|ASKS]] — 人→Agent 待办", "- [[技巧/技巧|agent使用技巧]] — " + f"{len(tips)} 条", "", "## 项目"]
for proj in sorted(projects):
    k = sum(1 for n in notes if n["project"] == proj and n["status"] == "active")
    bd = len(list((ROOT / "项目" / proj).rglob("*.md"))) and sum(1 for p in (ROOT / "项目" / proj).rglob("*.md") if "origin: batch-distill" in p.read_text())
    idx.append(f"- [[项目/{proj}/README|{proj}]] — {k} 条决策/经验" + (f"，{bd} 条批量归纳" if bd else ""))
idx += ["", "## 其他", "- [[Orbital-项目深度分析]]", "- [[MCP-测试]]", "- 旧格式原件：`_归档/`", ""]
(ROOT / "00-系统/INDEX.md").write_text("\n".join(idx))
print(f"{len(notes)} atomic notes, {len(projects)} projects, {len(tips)} tips")
