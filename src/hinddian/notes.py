"""Atomic Obsidian notes: load / upsert (4-state, gated) / routing export / correction queue / drafts.

Runs where the vault is (vault host, or any host with VAULT_ROOT). File format lives in note_format.py,
shared with the batch engine. Secrets are redacted on write.

Gate: callers on the agent channel (MCP / hooks) are untrusted — whatever flags they send,
decision notes (and anything that retires a decision) go to the correction queue. Only
decide_correction(), reached from the dashboard, writes with trusted=True.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
from typing import Any

from . import note_format as nf

VAULT = pathlib.Path(os.environ.get("VAULT_ROOT") or os.environ.get("HC_VAULT") or "/srv/obsidian/vault")
DRAFTS = pathlib.Path(os.environ.get("HB_DRAFTS") or "/var/lib/hinddian/drafts")
CORRECTIONS = pathlib.Path(os.environ.get("HB_CORRECTIONS") or "/var/lib/hinddian/agent_corrections")
ROUTING_CACHE = pathlib.Path(os.environ.get("HINDDIAN_ROUTING") or "/var/lib/hinddian/routing")
OWNER = os.environ.get("HC_OWNER", "obsidian")
UNKNOWN_PROJECT = "通用-未定"
HARD_DELETE_ACTIONS = {"delete", "remove", "purge", "hard_delete", "forget", "erase"}
SOFT_RETIRE_ACTIONS = {"obsolete", "retire", "archive"}
SUGGEST_MODES = {"suggest", "suggestion", "queue"}
_META_KEY = re.compile(r"^[a-z][a-z0-9_]{0,40}$")

_cache = nf.NoteCache()

# re-exported for callers / tests
redact = nf.redact
safe_title = nf.safe_title
slugify = nf.slugify


def configure(*, vault: str | os.PathLike | None = None) -> None:
    global VAULT
    if vault:
        VAULT = pathlib.Path(vault)


def today() -> str:
    return dt.date.today().isoformat()


def load_notes(*, include_inactive: bool = True) -> dict[str, dict]:
    notes = _cache.load(VAULT)
    if not include_inactive:
        notes = {k: n for k, n in notes.items() if n["status"] == "active"}
    return notes


def _write(n: dict, notes: dict[str, dict]) -> None:
    nf.write_note_file(VAULT, n["path"], nf.render(n, notes, today=today()), owner=OWNER)


def list_projects() -> list[str]:
    root = VAULT / "项目"
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith(("_", ".")))


def _readme(name: str) -> str:
    try:
        p = nf.within(VAULT, f"项目/{nf.safe_project(name)}/README")
    except nf.UnsafePath:
        return ""
    return p.read_text(encoding="utf-8", errors="ignore") if p.is_file() else ""


def routing_global() -> dict:
    notes = load_notes(include_inactive=False)
    projects = []
    for name in list_projects():
        blurb = ""
        t = _readme(name)
        if t:
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
            "写入：禁止 Hindsight retain。优先 hooks→草稿。"
            "门控 upsert：tip/preference/lesson 可直接 upsert_note；"
            "decision/架构定论一律进仪表盘「Agent 修正」由用户批准（Agent 侧无法绕过）；"
            "禁止硬删，只用 supersede/obsolete。"
        ),
    }


def routing_project(name: str) -> dict:
    name = nf.safe_project(name, "")
    notes = load_notes(include_inactive=False)
    state = ""
    m = re.search(r"## 当前状态\n(.*?)(?=\n## |\Z)", _readme(name), re.S) if name else None
    if m:
        state = m.group(1).strip()[:800]
    dec = sorted([n for n in notes.values() if n["project"] == name and n["type"] == "decision"], key=lambda n: n["title"])
    les = sorted([n for n in notes.values() if n["project"] == name and n["type"] == "lesson"], key=lambda n: n["title"])
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
        "related": [r for r in n["related"] if r in notes],
        "supersedes": [r for r in n["supersedes"] if r in notes],
        "superseded_by": n["superseded_by"] if n["superseded_by"] in notes else "",
        "tags": n["tags"],
        "updated": n["updated"],
        "text": n["text"],
    }


def _summary(n: dict) -> dict:
    return {"id": n["id"], "title": n["title"], "type": n["type"], "project": n["project"], "status": n["status"], "path": n["path"]}


def _match(n: dict, project: str | None, type_: str | None, status: str) -> bool:
    if status != "all" and n["status"] != status:
        return False
    if project and n["project"] != project and not (project == "global" and n["type"] == "tip"):
        return False
    return not (type_ and n["type"] != type_)


def list_notes(*, project: str | None = None, type_: str | None = None, status: str = "active", limit: int = 50) -> list[dict]:
    notes = load_notes(include_inactive=(status != "active"))
    out = sorted((_summary(n) for n in notes.values() if _match(n, project, type_, status)), key=lambda x: x["title"])
    return out[: max(0, int(limit))]


def search_notes(query: str, *, project: str | None = None, type_: str | None = None, limit: int = 12) -> list[dict]:
    """Local recall fallback: bigram score over title + body (Chinese-safe). Like Hindsight recall,
    a project search without a type also covers the global tips."""
    notes = load_notes(include_inactive=False)
    scored = []
    for n in notes.values():
        if not (_match(n, project, type_, "active") or (project and not type_ and n["type"] == "tip")):
            continue
        s = nf.score(query, n)
        if s > 0:
            scored.append({**_summary(n), "score": round(s, 3), "scene": n["scene"][:300], "practice": n["practice"][:600]})
    scored.sort(key=lambda x: -x["score"])
    return scored[: max(0, int(limit))]


# ------------------------------------------------------------------ gate
def _norm_type(raw: str | None) -> tuple[str, list[str]]:
    """Map preference→tip+tag; unknown→lesson."""
    t = (raw or "lesson").strip().lower()
    if t in ("preference", "pref", "prefs"):
        return "tip", ["preference"]
    if t not in nf.NOTE_TYPES:
        return "lesson", []
    return t, []


def _needs_review(typ: str, *, target: str, supersedes: list[str], notes: dict, mode: str) -> bool:
    """Untrusted (agent) writes that must wait for a human in the dashboard."""
    if mode in SUGGEST_MODES or typ == "decision":
        return True
    if target in notes and notes[target]["type"] == "decision":
        return True
    return any(notes.get(o, {}).get("type") == "decision" for o in supersedes)


def _untrusted(payload: dict) -> dict:
    """Agent payloads can't carry server-side flags (e.g. `_from_dashboard`)."""
    return {k: v for k, v in (payload or {}).items() if not str(k).startswith("_")}


