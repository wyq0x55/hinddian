"""hinddian-memory MCP (HTTP JSON-RPC) + REST helpers for host hooks — the *agent channel*.

Tools: routing_global, routing_project, recall, get_note, upsert_note, suggest_correction, list_notes, push_draft
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

from . import __version__, jev
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
        "description": "Project routing table: current state, decision/lesson titles+ids, when_to_recall guidance.",
        "inputSchema": {
            "type": "object",
            "properties": {"project": {"type": "string", "description": "Project folder name"}},
            "required": ["project"],
        },
    },
    {
        "name": "recall",
        "description": "Semantic recall of active atomic notes via Hindsight (local bigram search if Hindsight is down). Filters non-active by default. Prefer after routing_project says to read.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "project": {"type": "string"},
                "type": {"type": "string", "description": "decision|lesson|tip"},
                "budget": {"type": "string", "description": "low|mid|high", "default": "mid"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_note",
        "description": "Fetch one atomic note by id (full text + related links + status).",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
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
            },
        },
    },
    {
        "name": "upsert_note",
        "description": (
            "Gated write to Obsidian (SoT). Actions: add|update|supersede|noop|obsolete. "
            "tip/preference/lesson write directly. Anything that creates, changes or retires a decision "
            "is queued for the user's dashboard approval — no flag bypasses this. "
            "Hard delete forbidden — use supersede or obsolete. Never Hindsight retain. No secrets."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "add|update|supersede|noop|obsolete (not delete)"},
                "id": {"type": "string"},
                "type": {"type": "string", "description": "decision|lesson|tip|preference"},
                "project": {"type": "string"},
                "title": {"type": "string"},
                "slug": {"type": "string"},
                "scene": {"type": "string"},
                "practice": {"type": "string"},
                "reason": {"type": "string"},
                "supersedes": {"type": "array", "items": {"type": "string"}},
                "related": {"type": "array", "items": {"type": "string"}},
                "tags": {"type": "array", "items": {"type": "string"}},
                "sources": {"type": "array", "items": {"type": "string"}},
                "auto_verdict": {"type": "boolean", "description": "Let Jev pick add/update/supersede/noop against existing notes"},
                "face_correction": {"type": "boolean", "description": "User explicitly corrected a wrong memory in this turn (shown to the reviewer)"},
                "user_confirmed": {"type": "boolean", "description": "User confirmed in chat (shown to the reviewer; decisions still need dashboard approval)"},
                "mode": {"type": "string", "description": "suggest = force queue to dashboard"},
                "correction_reason": {"type": "string"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "suggest_correction",
        "description": (
            "Queue an Agent memory correction for dashboard approval (preferred for decision/architecture). "
            "Does not write Obsidian until the user approves."
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
            "required": ["title"],
        },
    },
    {
        "name": "push_draft",
        "description": "Push one session draft into drafts/<project>/ (session_id upserts same file). Threshold counts session drafts, not turns. Include jev_source when known.",
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
    """Run one vault op locally (VAULT_ROOT mounted) or on the vault host via the memory CLI."""
    if get_settings().vault_local:
        n = _notes_mod()
        if op == "routing_global":
            return n.routing_global()
        if op == "routing_project":
            return n.routing_project(kw["project"])
        if op == "get_note":
            return n.get_note(kw["id"])
        if op == "list_notes":
            return n.list_notes(project=kw.get("project"), type_=kw.get("type"), status=kw.get("status", "active"), limit=kw.get("limit", 50))
        if op == "search_notes":
            return n.search_notes(kw["query"], project=kw.get("project"), type_=kw.get("type"), limit=kw.get("limit", 12))
        if op == "upsert_note":
            return n.upsert_note(kw["payload"])
        if op == "suggest_correction":
            return n.enqueue_correction(kw["payload"])
        if op == "push_draft":
            p = kw["payload"]
            return n.push_draft(project=p["project"], title=p["title"], body=p["body"], meta=p["meta"])
        if op == "list_corrections":
            return n.list_corrections(status=kw.get("status", "pending"), limit=kw.get("limit", 100))
        if op == "decide_correction":
            return n.decide_correction(kw["id"], approve=kw["approve"], reason=kw.get("reason", ""))
        raise ValueError(f"unknown vault op {op}")

    if op in ("routing_global",):
        return _ssh_cli([op])
    if op == "routing_project":
        return _ssh_cli([op, "--project", kw["project"]])
    if op == "get_note":
        return _ssh_cli([op, "--id", kw["id"]])
    if op in ("list_notes", "search_notes"):
        cmd = [op, f"--limit={int(kw.get('limit') or 50)}", f"--status={kw.get('status', 'active')}"]
        if kw.get("project"):
            cmd += ["--project", kw["project"]]
        if kw.get("type"):
            cmd += ["--type", kw["type"]]
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
        nid = str(args.get("id") or "")
        n = vault("get_note", id=nid)
        return n or {"error": "not_found", "id": nid}

    if name == "list_notes":
        return vault(
            "list_notes",
            project=args.get("project"),
            type=args.get("type"),
            status=args.get("status") or "active",
            limit=int(args.get("limit") or 50),
        )

    if name == "upsert_note":
        payload = dict(args)
        if payload.pop("auto_verdict", None) and (payload.get("type") or "").lower() != "decision":
            _apply_jev_verdict(payload)
        return vault("upsert_note", payload=payload)

    if name == "suggest_correction":
        return vault("suggest_correction", payload=dict(args, mode="suggest"))

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
    """Let Jev choose add/update/supersede/noop against nearby notes. Decisions skip this:
    they are queued for the dashboard whatever the verdict."""
    cands = vault("list_notes", project=payload.get("project"), type=payload.get("type"), status="active", limit=20)
    digest = f"{payload.get('title')}\n{payload.get('scene')}\n{payload.get('practice')}"
    ver = jev.write_verdict(digest, cands if isinstance(cands, list) else [])
    if not ver.ok:
        return
    if isinstance(ver.value, str):
        payload["action"] = ver.value
    elif isinstance(ver.raw, dict) and ver.raw.get("verdict"):
        payload["action"] = ver.raw["verdict"]
        if ver.raw.get("target_id"):
            payload["id"] = ver.raw["target_id"]


# Hindsight ≥1.0 serves only the first; the others are kept for older self-hosted builds.
_RECALL_PATHS = ("/v1/default/banks/{bank}/memories/recall", "/v1/banks/{bank}/memories/recall", "/banks/{bank}/recall")
# obsidian_hindsight_sync tags every note `source:obsidian`, `type:<t>`, `project:<p>`.
# all_strict = AND, excluding untagged memories (anything not synced from the vault).
VAULT_TAG = "source:obsidian"
_recall_path: dict[str, str] = {}
_recall_lock = threading.Lock()


def _hindsight_recall(query: str, budget: str, tags: list[str] | None = None) -> list | dict:
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
                body.update(tags=tags, tags_match="all_strict")
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
    try:
        tags = [VAULT_TAG] + ([f"type:{typ}"] if typ else [])
        if project and typ != "tip":
            tags.append(f"project:{project}")
        items = _hindsight_recall(query, budget, tags)
        return {"ok": True, "via": "hindsight", "query": query, "results": _filter_active(items, project, typ)}
    except Exception as e:  # noqa: BLE001 — any Hindsight failure falls back to the vault itself
        err = f"{type(e).__name__}: {str(e)[:200]}"
    results = vault("search_notes", query=query, project=project or None, type=typ or None, limit=12)
    return {"ok": True, "via": "local-fallback", "error": err, "query": query, "results": results}


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
    s = get_settings()
    token = s.hinddian_mcp_token
    if not token:
        if s.hinddian_allow_no_auth:
            return
        raise HTTPException(503, "HINDDIAN_MCP_TOKEN not configured")
    got = bearer(authorization)
    if not got:
        raise HTTPException(401, "Bearer required")
    if not hmac.compare_digest(got.encode(), token.encode()):
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
    r = jev.classify_turn(args.get("turn", "") or args.get("text", ""), _project_names())
    return {"ok": r.ok, "value": r.value, "confidence": r.confidence, "source": r.source, "error": r.error}
