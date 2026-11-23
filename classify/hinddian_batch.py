#!/usr/bin/env python3
"""Organize local session drafts into Obsidian atomic notes.

`run` processes pending projects; `process PROJECT` targets one project.
The holdout tree is reserved for manual comparisons. 通用-未定 only produces tips.
"""
from __future__ import annotations
import argparse, contextlib, datetime as dt, json, os, pathlib, re, shutil, sys, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.append(str(ROOT / "tools"))
from hinddian import draft_store, note_format as nf, paths  # noqa: E402

VAULT = paths.vault_dir()
BASE = paths.state_dir()
DRAFTS, PROCESSED, LOG = paths.drafts_dir(), paths.processed_dir(), BASE / "batch-ledger.jsonl"
BATCH = int(os.environ.get("HB_BATCH", "20"))
PER_DRAFT = int(os.environ.get("HB_PER_DRAFT", "1500"))
RUN_MAX_BATCHES = int(os.environ.get("HB_RUN_MAX_BATCHES", "3"))
GATEWAY = os.environ.get("HB_GATEWAY", "http://127.0.0.1:3425/v1/chat/completions")
MODEL = os.environ.get("HB_MODEL", "group/auto-flash")
UNKNOWN = "通用-未定"
DEDUPE = float(os.environ.get("HB_DEDUPE", "0.40"))
FULL_TOP = int(os.environ.get("HB_FULL_TOP", "25"))
FOLDER = nf.FOLDER
OWNER = os.environ.get("HC_OWNER")

def today(): return dt.date.today().isoformat()
def now(): return dt.datetime.now().astimezone().isoformat(timespec="seconds")
def log(ev):
    BASE.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as f: f.write(json.dumps({"at": now(), **ev}, ensure_ascii=False) + "\n")
redact, safe, slugify, link_of = nf.redact, nf.safe_title, nf.slugify, nf.link_of

# ------------------------------------------------------------------ notes
_cache = nf.NoteCache()
def load_notes(): return _cache.load(VAULT)
def render(n, notes): return nf.render(n, notes, today=today())
def write_file(rel, text, *, create=False): return nf.write_note_file(VAULT, rel, text, owner=OWNER, create=create)
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
    """Repair related links and re-render the atomic notes."""
    with nf.vault_lock(): return _repair_notes()

def _repair_notes():
    notes = load_notes(); fixed = 0
    for n in notes.values():
        if n["type"] not in ("tip", "decision", "lesson"): continue
        n["related"] = [link for link in n["related"] if link != n["id"]]
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
        import graph_colors; graph_colors.main(VAULT)
    except Exception as e: log({"event": "graph_colors_error", "error": str(e)[:200]})
    notes = load_notes()
    projects = draft_store.project_names(VAULT)
    for proj in projects:
        pdir = VAULT / "项目" / proj
        mine = [n for n in notes.values() if n["project"] == proj and n["type"] in FOLDER]
        rd = nf.within(VAULT, f"项目/{proj}/README")
        head = rd.read_text(encoding="utf-8") if rd.exists() else "\n".join([
            nf.dump_frontmatter([("id", f"proj/{proj}/readme"), ("type", "state"), ("project", proj),
                                 ("tags", [proj, "hub"]), ("status", "active"), ("updated", today())]),
            f"# {proj}", "", "> 上级：[[00-系统/INDEX|INDEX]]", "", "## 当前状态", "（待补）", "",
        ])
        act = lambda t: sorted([n for n in mine if n["type"] == t and n["status"] == "active"], key=lambda n: n["title"])
        docs = sorted(p.stem for p in pdir.glob("*.md") if p.name != "README.md")
        sections = {"决策": [f"- {link_of(n)}" for n in act("decision")],
                    "经验": [f"- {link_of(n)}" for n in act("lesson")],
                    "说明文档": [f"- [[项目/{proj}/{d}|{d}]]" for d in docs]}
        out = hub_links(head, sections)
        if out != head or not rd.exists():
            write_file(f"项目/{proj}/README", out, create=not rd.exists())
    tips = sorted([n for n in notes.values() if n["type"] == "tip" and n["status"] == "active"], key=lambda n: n["title"])
    th = ["---", "id: topic/agent-usage-tips", "type: hub", "project: global", "tags: [agent使用技巧, hub]", f"updated: {today()}", "---",
          "# agent使用技巧", "", "> 上级：[[00-系统/INDEX|INDEX]]", ""]
    write_hub("技巧/技巧", "topic/agent-usage-tips", "\n".join(th),
              {"技巧": [f"- {link_of(t)}" for t in tips]})
    idx = ["---", "id: system/index", "type: hub", f"updated: {today()}", "generated: true", "---", "# 笔记库地图（INDEX）", "",
           "## 全局", "- [[00-系统/ASKS|ASKS]] — 人→Agent 待办", ""]
    entries = []
    for proj in projects:
        k = sum(1 for n in notes.values() if n["project"] == proj and n["type"] in FOLDER and n["status"] == "active")
        entries.append(f"- [[项目/{proj}/README|{proj}]] — {k} 条决策/经验")
    others = sorted(p.stem for p in VAULT.glob("*.md"))
    write_hub("00-系统/INDEX", "system/index", "\n".join(idx),
              {"全局": [f"- [[技巧/技巧|agent使用技巧]] — {len(tips)} 条"],
               "项目": entries, "其他": [f"- [[{o}]]" for o in others]})