def _str_list(v: Any) -> list[str]:
    if v is None:
        return []
    v = v if isinstance(v, list) else [v]
    return [str(x) for x in v if str(x).strip()]


def enqueue_correction(payload: dict) -> dict:
    """Queue an Agent correction for dashboard approval (no silent decision write)."""
    payload = _untrusted(payload)
    CORRECTIONS.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now()
    title = safe_title(payload.get("title") or payload.get("id") or "correction")
    cid = f"ac-{now.strftime('%Y%m%d-%H%M%S')}-{now.microsecond:06d}-{slugify(title)[:24]}"
    clean = {
        k: payload[k]
        for k in (
            "action", "verdict", "id", "target_id", "type", "project", "title", "slug",
            "scene", "practice", "reason", "supersedes", "tags", "sources", "related",
            "origin", "correction_reason",
        )
        if k in payload and payload[k] is not None
    }
    clean["action"] = str(clean.get("action") or clean.get("verdict") or "update").lower()
    doc = {
        "id": cid,
        "status": "pending",
        "created_at": now.isoformat(timespec="seconds"),
        "kind": "agent_correction",
        "summary": title,
        "type": clean.get("type") or "",
        "project": clean.get("project") or "",
        "action": clean["action"],
        "target_id": clean.get("id") or clean.get("target_id") or "",
        "reason": str(payload.get("correction_reason") or payload.get("reason") or "")[:500],
        # What the agent claimed — shown to the human, never trusted.
        "agent_claims": {
            "user_confirmed": bool(payload.get("user_confirmed")),
            "face_correction": bool(payload.get("face_correction")),
        },
        "payload": clean,
    }
    path = CORRECTIONS / f"{cid}.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o664)
    except OSError:
        pass
    return {
        "ok": True,
        "action": "suggested",
        "queued": True,
        "suggestion_id": cid,
        "hint": "decision/架构类已入仪表盘「Agent 修正」队列；用户在仪表盘批准后才写 Obsidian。",
    }


def list_corrections(*, status: str = "pending", limit: int = 50) -> list[dict]:
    if not CORRECTIONS.is_dir():
        return []
    out: list[dict] = []
    for p in sorted(CORRECTIONS.glob("ac-*.json"), reverse=True):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if status != "all" and doc.get("status") != status:
            continue
        out.append(doc)
        if len(out) >= limit:
            break
    return out


