#!/usr/bin/env python3
"""hinddian batch engine (vault host): drafts outside the vault -> batch / incremental distill -> atomic notes.

Drafts:   /var/lib/hinddian/drafts/<project>/*.md   (holdout/ is never touched by `run`)
Gate:     /var/lib/hinddian/gate.json  {project: {"approved": bool, "approved_at": iso}}
Policy:   project not yet approved: wait until >= THRESHOLD session drafts -> "ready" (dashboard approve button)
          approved project: every run processes new drafts incrementally against existing notes (automatic)
          通用-未定: tips-only extraction, automatic (global tips are always automatic)
Commands: run | approve <project> [--now] | gate --json | process <project> [--dry-run] [--dir D] [--batch N]
          export-notes --json | rebuild-hubs
"""
from __future__ import annotations
import argparse, datetime as dt, fcntl, hashlib, json, os, pathlib, re, shutil, subprocess, sys, urllib.request

for _root in (pathlib.Path(__file__).resolve().parents[1] / "src", pathlib.Path("/opt/hinddian/src"), pathlib.Path("/opt/hinddian-classify/src")):
    if (_root / "hinddian" / "note_format.py").is_file():
        sys.path.insert(0, str(_root)); break
from hinddian import note_format as nf  # noqa: E402

VAULT = pathlib.Path(os.environ.get("HC_VAULT", "/srv/obsidian/vault"))
BASE = pathlib.Path(os.environ.get("HB_BASE", "/var/lib/hinddian"))
DRAFTS, PROCESSED, GATE, LOG = BASE / "drafts", BASE / "processed", BASE / "gate.json", BASE / "batch-ledger.jsonl"
THRESHOLD = int(os.environ.get("HB_THRESHOLD", "20"))
BATCH = int(os.environ.get("HB_BATCH", "20"))
PER_DRAFT = int(os.environ.get("HB_PER_DRAFT", "1500"))
RUN_MAX_BATCHES = int(os.environ.get("HB_RUN_MAX_BATCHES", "3"))
GATEWAY = os.environ.get("HB_GATEWAY", "http://127.0.0.1:3425/v1/chat/completions")
MODEL = os.environ.get("HB_MODEL", "group/auto-flash")
UNKNOWN = "通用-未定"
DEDUPE = float(os.environ.get("HB_DEDUPE", "0.40"))
FULL_TOP = int(os.environ.get("HB_FULL_TOP", "25"))
SPECIAL = {"holdout", UNKNOWN}
FOLDER = nf.FOLDER
OWNER = os.environ.get("HC_OWNER", "obsidian")

def today(): return dt.date.today().isoformat()
def now(): return dt.datetime.now().astimezone().isoformat(timespec="seconds")
def log(ev):
    BASE.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as f: f.write(json.dumps({"at": now(), **ev}, ensure_ascii=False) + "\n")
redact, safe, slugify, link_of = nf.redact, nf.safe_title, nf.slugify, nf.link_of

# ------------------------------------------------------------------ notes (format shared with hinddian.notes)
_cache = nf.NoteCache()
def load_notes(): return _cache.load(VAULT)
def render(n, notes): return nf.render(n, notes, today=today())
def write_file(rel, text): return nf.write_note_file(VAULT, rel, text, owner=OWNER)
def clean_field(t): return nf.guard_field(nf.unwiki(t or ""))

# ------------------------------------------------------------------ hubs
def _grams(t):
    t = re.sub(r"\s+", "", t or ""); return {t[i:i + 2] for i in range(len(t) - 1)}

def suggest_related(notes, k=3, thr=0.12):
    """Add up to k related links by bigram Jaccard within the same project (or among tips)."""
    pool = [n for n in notes.values() if n["type"] in ("tip", "decision", "lesson") and n["status"] == "active"]
    g = {n["id"]: _grams(n["title"] + n["scene"] + n["practice"]) for n in pool}
    for n in pool:
        if len(n["related"]) >= k: continue
        cands = [m for m in pool if m["id"] != n["id"] and m["id"] not in n["related"] and (m["project"] == n["project"])]
        sc = sorted(((len(g[n["id"]] & g[m["id"]]) / (len(g[n["id"]] | g[m["id"]]) or 1), m["id"]) for m in cands), reverse=True)
        for score, mid in sc[: k - len(n["related"])]:
            if score >= thr:
                n["related"].append(mid)
                if n["id"] not in notes[mid]["related"]: notes[mid]["related"].append(n["id"])