def hub_links(text, sections):
    """Keep the existing page byte for byte outside generated link blocks."""
    marker = re.compile(r"(?m)^<!-- hinddian:links -->\n[\s\S]*?^<!-- /hinddian:links -->\n")
    parts = re.split(r"(?m)(?=^## )", text)
    sections = sections.copy()
    targets = {match[1] for match in nf.WIKI.finditer(marker.sub("", text))}
    for index, part in enumerate(parts[1:], 1):
        heading = part.split("\n", 1)[0][3:].strip()
        if heading in sections:
            parts[index] = _hub_section(marker, part, sections.pop(heading), targets)
    for heading, lines in sections.items():
        section = _hub_section(marker, f"## {heading}\n", lines, targets)
        if "<!-- hinddian:links -->" in section:
            prefix = "" if "".join(parts).endswith("\n\n") else "\n"
            parts.append(prefix + section)
    return "".join(parts)


def _hub_section(marker, part, lines, targets):
    manual = marker.sub("", part)
    generated = [line for line in lines if (match := nf.WIKI.search(line)) and match[1] not in targets]
    if not generated:
        return manual
    block = "<!-- hinddian:links -->\n" + "\n".join(generated) + "\n<!-- /hinddian:links -->\n"
    if found := marker.search(part):
        return part[:found.start()] + block + part[found.end():]
    return manual + ("" if manual.endswith("\n") else "\n") + block + "\n"


def write_hub(rel, note_id, text, sections):
    path = nf.within(VAULT, rel)
    if path.is_file():
        old = path.read_text(encoding="utf-8")
        parsed = nf.parse_frontmatter(old)
        if not parsed or parsed[0].get("id") != note_id:
            return
        new = hub_links(old, sections)
        if new != old:
            write_file(rel, new)
    else:
        write_file(rel, hub_links(text, sections), create=True)

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
    parsed = nf.parse_frontmatter(text)
    if parsed and isinstance(sid := parsed[0].get("session_id"), str) and sid.strip():
        return sid.strip()
    m = re.search(r"ingested_from: (\S+)", text)
    return (m.group(1) if m else name).removesuffix(".json").removesuffix("-otlp").removesuffix(".md")