def decide_correction(cid: str, *, approve: bool, reason: str = "") -> dict:
    """Dashboard-only: the one trusted write path."""
    cid = "".join(c for c in (cid or "") if c.isalnum() or c in "-_")
    path = CORRECTIONS / f"{cid}.json"
    with nf.vault_lock():
        if not path.is_file():
            return {"ok": False, "error": "not_found", "id": cid}
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("status") != "pending":
            return {"ok": False, "error": "not_pending", "status": doc.get("status"), "id": cid}
        stamp = dt.datetime.now().isoformat(timespec="seconds")
        if approve:
            result = upsert_note(dict(doc.get("payload") or {}), trusted=True)
            doc["status"] = "applied" if result.get("ok") else "failed"
            doc["applied_at"] = stamp
            doc["apply_result"] = result
        else:
            result = None
            doc["status"] = "rejected"
            doc["rejected_at"] = stamp
            doc["reject_reason"] = (reason or "")[:300]
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    if approve:
        return {"ok": bool(result.get("ok")), "id": cid, "status": doc["status"], "result": result}
    return {"ok": True, "id": cid, "status": "rejected"}


def _new_id(base: str, notes: dict) -> str:
    nid, k = base, 2
    while nid in notes:
        nid = f"{base}-{k}"
        k += 1
    return nid


def _new_path(base: str, notes: dict) -> str:
    taken = {n["path"] for n in notes.values()}
    path, k = base, 2
    while path in taken or nf.within(VAULT, path).exists():
        path = f"{base}-{k}"
        k += 1
    return path


DEDUPE = float(os.environ.get("HINDDIAN_DEDUPE", "0.40"))  # same scale as the batch engine's HB_DEDUPE


def _similar(title: str, practice: str, typ: str, project: str, notes: dict, k: int = 3) -> list[dict]:
    """Active notes of the same type (and project, unless tip) that look like the same topic."""
    pool = [n for n in notes.values() if n["status"] == "active" and n["type"] == typ and (typ == "tip" or n["project"] == project)]
    scored = sorted(((nf.similarity(title, practice, n), n) for n in pool), key=lambda x: -x[0])
    return [{"id": n["id"], "title": n["title"], "score": round(sc, 2)} for sc, n in scored[:k] if sc >= DEDUPE]