def repair_notes():
    """Re-render notes whose related/supersedes point at missing notes (or contain stray wikilinks in body)."""
    with nf.vault_lock(): return _repair_notes()

def _repair_notes():
    notes = load_notes(); fixed = 0
    for n in notes.values():
        if n["type"] not in ("tip", "decision", "lesson"): continue
        n["related"] = [r for r in n["related"] if r in notes and r != n["id"]]
        n["supersedes"] = [r for r in n["supersedes"] if r in notes]
    suggest_related(notes)
    for n in notes.values():
        if n["type"] not in ("tip", "decision", "lesson"): continue
        new = render(n, notes)
        if new != n["text"]: write_file(n["path"], new); fixed += 1
    return fixed

def rebuild_hubs():
    with nf.vault_lock(): _rebuild_hubs()

def _rebuild_hubs():
    _repair_notes()
    try:
        import graph_colors; graph_colors.main()
    except Exception as e: log({"event": "graph_colors_error", "error": str(e)[:200]})
    notes = load_notes()
    projects = sorted(p.name for p in (VAULT / "项目").iterdir() if p.is_dir() and not p.name.startswith(("_", ".")))
    for proj in projects:
        pdir = VAULT / "项目" / proj
        mine = [n for n in notes.values() if n["project"] == proj and n["type"] in FOLDER]
        rd = pdir / "README.md"
        head = ""
        if rd.exists():
            t = rd.read_text(); i = t.find("\n## 决策")
            head = t[:i] if i >= 0 else t
        if not head.strip():
            head = "\n".join(["---", f"id: proj/{proj}/readme", "type: state", f"project: {proj}", f"tags: [{proj}, hub]",
                              "status: active", f"updated: {today()}", "---", f"# {proj}", "",
                              "> 项目枢纽页：当前状态（覆盖写）+ 全部决策/经验链接。上级：[[00-系统/INDEX|INDEX]]", "", "## 当前状态", "（待补）"])
        act = lambda t: sorted([n for n in mine if n["type"] == t and n["status"] == "active"], key=lambda n: n["title"])
        old = [n for n in mine if n["status"] == "superseded"]
        docs = sorted(p.stem for p in pdir.glob("*.md") if p.name != "README.md")
        out = [head.rstrip(), "", "## 决策", *[f"- {link_of(n)}" for n in act("decision")], "", "## 经验", *[f"- {link_of(n)}" for n in act("lesson")], ""]
        if old: out += ["## 已取代", *[f"- ~~{link_of(n)}~~" for n in old], ""]
        if docs: out += ["## 说明文档", *[f"- [[项目/{proj}/{d}|{d}]]" for d in docs], ""]
        write_file(f"项目/{proj}/README", "\n".join(out))
    tips = sorted([n for n in notes.values() if n["type"] == "tip" and n["status"] == "active"], key=lambda n: n["title"])
    th = ["---", "id: topic/agent-usage-tips", "type: hub", "project: global", "tags: [agent使用技巧, hub]", f"updated: {today()}", "---",
          "# agent使用技巧", "", "> 一条技巧一个文件；本页由 hinddian 生成。上级：[[00-系统/INDEX|INDEX]]", "",
          *[f"- {link_of(t)} — {t['scene'][:40].replace(chr(10), ' ')}…" for t in tips], ""]
    write_file("技巧/技巧", "\n".join(th))
    idx = ["---", "id: system/index", "type: hub", f"updated: {today()}", "generated: true", "---", "# 笔记库地图（INDEX）", "",
           "> 由 hinddian 生成，勿手改。Agent 开局走 Hindsight Recall；本页给人导航和图谱枢纽。", "",
           "## 全局", "- [[00-系统/ASKS|ASKS]] — 人→Agent 待办", f"- [[技巧/技巧|agent使用技巧]] — {len(tips)} 条", "", "## 项目"]
    for proj in projects:
        k = sum(1 for n in notes.values() if n["project"] == proj and n["type"] in FOLDER and n["status"] == "active")
        idx.append(f"- [[项目/{proj}/README|{proj}]] — {k} 条决策/经验")
    others = sorted(p.stem for p in VAULT.glob("*.md"))
    idx += ["", "## 其他", *[f"- [[{o}]]" for o in others], "- 旧格式原件：`_归档/`", ""]
    write_file("00-系统/INDEX", "\n".join(idx))

