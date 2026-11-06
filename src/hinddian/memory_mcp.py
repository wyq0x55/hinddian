"""hinddian-memory MCP (HTTP JSON-RPC) + REST helpers for host hooks — the *agent channel*.

Tools: routing_global, routing_project, recall, timeline, get_note, upsert_note, suggest_correction, list_notes, push_draft
Transport: HTTP POST /mcp (JSON-RPC). REST under /api/memory/* for host lifecycle hooks.
Auth: Bearer HINDDIAN_MCP_TOKEN. Nothing here can approve a correction — that lives on the
dashboard channel (api.py, AUTH_TOKEN).
Vault ops run locally if VAULT_ROOT exists, else via SSH to CLASSIFY_SSH_HOST (vault host).
"""
from __future__ import annotations

import hmac
import json
import shlex
import subprocess
import threading
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

from . import __version__, index_sync, jev, jev_log, session_finalize
from .config import get_settings

router = APIRouter()

TOOLS = [
    {
        "name": "routing_global",
        "description": "Global memory routing table: projects, tip count, when to recall. Call at session start; keep as stable prefix.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "routing_project",
        "description": "Project memory map: current state and decision/lesson titles grouped by type, with ids and updated dates. Expand only relevant notes with get_note.",
        "inputSchema": {
            "type": "object",
            "properties": {"project": {"type": "string", "description": "Project folder name"}},
            "required": ["project"],
        },
    },
    {
        "name": "recall",
        "description": "Search active notes via Hindsight (vault local fallback). Returns a compact id/title/type/date/score index verified against current vault files; date is updated. Use timeline for context and get_note for details. format=full includes current vault text.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "project": {"type": "string"},
                "type": {"type": "string", "description": "decision|lesson|tip"},
                "budget": {"type": "string", "description": "low|mid|high", "default": "mid"},
                "format": {"type": "string", "enum": ["index", "full"], "default": "index"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_note",
        "description": "Fetch current vault full text, links, status and updated. A string id returns one note; an array of up to 20 ids returns a list in request order, including not_found entries.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 20}]}},
            "required": ["id"],
        },
    },
    {
        "name": "timeline",
        "description": "Active notes adjacent in updated-date order in the anchor's exact project, including the anchor (even if retired). Ties sort by id; undated neighbors are omitted.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "anchor_id": {"type": "string"},
                "before": {"type": "integer", "minimum": 0, "maximum": 20, "default": 3},
                "after": {"type": "integer", "minimum": 0, "maximum": 20, "default": 3},
            },
            "required": ["anchor_id"],
        },
    },
    {
        "name": "list_notes",
        "description": "List notes by project/type/status (default status=active).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "type": {"type": "string"},
                "status": {"type": "string", "default": "active"},
                "limit": {"type": "integer", "default": 50},
                "order": {"type": "string", "enum": ["title", "recent"], "default": "title"},
            },
        },
    },
    {
        "name": "upsert_note",
        "description": (
            "Direct write to Obsidian (SoT), including decision. Actions: add|update|supersede|noop|obsolete. "
            "No dashboard approval required. Use a proposition as title and fill scene/practice/reason "
            "plus project for project notes; updates can reuse existing fields. "
            "Hard delete forbidden — use supersede or obsolete. Never Hindsight retain. No secrets."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "add|update|supersede|noop|obsolete (not delete)"},
                "id": {"type": "string"},
                "type": {"type": "string", "description": "decision|lesson|tip|preference"},
                "project": {"type": "string"},
                "title": {"type": "string", "description": "Proposition; required for add/supersede, optional for update/obsolete"},
                "slug": {"type": "string"},
                "scene": {"type": "string"},
                "practice": {"type": "string"},
                "reason": {"type": "string"},
                "supersedes": {"type": "array", "items": {"type": "string"}},
                "related": {"type": "array", "items": {"type": "string"}},
                "tags": {"type": "array", "items": {"type": "string"}},
                "sources": {"type": "array", "items": {"type": "string"}},
                "auto_verdict": {"type": "boolean", "description": "Let Jev pick add/update/supersede/noop against existing notes"},
                "force_new": {"type": "boolean", "description": "add only: write even though similar notes exist (an add that looks like a duplicate returns similar_exists + candidates)"},
                "face_correction": {"type": "boolean", "description": "Legacy context flag; does not change the direct write path"},
                "user_confirmed": {"type": "boolean", "description": "Legacy context flag; no approval needed"},
                "mode": {"type": "string", "description": "Legacy flag; all modes use direct writes"},
                "correction_reason": {"type": "string"},
            },
        },
    },
    {
        "name": "suggest_correction",
        "description": (
            "Apply a memory correction directly to Obsidian, including decision/architecture. "
            "Same actions and atomic-note contract as upsert_note; no pending queue. "
            "Use when the user corrects memory or you discover a wrong/outdated note. "
            "Never use push_draft for corrections."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "update|supersede|obsolete|add"},
                "id": {"type": "string"},
                "type": {"type": "string"},
                "project": {"type": "string"},
                "title": {"type": "string"},
                "scene": {"type": "string"},
                "practice": {"type": "string"},
                "reason": {"type": "string"},
                "supersedes": {"type": "array", "items": {"type": "string"}},
                "tags": {"type": "array", "items": {"type": "string"}},
                "correction_reason": {"type": "string"},
            },
        },
    },
    {
        "name": "push_draft",
        "description": (
            "Hooks/session-finalize only: push one session transcript draft into drafts/<project>/ "
            "(session_id upserts same file; batch may distill later). "
            "Do NOT call for remember/correct/update — use upsert_note or suggest_correction. "
            "push_draft does not enter the Agent 修正 queue and is not a review path for corrections."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "title": {"type": "string"},
                "body": {"type": "string"},
                "type": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["title", "body"],
        },
    },
]