PROMPT = """你是用户的笔记库维护员。任务：把一批会话提炼草稿合并进**已有**原子笔记库。{mode}

规则：
- 只保留可长期复用的知识（工程约定=decision、踩坑经验=lesson、跨项目通用的 agent 使用技巧=tip）。一次性排障、某个 issue 的进度、文件行号、寒暄、子 agent 执行流水一律丢弃。
- 草稿内容与已有笔记同主题 → op=update，给出该笔记 id 和**合并后的完整**场景/做法/理由（保留旧要点，补充新要点，删除被推翻的说法）。
- 真正的新主题（最好 ≥2 份草稿出现）→ op=create，slug 用英文小写连字符、描述性。
- 标题即命题，明确表达决定或经验；每条笔记填齐场景/做法/理由，不写成无分段的文本堆，不编造缺失事实。
- related 填相关笔记的 id（已有 id 或本批新建的 "new:<slug>"）。
- 宁少勿滥：本批最多 {maxops} 个 op；没有值得记的就返回空 ops。
- 绝不写密钥、token、口令、证书内容。
只输出 JSON：
{{"ops":[{{"op":"create|update","id":"(update 时必填已有 id)","slug":"english-slug","title":"中文短标题","type":"decision|lesson|tip",
"tags":["..."],"scene":"场景","practice":"做法（- 列表）","reason":"理由","related":["id 或 new:slug"],"sources":["S01"]}}]}}

## 已有笔记（{nn} 条）
{existing}

## 草稿（{nd} 份）
{drafts}
"""

def note_digest(n, full=True):
    s = f"### id={n['id']} type={n['type']} 标题={n['title']}"
    if full: s += f"\n场景：{redact(n['scene'])[:300]}\n做法：{redact(n['practice'])[:700]}\n理由：{redact(n['reason'])[:300]}"
    return redact(s)

def process(project: str, files: list[pathlib.Path], dry=False):
    validate_project(project)
    check_draft_paths()
    notes = load_notes()  # snapshot for the prompt; the LLM call can take minutes, so no lock yet
    tips_only = project == UNKNOWN
    pool = [n for n in notes.values() if n["status"] == "active" and (n["type"] == "tip" or (not tips_only and n["project"] == project))]
    idx, chunks, snapshots = {}, [], {}
    for i, f in enumerate(files, 1):
        paths.check_draft_root(f, VAULT)
        snapshots[f] = f.read_bytes()
        text = snapshots[f].decode("utf-8", errors="replace")
        key = f"S{i:02d}"
        idx[key] = redact(session_of(f.name, text))
        chunks.append(f"### {key}\n{extract(redact(text))[:PER_DRAFT]}")
    # large pools: full text for the notes most similar to this batch, titles for the rest
    bg = _grams("".join(chunks))
    ranked = sorted(pool, key=lambda n: -len(bg & _grams(n["title"] + n["scene"] + n["practice"])))
    full = {n["id"] for n in ranked[:FULL_TOP]} if len(pool) > 60 else {n["id"] for n in pool}
    existing = "\n\n".join(note_digest(n, n["id"] in full) for n in ranked) or "（空）"
    mode = ("这些草稿项目归属不明：**只提取跨项目通用的 agent 使用技巧（type=tip）**，其余全部忽略。" if tips_only
            else f"项目：「{redact(project)}」。项目相关的写 decision/lesson；通用 agent 技巧写 tip。")
    prompt = PROMPT.format(mode=mode, maxops=8, nn=len(pool), existing=existing, nd=len(files), drafts="\n\n".join(chunks))
    for attempt in range(3):
        try: data = parse_json(chat(prompt)); break
        except (ValueError, KeyError) as e:
            if attempt == 2: raise RuntimeError(f"model output unparseable after 3 tries: {e}")
    with nf.vault_lock(timeout=300):
        if any(f.read_bytes() != original for f, original in snapshots.items()):
            raise RuntimeError("a draft changed during the model call; retry with the latest drafts")
        return _apply(project, files, data, idx, dry, before=notes)


def validate_project(project):
    if not draft_store.valid_project(project) or project == "holdout":
        raise ValueError(f"invalid project: {project!r}")


def check_draft_paths():
    for root in (DRAFTS, PROCESSED):
        paths.check_draft_root(root, VAULT)
    pending, processed = DRAFTS.resolve(), PROCESSED.resolve()
    if pending.is_relative_to(processed) or processed.is_relative_to(pending):
        raise ValueError("drafts and processed must be separate directories")