def upsert_note(payload: dict, *, trusted: bool = False) -> dict:
    """Gated 4-state write: add | update | supersede | obsolete | noop.  No hard delete.

    trusted=False (agent channel): tip / preference / lesson write directly; anything that
    creates, changes or retires a decision is queued for the dashboard.
    """
    if not trusted:
        payload = _untrusted(payload)
    action = str(payload.get("action") or payload.get("verdict") or "add").lower()
    if action in HARD_DELETE_ACTIONS:
        return {
            "ok": False,
            "error": "hard_delete_forbidden",
            "hint": "Use action=supersede (with supersedes=[old_id]) or action=obsolete. Never delete.",
        }
    if action in ("noop", "ignore"):
        return {"ok": True, "action": "noop", "reason": payload.get("reason", "noop")}
    if action == "create":
        action = "add"
    if action in SOFT_RETIRE_ACTIONS:
        action = "obsolete"
    if action not in ("add", "update", "supersede", "obsolete"):
        return {"ok": False, "error": f"unknown action {action}"}

    with nf.vault_lock():
        notes = load_notes(include_inactive=True)
        typ, extra_tags = _norm_type(payload.get("type"))
        target_id = str(payload.get("id") or payload.get("target_id") or "")
        target = notes.get(target_id)
        if action in ("update", "obsolete") and target:
            typ = target["type"] or typ  # a note's type can't be changed by relabeling the payload
        tags = list(dict.fromkeys(_str_list(payload.get("tags")) + extra_tags))
        project = "" if typ == "tip" else nf.safe_project(payload.get("project") or (target or {}).get("project"))
        title = safe_title(payload.get("title") or (target or {}).get("title") or "未命名")
        supersedes = [s for s in _str_list(payload.get("supersedes")) if s in notes]
        fields = {k: nf.guard_field(nf.unwiki(str(payload.get(k) or ""))) for k in ("scene", "practice", "reason")}
        mode = str(payload.get("mode") or "").strip().lower()

        if action == "obsolete" and not target:
            return {"ok": False, "error": "obsolete_needs_id", "hint": "Pass id of note to mark obsolete"}
        if action == "add" and not trusted and not payload.get("force_new"):
            similar = _similar(title, fields["practice"], typ, project, notes)
            if similar:
                return {
                    "ok": False,
                    "error": "similar_exists",
                    "candidates": similar,
                    "hint": "已有相近笔记：要补充就用 action=update + id 合并；确是新主题再带 force_new=true 重试。",
                }
        if not trusted and _needs_review(typ, target=target_id, supersedes=supersedes, notes=notes, mode=mode):
            pl = dict(payload, type=typ, tags=tags, project=project, title=title, action=action, supersedes=supersedes)
            if target_id:
                pl["id"] = target_id
            return enqueue_correction(pl)

        origin = str(payload.get("origin") or "upsert")[:80]
        gated = "dashboard" if trusted else "auto"

        if action == "obsolete":
            target["status"] = "obsolete"
            target["updated"] = today()
            _write(target, notes)
            return {"ok": True, "action": "obsolete", "id": target_id, "path": target["path"], "gated": gated}

        if action == "update" and not target:
            action = "add"

        related = [r for r in _str_list(payload.get("related")) if r in notes]
        sources = _str_list(payload.get("sources"))

        if action == "update":
            n = target
            for k, v in fields.items():
                if v:
                    n[k] = v
            n["updated"] = today()
            n["origin"] = str(payload.get("origin") or n.get("origin") or "upsert")[:80]
            n["tags"] = list(dict.fromkeys(n["tags"] + tags))
            n["sources"] = list(dict.fromkeys(n["sources"] + sources))
            n["related"] = list(dict.fromkeys(n["related"] + [r for r in related if r != n["id"]]))
            _write(n, notes)
            return {"ok": True, "action": "update", "id": n["id"], "path": n["path"], "gated": gated}

        slug = slugify(payload.get("slug") or title)
        base_id = f"tip/{slug}" if typ == "tip" else f"proj/{project}/{typ}/{slug}"
        if action == "add" and target_id and target_id not in notes and trusted:
            base_id = target_id
        nid = _new_id(base_id, notes)
        base_path = f"技巧/{title}" if typ == "tip" else f"项目/{project}/{nf.FOLDER[typ]}/{title}"
        try:
            path = _new_path(base_path, notes)
        except nf.UnsafePath as e:
            return {"ok": False, "error": "unsafe_path", "detail": str(e)}
        n = nf.new_note(
            id=nid, path=path, type=typ, project=project, tags=tags, sources=sources,
            related=[r for r in related if r != nid], title=title, updated=today(), origin=origin, **fields,
        )
        notes[nid] = n
        if action == "supersede":
            for old in supersedes:
                if old == nid:
                    continue
                notes[old]["status"] = "superseded"
                notes[old]["superseded_by"] = nid
                notes[old]["updated"] = today()
                n["supersedes"].append(old)
        _write(n, notes)
        for old in n["supersedes"]:
            _write(notes[old], notes)
        return {"ok": True, "action": action, "id": nid, "path": path, "gated": gated}


# ------------------------------------------------------------------ drafts
def push_draft(*, project: str, title: str, body: str, meta: dict | None = None) -> dict:
    """Write one draft file. With meta.session_id, upsert the same session draft (threshold counts sessions)."""
    project = nf.safe_project(project)
    if project == "holdout":  # never write into holdout from hooks
        project = UNKNOWN_PROJECT
    d = DRAFTS / project
    meta = dict(meta or {})
    sid = str(meta.get("session_id") or "").strip()
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = slugify(title)[:40] or "session"
    if sid:
        safe_sid = "".join(c if c.isalnum() or c in "-_" else "_" for c in sid)[:80]
        name = f"session-{safe_sid}"
    else:
        name = f"{ts}-{slug}"
    path = nf.within(DRAFTS, f"{project}/{name}")
    d.mkdir(parents=True, exist_ok=True)
    origin = meta.get("origin") or ("session-finalize" if sid else "turn-end")
    items: list[tuple[str, Any]] = [
        ("title", safe_title(title)),
        ("project", project),
        ("origin", str(origin)[:120]),
        ("created", today()),
        ("updated", today()),
    ]
    for k, v in meta.items():
        if k in ("title", "project", "body", "origin", "created", "updated") or not _META_KEY.match(str(k)):
            continue
        if isinstance(v, (str, int, float, bool)):
            items.append((k, str(v)[:200]))
    text = redact(nf.dump_frontmatter(items) + "\n\n# " + safe_title(title) + "\n\n" + (body or "").strip() + "\n")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return {
        "ok": True,
        "path": str(path),
        "project": project,
        "session_id": sid or None,
        "jev_source": meta.get("jev_source"),
        "upsert": bool(sid),
    }