DRAFT_META_KEYS = ("type", "confidence", "origin", "session_id", "jev_source", "turn_count", "finalize_reason")


# ------------------------------------------------------------------ vault backend
def _notes_mod():
    from . import notes

    notes.configure(vault=get_settings().vault_root)
    return notes


def _ssh_cli(args: list[str], payload: dict | None = None) -> Any:
    """Call /usr/local/bin/hinddian-memory-cli on the vault host; return JSON. Payload via stdin.
    ControlMaster keeps one SSH connection warm instead of a handshake per tool call."""
    s = get_settings()
    remote = "/usr/local/bin/hinddian-memory-cli " + " ".join(shlex.quote(a) for a in args)
    cmd = [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
        "-o", "ControlMaster=auto", "-o", f"ControlPath={s.ssh_control_path}", "-o", "ControlPersist=600",
        s.classify_ssh_host, remote,
    ]
    stdin = json.dumps(payload, ensure_ascii=False) if payload is not None else None
    try:
        p = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("vault host timeout") from e
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "ssh failed")[:400])
    lines = (p.stdout or "").strip().splitlines()
    if not lines:
        raise RuntimeError("vault host returned nothing")
    return json.loads(lines[-1])


def vault(op: str, **kw: Any) -> Any:
    result = _vault(op, **kw)
    if (isinstance(result, dict) and result.get("ok")
            and ((op in ("upsert_note", "suggest_correction") and result.get("action") != "noop")
                 or (op == "decide_correction" and result.get("status") == "applied"))):
        index_sync.kick()
    return result