def new_path(base, notes):
    occupied = {"技巧/技巧", *(note["path"] for note in notes.values())}
    path, suffix = base, 2
    while path in occupied or (VAULT / (path + ".md")).is_symlink() or nf.within(VAULT, path).exists():
        path, suffix = f"{base}-{suffix}", suffix + 1
    return path


def _apply(project, files, data, idx, dry, *, before=None):
    """Apply model operations under the vault lock using a fresh read of the notes."""
    validate_project(project)
    if not isinstance(data, dict) or not isinstance(data.get("ops"), list):
        raise ValueError("model output must contain an ops list")
    destinations = []
    if not dry:
        for source in files:
            destination = nf.within(PROCESSED, f"{project}/{source.name.removesuffix('.md')}")
            paths.check_draft_root(destination, VAULT)
            if (PROCESSED / project).is_symlink() or (PROCESSED / project / source.name).is_symlink():
                raise nf.UnsafePath("processed path must not use a symlink")
            destinations.append((source, destination))
    notes = load_notes()
    tips_only = project == UNKNOWN
    pool = [n for n in notes.values() if n["status"] == "active" and (n["type"] == "tip" or (not tips_only and n["project"] == project))]
    plan, newids = [], {}
    candidates = list(pool)
    def norm(op):
        for k in ("scene", "practice", "reason", "title", "slug", "id"):
            v = op.get(k)
            if isinstance(v, list): op[k] = "\n".join(f"- {x}" for x in v) if k == "practice" else "；".join(map(str, v))
            elif v is not None and not isinstance(v, str): op[k] = str(v)
            if op.get(k): op[k] = redact(op[k])
        for k in ("scene", "practice", "reason"):
            if op.get(k): op[k] = clean_field(op[k])
        for k in ("tags", "related", "sources"):
            v = op.get(k) or []
            v = v if isinstance(v, list) else [v]
            flat = []
            for x in v: flat += x if isinstance(x, list) else [x]
            op[k] = [redact(str(x)) for x in flat if x]
        return op
    for op in [norm(o) for o in data["ops"] if isinstance(o, dict)][:8]:
        if op.get("op") not in ("create", "update"):
            continue
        typ = op.get("type") if op.get("type") in ("decision", "lesson", "tip") else "lesson"
        if tips_only and typ != "tip": continue
        dup = None
        if op.get("op") == "update":
            nid = op.get("id")
            if nid not in notes or (before is not None and nid not in before):
                continue
            target = notes[nid]
            if target not in pool:
                continue
            typ = target["type"]
        else:
            if op.get("type") not in nf.NOTE_TYPES or any(
                not op.get(field, "").strip() or op[field].strip() == "（待补）"
                for field in ("title", "scene", "practice", "reason")
            ):
                log({"event": "rejected_op", "project": project, "reason": "incomplete_atomic_note"})
                continue
            best = max(((nf.similarity(op["title"], op["practice"], m), m["id"])
                        for m in candidates if m["type"] == typ), default=(0, None))
            if best[0] >= DEDUPE: dup = best[1]
            if dup:
                nid = dup; op["merged_by_dedupe"] = True
            else:
                slug = slugify(op.get("slug") or op.get("title", ""))
                base = f"tip/{slug}" if typ == "tip" else f"proj/{project}/{typ}/{slug}"
                nid, suffix = base, 2
                while nid in notes or any(nid == item[0] for item in plan):
                    nid, suffix = f"{base}-{suffix}", suffix + 1
                candidates.append({"id": nid, "type": typ, "title": op["title"], "practice": op["practice"]})
        newids["new:" + (op.get("slug") or "")] = nid
        plan.append((nid, typ, op))
    result, done, created = [], [], set()
    valid_related = set(notes) | {nid for nid, _, _ in plan}
    for nid, typ, op in plan:
        srcs = sorted({idx[s] for s in op.get("sources", []) if s in idx})
        rel = [newids.get(link, link) for link in op.get("related", [])]
        rel = [link for link in rel if link in valid_related and link != nid]
        done.append((nid, typ, op))
        if nid in notes:
            n = notes[nid]; action = "update"
            previous = (before or {}).get(nid)
            for field in ("scene", "practice", "reason"):
                if op.get(field) and (before is None or (previous and previous[field] == n[field])):
                    n[field] = op[field]
            n.update(sources=sorted(set(n["sources"]) | set(srcs)), updated=today())
            n["related"] = list(dict.fromkeys(n["related"] + rel))
            n["tags"] = list(dict.fromkeys(n["tags"] + op.get("tags", [])))
        else:
            action = "create"
            title = safe(op.get("title") or nid.rsplit("/", 1)[-1])
            path = f"技巧/{title}" if typ == "tip" else f"项目/{project}/{FOLDER[typ]}/{title}"
            n = nf.new_note(id=nid, path=new_path(path, notes), type=typ, project="" if typ == "tip" else project, tags=op.get("tags", []),
                            sources=srcs, related=rel, title=title, scene=op.get("scene", ""),
                            practice=op.get("practice", ""), reason=op.get("reason", ""), updated=today(), origin="batch-distill")
            notes[nid] = n
            created.add(nid)
        if op.get("merged_by_dedupe"): action = "update(dedupe)"
        result.append({"action": action, "id": nid, "title": n["title"], "sources": len(srcs)})
    # keep backlinks symmetric
    for nid, _, _ in done:
        for r in notes[nid]["related"]:
            if r in notes and nid not in notes[r]["related"]: notes[r]["related"].append(nid)
    if dry: return result
    touched = {nid for nid, _, _ in done} | {r for nid, _, _ in done for r in notes[nid]["related"]}
    for nid in sorted(touched):
        if nid in notes and notes[nid]["type"] in ("tip", "decision", "lesson"):
            write_file(notes[nid]["path"], render(notes[nid], notes), create=nid in created)
    for source, destination in destinations:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(source, destination)
    log({"event": "batch", "project": project, "drafts": len(files), "ops": result})
    return result

