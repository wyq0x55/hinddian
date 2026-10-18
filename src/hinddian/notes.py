"""Atomic Obsidian notes: load / render / upsert (4-state) / routing export.

Works when VAULT_ROOT points at the vault (DMIT). Secrets are redacted on write.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import shutil
from typing import Any

VAULT = pathlib.Path(os.environ.get("VAULT_ROOT") or os.environ.get("HC_VAULT") or "/srv/obsidian/vault")
DRAFTS = pathlib.Path(os.environ.get("HB_DRAFTS") or "/var/lib/hinddian/drafts")
ROUTING_CACHE = pathlib.Path(os.environ.get("HINDDIAN_ROUTING") or "/var/lib/hinddian/routing")
OWNER = os.environ.get("HC_OWNER", "obsidian")
FOLDER = {"decision": "决策", "lesson": "经验"}
SECRET_RE = [
    re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key|bearer)\s*[:=]\s*['\"]?[A-Za-z0-9_\-\.]{12,}"),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(ghp|gho|github_pat)_[A-Za-z0-9_]{20,}"),
]
WIKI = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def today() -> str:
    return dt.date.today().isoformat()


def redact(t: str) -> str:
    for r in SECRET_RE:
        t = r.sub("[REDACTED]", t)
    return t


def safe_title(t: str) -> str:
    return re.sub(r'[\\/:*?"<>|#\[\]^]', "-", t).strip()[:80]


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:60] or "note"


def parse_note(p: pathlib.Path) -> dict | None:
    t = p.read_text(errors="ignore")
    if not t.startswith("---\n"):
        return None
    end = t.find("\n---\n", 4)
    if end < 0:
        return None
    fm: dict[str, str] = {}
    for line in t[4:end].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    if "id" not in fm:
        return None
    body = t[end + 5 :]
    sec = dict(re.findall(r"^## (.+?)\n(.*?)(?=^## |\Z)", body, re.M | re.S))
    title_m = re.search(r"^# (.+)$", body, re.M)
    title = title_m.group(1) if title_m else p.stem

    def lst(v: str | None) -> list[str]:
        v = (v or "").strip()
        links = re.findall(r"\[\[[^\]]+\]\]", v)
        if links:
            return links
        return [x.strip().strip('"') for x in v.strip("[]").split(",") if x.strip().strip('"')]

    try:
        rel = str(p.relative_to(VAULT))[:-3]
    except ValueError:
        rel = str(p)
    return {
        "path": rel,
        "id": fm["id"],
        "type": fm.get("type", ""),
        "project": fm.get("project", ""),
        "tags": lst(fm.get("tags")),
        "status": fm.get("status", "active"),
        "sources": lst(fm.get("sources")),
        "related_raw": lst(fm.get("related")),
        "supersedes_raw": lst(fm.get("supersedes")),
        "legacy_code": fm.get("legacy_code", ""),
        "origin": fm.get("origin", ""),
        "updated": fm.get("updated", ""),
        "title": title,
        "scene": sec.get("场景", "").strip(),
        "practice": sec.get("做法", "").strip(),
        "reason": sec.get("理由", "").strip(),
        "text": t,
    }


def load_notes(*, include_inactive: bool = True) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not VAULT.is_dir():
        return out
    for p in VAULT.rglob("*.md"):
        if any(x in p.parts for x in (".obsidian", "_归档", ".git", ".trash", "_模板")):
            continue
        n = parse_note(p)
        if not n:
            continue
        if not include_inactive and n["status"] != "active":
            continue
        out[n["id"]] = n
    return out


def link_of(n: dict) -> str:
    return f"[[{n['path']}|{n['title']}]]"


def unwiki(t: str) -> str:
    return WIKI.sub(lambda m: f"`{m.group(2) or m.group(1)}`", t or "")


def render(n: dict, notes: dict[str, dict]) -> str:
    def links(ids: list[str]) -> list[str]:
        return [link_of(notes[i]) for i in ids if i in notes]

    fm = [
        "---",
        f"id: {n['id']}",
        f"type: {n['type']}",
        f"project: {n['project'] or 'global'}",
        "tags: [" + ", ".join(n.get("tags") or []) + "]",
        f"status: {n.get('status', 'active')}",
        "supersedes: [" + ", ".join(f'"{l}"' for l in links(n.get("supersedes") or [])) + "]",
        "related: [" + ", ".join(f'"{l}"' for l in links(n.get("related") or [])) + "]",
        "sources: [" + ", ".join(n.get("sources") or []) + "]",
        f"updated: {n.get('updated') or today()}",
    ]
    if n.get("legacy_code"):
        fm.append(f"legacy_code: {n['legacy_code']}")
    if n.get("origin"):
        fm.append(f"origin: {n['origin']}")
    fm.append("---")
    hub = f"[[项目/{n['project']}/README|{n['project']}]]" if n.get("type") != "tip" else "[[技巧/技巧|agent使用技巧]]"
    b = [f"# {n['title']}", "", f"> 所属：{hub}" + (f" · 归纳自 {len(n.get('sources') or [])} 个会话" if n.get("sources") else "")]
    if n.get("status") == "superseded" and n.get("superseded_by") in notes:
        b.append(f"> ⚠️ 已被 {link_of(notes[n['superseded_by']])} 取代")
    b += [
        "",
        "## 场景",
        unwiki(n.get("scene") or "") or "（待补）",
        "",
        "## 做法",
        unwiki(n.get("practice") or "") or "（待补）",
        "",
        "## 理由",
        unwiki(n.get("reason") or "") or "（待补）",
        "",
    ]
    if n.get("supersedes"):
        b += ["## 取代", *[f"- {l}" for l in links(n["supersedes"])], ""]
    if n.get("related"):
        b += ["## 相关", *[f"- {l}" for l in links(n["related"])], ""]
    return redact("\n".join(fm + b))


def write_file(rel: str, text: str) -> pathlib.Path:
    p = VAULT / (rel + ".md")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".md.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)
    try:
        shutil.chown(p, OWNER, OWNER)
        os.chmod(p, 0o664)
    except Exception:
        pass
    return p


def list_projects() -> list[str]:
    root = VAULT / "项目"
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith(("_", ".")))


def routing_global() -> dict:
    notes = load_notes(include_inactive=False)
    projects = []
    for name in list_projects():
        readme = VAULT / "项目" / name / "README.md"
        blurb = ""
        if readme.exists():
            t = readme.read_text(errors="ignore")
            m = re.search(r"^# .+\n+(?:> .+\n+)?([^#\n][^\n]{0,120})", t, re.M)
            if m:
                blurb = m.group(1).strip()
            st = re.search(r"## 当前状态\n(.*?)(?=\n## |\Z)", t, re.S)
            if st:
                blurb = (blurb + " | " + re.sub(r"\s+", " ", st.group(1)).strip()[:100]).strip(" |")
        n_dec = sum(1 for n in notes.values() if n["project"] == name and n["type"] == "decision")
        n_les = sum(1 for n in notes.values() if n["project"] == name and n["type"] == "lesson")
        projects.append(
            {
                "name": name,
                "id": f"proj/{name}/readme",
                "blurb": blurb[:160],
                "decisions": n_dec,
                "lessons": n_les,
                "when_to_recall": f"任务涉及 {name} 仓库/代码/决策时先 routing_project 再按需 recall",
            }
        )
    tips = sum(1 for n in notes.values() if n["type"] == "tip")
    return {
        "version": 1,
        "updated": today(),
        "tips": {"id": "topic/agent-usage-tips", "count": tips, "path": "技巧/技巧"},
        "projects": projects,
        "guidance": (
            "稳定前缀：本路由表。易变 recall 结果放对话后部。"
            "先 match 项目；再看项目路由的 when_to_recall；不需要就跳过。"
            "写入只走 upsert_note / 流水线，禁止 Hindsight retain。"
        ),
    }


def routing_project(name: str) -> dict:
    notes = load_notes(include_inactive=False)
    readme = VAULT / "项目" / name / "README.md"
    state = ""
    if readme.exists():
        t = readme.read_text(errors="ignore")
        m = re.search(r"## 当前状态\n(.*?)(?=\n## |\Z)", t, re.S)
        if m:
            state = m.group(1).strip()[:800]
    dec = sorted(
        [n for n in notes.values() if n["project"] == name and n["type"] == "decision"],
        key=lambda n: n["title"],
    )
    les = sorted(
        [n for n in notes.values() if n["project"] == name and n["type"] == "lesson"],
        key=lambda n: n["title"],
    )
    return {
        "project": name,
        "readme_id": f"proj/{name}/readme",
        "current_state": state or "（待补）",
        "when_to_recall": (
            f"涉及 {name} 架构、门禁、测试、部署或已知坑时调用 recall(project={name})；"
            "纯寒暄/无关任务可跳过。默认只召回 status=active。"
        ),
        "decisions": [{"id": n["id"], "title": n["title"]} for n in dec[:40]],
        "lessons": [{"id": n["id"], "title": n["title"]} for n in les[:40]],
        "decision_count": len(dec),
        "lesson_count": len(les),
    }


def export_routing() -> dict:
    ROUTING_CACHE.mkdir(parents=True, exist_ok=True)
    g = routing_global()
    (ROUTING_CACHE / "global.json").write_text(json.dumps(g, ensure_ascii=False, indent=2), encoding="utf-8")
    projects = {}
    for p in g["projects"]:
        rp = routing_project(p["name"])
        projects[p["name"]] = rp
        safe = slugify(p["name"]) or "p"
        (ROUTING_CACHE / f"project-{safe}.json").write_text(json.dumps(rp, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROUTING_CACHE / "projects.json").write_text(json.dumps(projects, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "projects": len(projects), "path": str(ROUTING_CACHE)}


def get_note(note_id: str) -> dict | None:
    notes = load_notes(include_inactive=True)
    n = notes.get(note_id)
    if not n:
        return None
    related = []
    for raw in n.get("related_raw") or []:
        m = re.match(r"\[\[([^\]|]+)", raw)
        related.append(m.group(1) if m else raw)
    return {
        "id": n["id"],
        "path": n["path"],
        "type": n["type"],
        "project": n["project"],
        "status": n["status"],
        "title": n["title"],
        "scene": n["scene"],
        "practice": n["practice"],
        "reason": n["reason"],
        "related": related,
        "tags": n["tags"],
        "updated": n["updated"],
        "text": n["text"],
    }


def list_notes(*, project: str | None = None, type_: str | None = None, status: str = "active", limit: int = 50) -> list[dict]:
    notes = load_notes(include_inactive=(status != "active"))
    out = []
    for n in notes.values():
        if status != "all" and n["status"] != status:
            continue
        if project and n["project"] != project and not (project == "global" and n["type"] == "tip"):
            continue
        if type_ and n["type"] != type_:
            continue
        out.append({"id": n["id"], "title": n["title"], "type": n["type"], "project": n["project"], "status": n["status"], "path": n["path"]})
        if len(out) >= limit:
            break
    return sorted(out, key=lambda x: x["title"])


def upsert_note(payload: dict) -> dict:
    """4-state write. payload: action/add|update|supersede|noop, id?, type, project, title, scene, practice, reason, supersedes?, tags?, sources?"""
    action = (payload.get("action") or payload.get("verdict") or "add").lower()
    if action in ("noop", "ignore"):
        return {"ok": True, "action": "noop", "reason": payload.get("reason", "noop")}
    notes = load_notes(include_inactive=True)
    typ = payload.get("type") if payload.get("type") in ("decision", "lesson", "tip") else "lesson"
    project = (payload.get("project") or "").strip()
    if typ != "tip" and not project:
        project = "通用-未定"
    title = safe_title(payload.get("title") or "未命名")
    slug = slugify(payload.get("slug") or title)
    target_id = payload.get("id") or payload.get("target_id") or ""
    supersedes = list(payload.get("supersedes") or [])

    if action == "update":
        if target_id not in notes:
            action = "add"
        else:
            n = notes[target_id]
            n.update(
                scene=payload.get("scene") or n["scene"],
                practice=payload.get("practice") or n["practice"],
                reason=payload.get("reason") or n["reason"],
                updated=today(),
                origin=payload.get("origin") or n.get("origin") or "upsert",
            )
            if payload.get("tags"):
                n["tags"] = list(dict.fromkeys((n.get("tags") or []) + list(payload["tags"])))
            if payload.get("sources"):
                n["sources"] = list(dict.fromkeys((n.get("sources") or []) + list(payload["sources"])))
            n["related"] = n.get("related") or []
            n["supersedes"] = n.get("supersedes") or []
            write_file(n["path"], render(n, notes))
            return {"ok": True, "action": "update", "id": target_id, "path": n["path"]}

    if action in ("add", "create", "supersede"):
        nid = target_id if target_id and action != "supersede" else (
            f"tip/{slug}" if typ == "tip" else f"proj/{project}/{typ}/{slug}"
        )
        if action == "supersede" or nid in notes:
            # new id for supersede
            if action == "supersede" or nid in notes:
                nid = f"tip/{slug}" if typ == "tip" else f"proj/{project}/{typ}/{slug}"
                if nid in notes:
                    nid = nid + "-" + today().replace("-", "")[4:]
        path = f"技巧/{title}" if typ == "tip" else f"项目/{project}/{FOLDER[typ]}/{title}"
        if any(x["path"] == path for x in notes.values()):
            path += f"-{nid.rsplit('/', 1)[-1][:12]}"
        n = {
            "id": nid,
            "path": path,
            "type": typ,
            "project": "" if typ == "tip" else project,
            "tags": list(payload.get("tags") or []),
            "status": "active",
            "sources": list(payload.get("sources") or []),
            "related": list(payload.get("related") or []),
            "supersedes": [],
            "title": title,
            "scene": payload.get("scene") or "",
            "practice": payload.get("practice") or "",
            "reason": payload.get("reason") or "",
            "updated": today(),
            "origin": payload.get("origin") or "upsert",
        }
        notes[nid] = n
        if action == "supersede":
            for old in supersedes:
                if old in notes and old != nid:
                    notes[old]["status"] = "superseded"
                    notes[old]["superseded_by"] = nid
                    if old not in n["supersedes"]:
                        n["supersedes"].append(old)
                    write_file(notes[old]["path"], render(notes[old], notes))
        write_file(path, render(n, notes))
        return {"ok": True, "action": action if action != "create" else "add", "id": nid, "path": path}

    return {"ok": False, "error": f"unknown action {action}"}


def push_draft(*, project: str, title: str, body: str, meta: dict | None = None) -> dict:
    """Write one draft file. With meta.session_id, upsert the same session draft (threshold counts sessions)."""
    project = (project or "通用-未定").strip() or "通用-未定"
    # never write into holdout from hooks
    if project == "holdout":
        project = "通用-未定"
    d = DRAFTS / project
    d.mkdir(parents=True, exist_ok=True)
    meta = dict(meta or {})
    sid = str(meta.get("session_id") or "").strip()
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = slugify(title)[:40] or "session"
    if sid:
        safe_sid = "".join(c if c.isalnum() or c in "-_" else "_" for c in sid)[:80]
        path = d / f"session-{safe_sid}.md"
    else:
        path = d / f"{ts}-{slug}.md"
    origin = meta.get("origin") or ("session-finalize" if sid else "turn-end")
    fm = [
        "---",
        f"title: {safe_title(title)}",
        f"project: {project}",
        f"origin: {origin}",
        f"created: {today()}",
        f"updated: {today()}",
    ]
    for k, v in meta.items():
        if k in ("title", "project", "body", "origin"):
            continue
        if isinstance(v, (str, int, float, bool)):
            fm.append(f"{k}: {v}")
    fm.append("---")
    text = redact("\n".join(fm) + "\n\n# " + safe_title(title) + "\n\n" + (body or "").strip() + "\n")
    path.write_text(text, encoding="utf-8")
    return {
        "ok": True,
        "path": str(path),
        "project": project,
        "session_id": sid or None,
        "jev_source": meta.get("jev_source"),
        "upsert": bool(sid),
    }