def _vault(op: str, **kw: Any) -> Any:
    """Run one vault op locally (VAULT_ROOT mounted) or on the vault host via the memory CLI."""
    if get_settings().vault_local:
        n = _notes_mod()
        if op == "routing_global":
            return n.routing_global()
        if op == "routing_project":
            return n.routing_project(kw["project"])
        if op == "get_note":
            return n.get_note(kw["id"])
        if op == "get_notes":
            return n.get_notes(kw["ids"], summary=kw.get("summary", False))
        if op == "timeline":
            return n.timeline(kw["anchor_id"], before=kw["before"], after=kw["after"])
        if op == "list_notes":
            return n.list_notes(project=kw.get("project"), type_=kw.get("type"), status=kw.get("status", "active"), limit=kw.get("limit", 50), order=kw.get("order", "title"))
        if op == "search_notes":
            return n.search_notes(kw["query"], project=kw.get("project"), type_=kw.get("type"), limit=kw.get("limit", 12))
        if op == "upsert_note":
            return n.upsert_note(kw["payload"])
        if op == "suggest_correction":
            return n.suggest_correction(kw["payload"])
        if op == "push_draft":
            p = kw["payload"]
            return n.push_draft(project=p["project"], title=p["title"], body=p["body"], meta=p["meta"])
        if op == "list_corrections":
            return n.list_corrections(status=kw.get("status", "pending"), limit=kw.get("limit", 100))
        if op == "decide_correction":
            return n.decide_correction(kw["id"], approve=kw["approve"], reason=kw.get("reason", ""))
        if op == "list_drafts":
            return n.list_drafts(project=kw.get("project"), status=kw.get("status", "pending"), limit=kw.get("limit", 100))
        if op == "get_draft":
            return n.get_draft(kw["id"])
        raise ValueError(f"unknown vault op {op}")

    if op in ("routing_global",):
        return _ssh_cli([op])
    if op == "routing_project":
        return _ssh_cli([op, "--project", kw["project"]])
    if op == "get_note":
        return _ssh_cli([op, "--id", kw["id"]])
    if op == "get_notes":
        return _ssh_cli([op], {"ids": kw["ids"], "summary": kw.get("summary", False)})
    if op == "timeline":
        return _ssh_cli([op, "--id", kw["anchor_id"], "--before", str(kw["before"]), "--after", str(kw["after"])])
    if op in ("list_notes", "search_notes"):
        limit = kw.get("limit") if kw.get("limit") is not None else 50
        cmd = [op, f"--limit={int(limit)}", f"--status={kw.get('status', 'active')}"]
        if kw.get("project"):
            cmd += ["--project", kw["project"]]
        if kw.get("type"):
            cmd += ["--type", kw["type"]]
        if op == "list_notes" and kw.get("order") == "recent":
            cmd += ["--order", "recent"]
        if op == "search_notes":
            cmd += ["--query", kw["query"]]
        return _ssh_cli(cmd)
    if op in ("upsert_note", "suggest_correction", "push_draft"):
        return _ssh_cli([op], kw["payload"])
    if op == "list_corrections":
        return _ssh_cli([op, f"--status={kw.get('status', 'pending')}", "--limit", str(kw.get("limit", 100))])
    if op == "decide_correction":
        cmd = [op, "--id", kw["id"], "--approve" if kw["approve"] else "--reject"]
        if not kw["approve"]:
            cmd += ["--reason", kw.get("reason", "")]
        return _ssh_cli(cmd)
    if op == "list_drafts":
        cmd = [op, f"--status={kw.get('status', 'pending')}", "--limit", str(kw.get("limit", 100))]
        if kw.get("project"):
            cmd += ["--project", kw["project"]]
        return _ssh_cli(cmd)
    if op == "get_draft":
        return _ssh_cli([op, "--id", kw["id"]])
    raise ValueError(f"unknown vault op {op}")


# ------------------------------------------------------------------ tools
def call_tool(name: str, args: dict) -> Any:
    args = args or {}
    if name == "routing_global":
        return vault("routing_global")

    if name == "routing_project":
        proj = str(args.get("project") or "")
        if not proj:
            raise ValueError("project required")
        return vault("routing_project", project=proj)

    if name == "get_note":
        if isinstance(args.get("id"), list):
            ids = args["id"]
            if not 1 <= len(ids) <= 20 or any(not isinstance(nid, str) or not nid.strip() for nid in ids):
                raise ValueError("id must contain 1..20 nonempty string ids")
            return vault("get_notes", ids=ids)
        nid = str(args.get("id") or "")
        n = vault("get_note", id=nid)
        return n or {"error": "not_found", "id": nid}

    if name == "timeline":
        anchor = str(args.get("anchor_id") or "")
        before, after = int(args.get("before", 3)), int(args.get("after", 3))
        if not anchor or not (0 <= before <= 20 and 0 <= after <= 20):
            raise ValueError("anchor_id required; before/after must be 0..20")
        data = vault("timeline", anchor_id=anchor, before=before, after=after)
        if "results" in data:
            data["results"] = _compact_index(data["results"])
        return data

    if name == "list_notes":
        return vault(
            "list_notes",
            project=args.get("project"),
            type=args.get("type"),
            status=args.get("status") or "active",
            limit=int(args.get("limit") if args.get("limit") is not None else 50),
            order=args.get("order") or "title",
        )

    if name in ("upsert_note", "suggest_correction"):
        payload = dict(args)
        auto = payload.pop("auto_verdict", None)
        if auto and str(payload.get("action") or payload.get("verdict") or "add").lower() in ("add", "create"):
            _apply_jev_verdict(payload)
        return vault(name, payload=payload)

    if name == "push_draft":
        meta = {k: args[k] for k in DRAFT_META_KEYS if args.get(k) is not None}
        if isinstance(args.get("meta"), dict):
            for k, v in args["meta"].items():
                meta.setdefault(k, v)
        payload = {
            "project": args.get("project") or "通用-未定",
            "title": args.get("title") or "session",
            "body": args.get("body") or "",
            "meta": meta,
        }
        return vault("push_draft", payload=payload)

    if name == "recall":
        return _recall(args)

    raise ValueError(f"unknown tool {name}")