def drafts_of(project, d=None):
    validate_project(project)
    if not d:
        return draft_store.draft_files(DRAFTS, project)
    directory = pathlib.Path(d).expanduser()
    return sorted(path for path in directory.glob("*.md") if path.is_file() and not path.is_symlink())

@contextlib.contextmanager
def Lock():
    try:
        with nf.vault_lock(BASE / "batch.lock", timeout=0):
            yield
    except nf.VaultBusy:
        print("busy: another batch run holds a write lock", file=sys.stderr)
        sys.exit(75)

def run_project(project, max_batches):
    k = 0
    while k < max_batches and (files := drafts_of(project)):
        try: r = process(project, files[:BATCH]); print(project, json.dumps(r, ensure_ascii=False))
        except Exception as e: log({"event": "error", "project": project, "error": str(e)[:300]}); print("ERR", project, e); break
        k += 1
    return k


def cmd_run():
    check_draft_paths()
    with Lock():
        completed = sum(run_project(project, RUN_MAX_BATCHES) for project in draft_store.pending_projects(DRAFTS))
        if completed:
            rebuild_hubs()

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("run", "process", "rebuild-hubs")); ap.add_argument("arg", nargs="?")
    ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--dir"); ap.add_argument("--batch", type=int)
    a = ap.parse_args()
    if a.batch is not None:
        if a.batch <= 0: ap.error("--batch must be positive")
        BATCH = a.batch
    if a.cmd == "run": cmd_run()
    elif a.cmd == "rebuild-hubs": rebuild_hubs()
    elif a.cmd == "process":
        if not a.arg: ap.error("process requires a project")
        with Lock():
            files = drafts_of(a.arg, a.dir)
            res = [process(a.arg, files[index:index + BATCH], dry=a.dry_run) for index in range(0, len(files), BATCH)]
            if files and not a.dry_run: rebuild_hubs()
        print(json.dumps(res, ensure_ascii=False, indent=1))