# ------------------------------------------------------------------ llm
def chat(prompt: str) -> str:
    body = json.dumps({"model": MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2}).encode()
    req = urllib.request.Request(GATEWAY, data=body, headers={"Content-Type": "application/json", "Authorization": "Bearer magpie"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]

def parse_json(out: str):
    out = re.sub(r"^```(?:json)?|```$", "", out.strip(), flags=re.M)
    return json.loads(out[out.find("{"): out.rfind("}") + 1])

def extract(text):
    parts = []
    for sec in ("DECISIONS", "LESSONS"):
        m = re.search(rf"^## {sec}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
        if m and m.group(1).strip(): parts.append(f"[{sec}]\n" + m.group(1).strip())
    return "\n".join(parts)

def session_of(name, text):
    m = re.search(r"ingested_from: (\S+)", text)
    return (m.group(1) if m else name).removesuffix(".json").removesuffix("-otlp").removesuffix(".md")

PROMPT = """你是用户的笔记库维护员。任务：把一批会话提炼草稿合并进**已有**原子笔记库。{mode}

规则：
- 只保留可长期复用的知识（工程约定=decision、踩坑经验=lesson、跨项目通用的 agent 使用技巧=tip）。一次性排障、某个 issue 的进度、文件行号、寒暄、子 agent 执行流水一律丢弃。
- 草稿内容与已有笔记同主题 → op=update，给出该笔记 id 和**合并后的完整**场景/做法/理由（保留旧要点，补充新要点，删除被推翻的说法）。
- 真正的新主题（最好 ≥2 份草稿出现）→ op=create，slug 用英文小写连字符、描述性。
- 新结论推翻了旧笔记 → op=create 新笔记并在 supersedes 填旧 id。
- related 填相关笔记的 id（已有 id 或本批新建的 "new:<slug>"）。
- 宁少勿滥：本批最多 {maxops} 个 op；没有值得记的就返回空 ops。
- 绝不写密钥、token、口令、证书内容。
只输出 JSON：
{{"ops":[{{"op":"create|update","id":"(update 时必填已有 id)","slug":"english-slug","title":"中文短标题","type":"decision|lesson|tip",
"tags":["..."],"scene":"场景","practice":"做法（- 列表）","reason":"理由","related":["id 或 new:slug"],"supersedes":["id"],"sources":["S01"]}}]}}

## 已有笔记（{nn} 条）
{existing}

## 草稿（{nd} 份）
{drafts}
"""

def note_digest(n, full=True):
    s = f"### id={n['id']} type={n['type']} 标题={n['title']}"
    if full: s += f"\n场景：{n['scene'][:300]}\n做法：{n['practice'][:700]}\n理由：{n['reason'][:300]}"
    return s

def process(project: str, files: list[pathlib.Path], dry=False, review_decisions=False):
    notes = load_notes()  # snapshot for the prompt; the LLM call can take minutes, so no lock yet
    tips_only = project == UNKNOWN
    pool = [n for n in notes.values() if n["status"] == "active" and (n["type"] == "tip" or (not tips_only and n["project"] == project))]
    idx, chunks = {}, []
    for i, f in enumerate(files, 1):
        t = f.read_text(errors="ignore"); k = f"S{i:02d}"
        idx[k] = session_of(f.name, t); chunks.append(f"### {k}\n{redact(extract(t)[:PER_DRAFT])}")
    # large pools: full text for the notes most similar to this batch, titles for the rest
    bg = _grams("".join(chunks))
    ranked = sorted(pool, key=lambda n: -len(bg & _grams(n["title"] + n["scene"] + n["practice"])))
    full = {n["id"] for n in ranked[:FULL_TOP]} if len(pool) > 60 else {n["id"] for n in pool}
    existing = "\n\n".join(note_digest(n, n["id"] in full) for n in ranked) or "（空）"
    mode = ("这些草稿项目归属不明：**只提取跨项目通用的 agent 使用技巧（type=tip）**，其余全部忽略。" if tips_only
            else f"项目：「{project}」。项目相关的写 decision/lesson；通用 agent 技巧写 tip。")
    prompt = PROMPT.format(mode=mode, maxops=8, nn=len(pool), existing=existing, nd=len(files), drafts="\n\n".join(chunks))
    for attempt in range(3):
        try: data = parse_json(chat(prompt)); break
        except (ValueError, KeyError) as e:
            if attempt == 2: raise RuntimeError(f"model output unparseable after 3 tries: {e}")
    with nf.vault_lock(timeout=300):
        return _apply(project, files, data, idx, dry, review_decisions)

def _queue_decision(project, nid, typ, op, srcs, rel, olds, notes, ndrafts, dry):
    """Hand one decision op to the dashboard's Agent-correction queue instead of writing it."""
    from hinddian import notes as N
    payload = {k: op[k] for k in ("title", "slug", "scene", "practice", "reason", "tags") if op.get(k)}
    payload.update(type=typ, project=project, sources=srcs, related=[r for r in rel if r in notes], origin="batch-distill",
                   correction_reason=f"批处理增量（{ndrafts} 份会话草稿）提出的决策改动")
    if nid in notes:
        payload.update(action="update", id=nid)
    elif olds:
        payload.update(action="supersede", supersedes=olds)
    else:
        payload.update(action="add")
    if dry: return None
    return N.enqueue_correction(payload)["suggestion_id"]

def _apply(project, files, data, idx, dry, review_decisions=False):
    """Apply the model's ops against a fresh read of the vault (MCP upserts may have landed meanwhile).
    review_decisions: queue decision creates/updates/supersedes for the dashboard instead of writing them."""
    notes = load_notes()
    tips_only = project == UNKNOWN
    pool = [n for n in notes.values() if n["status"] == "active" and (n["type"] == "tip" or (not tips_only and n["project"] == project))]
    plan, newids = [], {}
    def norm(op):
        for k in ("scene", "practice", "reason", "title", "slug", "id"):
            v = op.get(k)
            if isinstance(v, list): op[k] = "\n".join(f"- {x}" for x in v) if k == "practice" else "；".join(map(str, v))
            elif v is not None and not isinstance(v, str): op[k] = str(v)
        for k in ("scene", "practice", "reason"):
            if op.get(k): op[k] = clean_field(op[k])
        for k in ("tags", "related", "supersedes", "sources"):
            v = op.get(k) or []
            v = v if isinstance(v, list) else [v]
            flat = []
            for x in v: flat += x if isinstance(x, list) else [x]
            op[k] = [str(x) for x in flat if x]
        return op
    for op in [norm(o) for o in data.get("ops", []) if isinstance(o, dict)][:8]:
        typ = op.get("type") if op.get("type") in ("decision", "lesson", "tip") else "lesson"
        if tips_only and typ != "tip": continue
        dup = None
        if op.get("op") != "update":  # local dedupe: model only sees titles when the pool is large
            best = max(((nf.similarity(op.get("title", ""), op.get("practice", ""), m), m["id"]) for m in pool if m["type"] == typ), default=(0, None))
            if best[0] >= DEDUPE: dup = best[1]
        if op.get("op") == "update" and op.get("id") in notes:
            nid = op["id"]
        elif dup:
            nid = dup; op["merged_by_dedupe"] = True
        else:  # a create never lands on an existing note: a taken id gets a suffix
            slug = slugify(op.get("slug") or op.get("title", ""))
            base = f"tip/{slug}" if typ == "tip" else f"proj/{project}/{typ}/{slug}"
            nid, k = base, 2
            while nid in notes or any(nid == p[0] for p in plan):
                nid, k = f"{base}-{k}", k + 1
        newids["new:" + (op.get("slug") or "")] = nid
        plan.append((nid, typ, op))
    result, done = [], []
    for nid, typ, op in plan:
        srcs = sorted({idx[s] for s in op.get("sources", []) if s in idx})
        rel = [newids.get(r, r) for r in op.get("related", [])]
        olds = [o for o in op.get("supersedes", []) if o in notes and o != nid]
        if review_decisions and (typ == "decision" or notes.get(nid, {}).get("type") == "decision"
                                 or any(notes[o]["type"] == "decision" for o in olds)):
            # incremental runs are unattended: decision changes wait in the dashboard queue
            q = _queue_decision(project, nid, typ, op, srcs, rel, olds, notes, len(files), dry)
            result.append({"action": "queued", "id": nid, "title": op.get("title") or notes.get(nid, {}).get("title", ""), "suggestion_id": q})
            continue
        done.append((nid, typ, op))
        if nid in notes:
            n = notes[nid]; action = "update"
            n.update(scene=op.get("scene") or n["scene"], practice=op.get("practice") or n["practice"], reason=op.get("reason") or n["reason"],
                     sources=sorted(set(n["sources"]) | set(srcs)), updated=today())
            n["related"] = list(dict.fromkeys(n["related"] + [r for r in rel if r != nid]))
            n["tags"] = list(dict.fromkeys(n["tags"] + op.get("tags", [])))
        else:
            action = "create"
            title = safe(op.get("title") or nid.rsplit("/", 1)[-1])
            path = f"技巧/{title}" if typ == "tip" else f"项目/{project}/{FOLDER[typ]}/{title}"
            if any(x["path"] == path for x in notes.values()): path += f"-{nid.rsplit('/', 1)[-1][:12]}"
            n = nf.new_note(id=nid, path=path, type=typ, project="" if typ == "tip" else project, tags=op.get("tags", []),
                            sources=srcs, related=[r for r in rel if r != nid], title=title, scene=op.get("scene", ""),
                            practice=op.get("practice", ""), reason=op.get("reason", ""), updated=today(), origin="batch-distill")
            notes[nid] = n
        for old in op.get("supersedes", []):
            if old in notes and old != nid:
                notes[old]["status"] = "superseded"; notes[old]["superseded_by"] = nid; notes[old]["updated"] = today()
                if old not in n["supersedes"]: n["supersedes"].append(old)
        if op.get("merged_by_dedupe"): action = "update(dedupe)"
        result.append({"action": action, "id": nid, "title": n["title"], "sources": len(srcs), "supersedes": n["supersedes"]})
    # keep backlinks symmetric
    for nid, _, _ in done:
        for r in notes[nid]["related"]:
            if r in notes and nid not in notes[r]["related"]: notes[r]["related"].append(nid)
    if dry: return result
    touched = {nid for nid, _, _ in done} | {r for nid, _, _ in done for r in notes[nid]["related"] + notes[nid]["supersedes"]}
    for nid in touched:
        if nid in notes and notes[nid]["type"] in ("tip", "decision", "lesson"):
            notes[nid]["related"] = [r for r in notes[nid]["related"] if r in notes]
            write_file(notes[nid]["path"], render(notes[nid], notes))
    dest = PROCESSED / project; dest.mkdir(parents=True, exist_ok=True)
    for f in files: shutil.move(str(f), dest / f.name)
    log({"event": "batch", "project": project, "drafts": len(files), "ops": result})
    return result

def drafts_of(project, d=None):
    d = pathlib.Path(d) if d else DRAFTS / project
    return sorted(d.glob("*.md")) if d.exists() else []

# ------------------------------------------------------------------ gate
def load_gate(): return json.loads(GATE.read_text()) if GATE.exists() else {}
def save_gate(g): GATE.write_text(json.dumps(g, ensure_ascii=False, indent=1))

def gate_status():
    g, out = load_gate(), []
    for d in sorted(DRAFTS.iterdir()) if DRAFTS.exists() else []:
        if not d.is_dir() or d.name == "holdout": continue
        n = len(list(d.glob("*.md"))); st = g.get(d.name, {})
        if d.name == UNKNOWN: state = "auto-tips"
        elif st.get("approved"): state = "incremental"
        elif n >= THRESHOLD: state = "ready"
        else: state = "accumulating"
        out.append({"project": d.name, "drafts": n, "threshold": THRESHOLD, "state": state, "approved_at": st.get("approved_at"),
                    "running": st.get("running", False), "processed": len(list((PROCESSED / d.name).glob("*.md"))) if (PROCESSED / d.name).exists() else 0})
    hold = DRAFTS / "holdout"
    return {"projects": out, "holdout": {p.name: len(list(p.glob("*.md"))) for p in hold.iterdir()} if hold.exists() else {}}

class Lock:
    def __enter__(self):
        BASE.mkdir(parents=True, exist_ok=True); self.f = open(BASE / "batch.lock", "w")
        try: fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("busy: another batch run holds batch.lock", file=sys.stderr); sys.exit(75)  # EX_TEMPFAIL
    def __exit__(self, *a): self.f.close()

def run_project(project, max_batches=None, review_decisions=False):
    k = 0
    while (files := drafts_of(project)) and (max_batches is None or k < max_batches):
        try: r = process(project, files[:BATCH], review_decisions=review_decisions); print(project, json.dumps(r, ensure_ascii=False))
        except Exception as e: log({"event": "error", "project": project, "error": str(e)[:300]}); print("ERR", project, e); break
        k += 1
    rebuild_hubs()

def cmd_run(force_below: bool = False):
    with Lock():
        for p in gate_status()["projects"]:
            if p["state"] in ("incremental", "auto-tips") and p["drafts"]:
                # tips: wait for a handful so the model sees >1 session (unless force timer)
                if p["state"] == "auto-tips" and p["drafts"] < 5 and not force_below: continue
                run_project(p["project"], RUN_MAX_BATCHES, review_decisions=True)
            elif force_below and p["state"] == "incremental" and p["drafts"]:
                run_project(p["project"], RUN_MAX_BATCHES, review_decisions=True)

def cmd_approve(project, now_=False):
    g = load_gate(); g.setdefault(project, {}).update(approved=True, approved_at=now()); save_gate(g)
    log({"event": "approve", "project": project})
    if now_:
        with Lock():
            g = load_gate(); g[project]["running"] = True; save_gate(g)
            try: run_project(project)
            finally: g = load_gate(); g[project]["running"] = False; save_gate(g)
    elif shutil.which("systemd-run"):
        subprocess.Popen(["systemd-run", "--unit", f"hinddian-batch-{abs(hash(project)) % 10**6}", "--collect",
                          sys.executable, __file__, "approve", project, "--now"])
    else:  # no systemd (dev box / container): detach a plain background process
        subprocess.Popen([sys.executable, __file__, "approve", project, "--now"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return {"ok": True, "project": project}

def cmd_export():
    """Notes for the Hindsight sync. `text` is the index text (no frontmatter / generated link lines)
    and `sha` covers only what gets indexed, so relinking or a date bump doesn't trigger a re-retain."""
    out = []
    for n in load_notes().values():
        if n["type"] in ("tip", "decision", "lesson", "state"):
            text = nf.index_text(n)
            sha = hashlib.sha256(f"{n['type']}|{n['project']}|{n['title']}\n{text}".encode()).hexdigest()[:16]
            out.append({"id": n["id"], "path": n["path"], "type": n["type"], "project": n["project"], "status": n["status"],
                        "title": n["title"], "sha": sha, "text": text})
    return out

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd"); ap.add_argument("arg", nargs="?")
    ap.add_argument("--json", action="store_true"); ap.add_argument("--now", action="store_true")
    ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--dir"); ap.add_argument("--batch", type=int)
    a = ap.parse_args()
    if a.batch: BATCH = a.batch
    if a.cmd == "run": cmd_run()
    elif a.cmd == "run-force": cmd_run(force_below=True)
    elif a.cmd == "export-routing":
        from pathlib import Path as P; import sys as S
        for root in (P(__file__).resolve().parents[1] / "src", P("/opt/hinddian/src"), P("/opt/hinddian-classify/src")):
            if root.is_dir():
                S.path.insert(0, str(root))
        from hinddian.notes import export_routing as er
        print(json.dumps(er(), ensure_ascii=False))
    elif a.cmd == "approve": print(json.dumps(cmd_approve(a.arg, a.now), ensure_ascii=False))
    elif a.cmd == "gate": print(json.dumps(gate_status(), ensure_ascii=False))
    elif a.cmd == "export-notes": print(json.dumps(cmd_export(), ensure_ascii=False))
    elif a.cmd == "rebuild-hubs": rebuild_hubs()
    elif a.cmd == "process":
        files = drafts_of(a.arg, a.dir)
        res = []
        for i in range(0, len(files), BATCH):
            try: res.append(process(a.arg, files[i:i + BATCH], dry=a.dry_run))
            except Exception as e: print("ERR batch", i, e, file=sys.stderr); log({"event": "error", "project": a.arg, "error": str(e)[:300]})
        if not a.dry_run: rebuild_hubs()
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else: ap.error("unknown cmd")