def _apply_jev_verdict(payload: dict) -> None:
    """Let Jev choose add/update/supersede/noop against similar notes of any type."""
    query = " ".join(str(payload.get(k) or "") for k in ("title", "practice", "scene")).strip()[:400]
    hits = vault("search_notes", query=query, project=payload.get("project") or None, type=payload.get("type") or None, limit=8) if query else []
    cands = [{"id": h["id"], "title": h["title"], "scene": (h.get("scene") or "")[:200], "practice": (h.get("practice") or "")[:300]}
             for h in (hits if isinstance(hits, list) else []) if isinstance(h, dict) and h.get("id")]
    if not cands:
        return  # nothing to merge into: a plain add
    digest = f"{payload.get('title')}\n{payload.get('scene')}\n{payload.get('practice')}"
    ver = jev.write_verdict(digest, cands)
    if not ver.ok:
        return
    raw = ver.raw if isinstance(ver.raw, dict) else {}
    verdict = str(raw.get("verdict") or ver.value or "").lower()
    if verdict not in ("add", "update", "supersede", "noop"):
        return
    ids = {c["id"] for c in cands}
    # System One only names the verdict; without a target, the closest candidate is the one meant
    target = raw.get("target_id") if raw.get("target_id") in ids else cands[0]["id"]
    payload["action"] = verdict
    if verdict == "update":
        payload["id"] = target
    elif verdict == "supersede":
        payload["supersedes"] = list(dict.fromkeys([*(payload.get("supersedes") or []), target]))


# Hindsight ≥1.0 serves only the first; the others are kept for older self-hosted builds.
_RECALL_PATHS = ("/v1/default/banks/{bank}/memories/recall", "/v1/banks/{bank}/memories/recall", "/banks/{bank}/recall")
# obsidian_hindsight_sync tags every note `source:obsidian`, `type:<t>`, `project:<p>`.
# all_strict = AND, excluding untagged memories (anything not synced from the vault).
VAULT_TAG = "source:obsidian"
_recall_path: dict[str, str] = {}
_recall_lock = threading.Lock()


def _hindsight_recall(query: str, budget: str, tags: list[str] | None = None, match: str = "all_strict") -> list | dict:
    """POST the plain query; project/type go as tag filters (the sync tags notes `project:<p>`,
    `type:<t>`), never into the embedding text. The working endpoint is discovered once and
    remembered. A server that rejects `tags` (422) is retried without them."""
    s = get_settings()
    base = s.hindsight_base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {s.hindsight_api_key}"} if s.hindsight_api_key else {}
    known = _recall_path.get(base)
    paths = [known] if known else [p.format(bank=s.hindsight_bank) for p in _RECALL_PATHS]
    errors = []
    with httpx.Client(timeout=30.0) as client:
        for path in paths:
            body: dict[str, Any] = {"query": query, "budget": budget}
            if tags:
                body.update(tags=tags, tags_match=match)
            r = client.post(base + path, headers=headers, json=body)
            if r.status_code == 422 and tags:
                r = client.post(base + path, headers=headers, json={"query": query, "budget": budget})
            if r.status_code == 404 and not known:
                errors.append(f"{path}:404")
                continue
            r.raise_for_status()
            with _recall_lock:
                _recall_path[base] = path
            data = r.json()
            if isinstance(data, dict):
                return data.get("results") or data.get("memories") or data.get("items") or []
            return data
    if known:  # remembered endpoint vanished → rediscover next call
        with _recall_lock:
            _recall_path.pop(base, None)
    raise RuntimeError("no recall endpoint: " + ", ".join(errors))


def _recall(args: dict) -> dict:
    query = str(args.get("query") or "")
    project = str(args.get("project") or "")
    typ = str(args.get("type") or "")
    budget = str(args.get("budget") or "mid")
    fmt = args.get("format", "index")
    if fmt not in ("index", "full"):
        raise ValueError("format must be index or full")
    try:
        if project and not typ:
            # this project's notes OR global tips (tips carry no project tag, so AND would drop them);
            # only the vault sync writes project:/type: tags, so any_strict still excludes other memories
            tags, match = [f"project:{project}", "type:tip"], "any_strict"
        else:
            tags, match = [VAULT_TAG] + ([f"type:{typ}"] if typ else []), "all_strict"
            if project and typ != "tip":
                tags.append(f"project:{project}")
        items = _hindsight_recall(query, budget, tags, match)
        results = _by_note(items)
    except Exception as e:  # noqa: BLE001 — any Hindsight failure falls back to the vault itself
        err = f"{type(e).__name__}: {str(e)[:200]}"
        results = vault("search_notes", query=query, project=project or None, type=typ or None, limit=12)
        return {"ok": True, "via": "local-fallback", "error": err, "query": query,
                "results": results if fmt == "full" else _compact_index(results)}
    # Hindsight ranks candidates; the vault decides existence, scope and current content.
    # Read in batches of 20 for the SSH CLI; do not mistake omitted ids for active notes.
    verified = True
    try:
        ids = list(dict.fromkeys(r["document_id"] for r in results
                                if isinstance(r, dict) and r.get("document_id")))
        current = {}
        for pos in range(0, len(ids), 20):
            current.update({n["id"]: n for n in vault("get_notes", ids=ids[pos:pos + 20], summary=fmt == "index")
                            if not n.get("error")})
        fresh = []
        for row in results:
            if not isinstance(row, dict) or not row.get("document_id"):
                fresh.append(row)
                continue
            note = current.get(row["document_id"])
            if not note:
                continue  # deleted in Obsidian, even if Hindsight still has the document
            meta = {k: note[k] for k in ("id", "title", "type", "project", "status", "path", "updated")}
            row = dict(row, metadata={**(row.get("metadata") or {}), **meta})
            if fmt == "full":
                row["text"] = note["text"]
            fresh.append(row)
        results = fresh
    except Exception:  # noqa: BLE001 — retain degraded recall if the vault host is offline
        verified = False
    results = _filter_active(results, project, typ)
    if fmt == "index":
        results = _compact_index(results)
    return {"ok": True, "via": "hindsight", "vault_verified": verified, "query": query, "results": results}


def _compact_index(items: Any) -> list[dict]:
    out = []
    for row in items if isinstance(items, list) else []:
        if not isinstance(row, dict):
            continue
        nid = row.get("document_id") or row.get("id")
        meta = row.get("metadata") or {}
        scores = row.get("scores") or {}
        # Hindsight sends "reranker": null when it skipped reranking; fall through to the next score
        score = next((v for v in (scores.get("reranker"), scores.get("final"), row.get("score")) if v is not None), None)
        # Fact-level rows have no title; their text is the only readable label
        text = " ".join(_row_text(row).split())[:80]
        item = {
            "id": nid,
            "title": str(meta.get("title") or row.get("title") or row.get("context") or text or nid or "")[:160],
            "type": meta.get("type") or row.get("type") or "",
            "date": meta.get("updated") or row.get("updated") or row.get("date") or None,
            "score": score,
        }
        if row.get("resolvable") is False:
            item["resolvable"] = False
        out.append(item)
    return out


def _row_text(it: dict) -> str:
    """Best-effort content field from a Hindsight recall row (fact or note-backed)."""
    for k in ("text", "content", "fact"):
        v = it.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def _norm_text(s: str) -> str:
    return " ".join(s.split())


def _by_note(items: Any) -> Any:
    """Hindsight returns facts, several per note. Keep one row per note (document_id): the
    first, i.e. best-ranked, fact, with the best score of its siblings and how many matched.

    Fact-layer rows without document_id cannot be opened via get_note. Drop those whose text
    duplicates a note already in this result set; keep remaining orphans annotated
    resolvable=false / note_id=null so consumers do not treat their id as a note id.
    """
    if not isinstance(items, list):
        return items

    # Pass 1: merge notes by document_id; park fact-only rows. Slots keep ranking order.
    seen: dict[str, dict] = {}
    facts: list[dict] = []
    slots: list[tuple[str, Any]] = []  # ("note", doc_id) | ("fact", idx) | ("raw", value)

    for it in items:
        if not isinstance(it, dict):
            slots.append(("raw", it))
            continue
        key = it.get("document_id") or None
        if not key:
            facts.append(it)
            slots.append(("fact", len(facts) - 1))
            continue
        first = seen.get(key)
        if first is None:
            seen[key] = dict(it, facts=1, scores=dict(it.get("scores") or {}))
            slots.append(("note", key))
            continue
        first["facts"] += 1
        for k, v in (it.get("scores") or {}).items():
            old = first["scores"].get(k)
            if isinstance(v, (int, float)) and (not isinstance(old, (int, float)) or v > old):
                first["scores"][k] = v

    note_texts = {_norm_text(_row_text(r)) for r in seen.values()}
    note_texts.discard("")

    out: list = []
    for kind, payload in slots:
        if kind == "raw":
            out.append(payload)
            continue
        if kind == "note":
            out.append(seen[payload])
            continue
        fact = facts[payload]
        nt = _norm_text(_row_text(fact))
        if nt and nt in note_texts:
            continue  # duplicate of a returned note → drop, free the recall slot
        out.append(dict(fact, note_id=None, resolvable=False))
    return out


def _filter_active(items: Any, project: str, typ: str) -> Any:
    """Belt-and-braces filter on the note metadata the sync writes. Only `metadata` is read:
    a recall result's top-level `type` is Hindsight's fact kind (world/experience/…), not ours."""
    if not isinstance(items, list):
        return items
    out = []
    for it in items:
        if not isinstance(it, dict):
            out.append(it)
            continue
        meta = it.get("metadata") or {}
        if str(meta.get("status") or "active").lower() not in ("active", ""):
            continue
        p = meta.get("project")
        if project and p and p not in (project, "global") and meta.get("type") != "tip":
            continue
        t = meta.get("type")
        if typ and t and t != typ:
            continue
        out.append(it)
    return out


# ------------------------------------------------------------------ auth
def bearer(authorization: str | None) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return ""


def require_agent(authorization: str | None = Header(default=None)) -> None:
    """Static HINDDIAN_MCP_TOKEN (hooks, legacy clients) or an OAuth access token (oauth.py)."""
    from . import oauth

    s = get_settings()
    token = s.hinddian_mcp_token
    if not token and not s.oauth_enabled:
        if s.hinddian_allow_no_auth:
            return
        raise HTTPException(503, "HINDDIAN_MCP_TOKEN not configured")
    hdr = {"WWW-Authenticate": oauth.www_authenticate()} if s.oauth_enabled else None
    got = bearer(authorization)
    if not got:
        raise HTTPException(401, "Bearer required", headers=hdr)
    if token and hmac.compare_digest(got.encode(), token.encode()):
        return
    if oauth.verify_access_token(got):
        return
    if s.oauth_enabled:
        # 401 (not 403) so MCP clients refresh / re-run the OAuth flow.
        raise HTTPException(401, "invalid token", headers={"WWW-Authenticate": oauth.www_authenticate("invalid_token")})
    raise HTTPException(403, "invalid token")


# ------------------------------------------------------------------ JSON-RPC
def _tool_result(data: Any) -> dict:
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": text}], "isError": False}


def _rpc(msg: dict) -> dict | None:
    if not isinstance(msg, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
    mid = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "hinddian-memory", "version": __version__},
            },
        }
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        try:
            result = call_tool(params.get("name"), params.get("arguments") or {})
            return {"jsonrpc": "2.0", "id": mid, "result": _tool_result(result)}
        except Exception as e:  # noqa: BLE001 — surfaced to the agent as a tool error
            return {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True},
            }
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def _dispatch(msg: Any) -> Any:
    if isinstance(msg, list):
        return [r for r in (_rpc(m) for m in msg) if r is not None]
    return _rpc(msg)


@router.api_route("/mcp", methods=["GET", "POST", "DELETE"], dependencies=[Depends(require_agent)])
@router.api_route("/mcp/", methods=["GET", "POST", "DELETE"], dependencies=[Depends(require_agent)])
async def mcp_endpoint(request: Request):
    if request.method == "GET":
        return JSONResponse({"name": "hinddian-memory", "tools": [t["name"] for t in TOOLS]})
    if request.method == "DELETE":
        return Response(status_code=204)
    body = await request.body()
    if not body:
        return JSONResponse({"error": "empty"}, status_code=400)
    try:
        msg = json.loads(body)
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    # Tool calls block on SSH / HTTP — keep them off the event loop.
    out = await run_in_threadpool(_dispatch, msg)
    if out is None:
        return Response(status_code=202)
    return JSONResponse(out)


# -------- REST for host hooks (curl-friendly). Sync handlers run in FastAPI's threadpool. --------
agent = [Depends(require_agent)]


@router.get("/api/memory/routing/global", dependencies=agent)
def api_routing_global():
    return call_tool("routing_global", {})


@router.get("/api/memory/routing/project/{project}", dependencies=agent)
def api_routing_project(project: str):
    return call_tool("routing_project", {"project": project})


@router.post("/api/memory/recall", dependencies=agent)
def api_recall(args: dict):
    return call_tool("recall", args)


@router.get("/api/memory/notes", dependencies=agent)
def api_list_notes(project: str | None = None, limit: int = 6, order: str = "recent"):
    return call_tool("list_notes", {"project": project, "limit": min(50, max(0, limit)), "order": order})


@router.post("/api/memory/push_draft", dependencies=agent)
def api_push_draft(args: dict):
    return call_tool("push_draft", args)


@router.post("/api/memory/upsert_note", dependencies=agent)
def api_upsert(args: dict):
    return call_tool("upsert_note", args)


@router.post("/api/memory/suggest_correction", dependencies=agent)
def api_suggest_correction(args: dict):
    return call_tool("suggest_correction", args)


@router.get("/api/memory/gates/backend", dependencies=agent)
@router.get("/api/memory/jev-backend", dependencies=agent)
def api_jev_backend():
    return jev.backend_info()


def _project_names() -> list[str]:
    g = call_tool("routing_global", {})
    return [p["name"] for p in g.get("projects", [])]


@router.post("/api/memory/gates/should_recall", dependencies=agent)
def api_should_recall(args: dict):
    r = jev.should_recall(args.get("cwd", ""), args.get("message", ""), _project_names())
    return {"ok": r.ok, "should_recall": r.value, "confidence": r.confidence, "source": r.source, "error": r.error}


@router.post("/api/memory/gates/classify_turn", dependencies=agent)
def api_classify_turn(args: dict):
    r = jev.classify_turn(args.get("turn", "") or args.get("text", ""), _project_names(), str(args.get("cwd") or ""))
    return {"ok": r.ok, "value": r.value, "confidence": r.confidence, "source": r.source, "error": r.error}


@router.post("/api/memory/finalize", dependencies=agent)
def api_finalize(args: dict):
    """Hooks POST a finalized session buffer; Jev runs here and the decision is logged for the dashboard."""
    try:
        return session_finalize.finalize(args, projects=_project_names, push=lambda pl: call_tool("push_draft", pl))
    except session_finalize.FinalizeError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/api/memory/gates/report", dependencies=agent)
def api_gate_report(args: dict):
    """Client hooks report each Jev decision (metadata only) so the dashboard can show it."""
    try:
        rec = jev_log.validate(args)
    except (jev_log.ReportError, TypeError, ValueError) as e:
        raise HTTPException(422, str(e)) from e
    try:
        jev_log.append(rec)
    except OSError as e:
        raise HTTPException(503, f"jev log unavailable: {type(e).__name__}") from e
    return {"ok": True}
