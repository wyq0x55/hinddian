"""hinddian-memory MCP (HTTP JSON-RPC) + REST helpers for host hooks.

Tools: routing_global, routing_project, recall, get_note, upsert_note, suggest_correction, list_notes, push_draft
Transport: HTTP POST /mcp (JSON-RPC). REST under /api/memory/* for host lifecycle hooks.
Vault ops run locally if VAULT_ROOT exists, else via SSH to CLASSIFY_SSH_HOST (DMIT).
"""
from __future__ import annotations

import json
import os
import subprocess
from typing import Any

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from . import jev

router = APIRouter()

HINDSIGHT_BASE = os.environ.get("HINDSIGHT_BASE_URL", "http://127.0.0.1:8888").rstrip("/")
HINDSIGHT_KEY = os.environ.get("HINDSIGHT_API_KEY", "")
MCP_TOKEN = os.environ.get("HINDDIAN_MCP_TOKEN") or HINDSIGHT_KEY
SSH_HOST = os.environ.get("CLASSIFY_SSH_HOST", "dmit-vps")
VAULT_ROOT = os.environ.get("VAULT_ROOT") or os.environ.get("HC_VAULT") or ""
BANK = os.environ.get("HINDSIGHT_BANK", "wanwan")

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
        "description": "Semantic recall of active atomic notes via Hindsight. Filters non-active by default. Prefer after routing_project says to read.",
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
            "tip/preference and face_correction=true may write directly (auto_verdict OK). "
            "decision/architecture without user_confirmed=true is queued as a dashboard suggestion (no silent write). "
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
                "tags": {"type": "array", "items": {"type": "string"}},
                "sources": {"type": "array", "items": {"type": "string"}},
                "auto_verdict": {"type": "boolean", "description": "Jev 4-state; OK for tip/preference"},
                "face_correction": {"type": "boolean", "description": "User explicitly corrected a wrong memory in this turn"},
                "user_confirmed": {"type": "boolean", "description": "User one-line confirmed this decision write"},
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
            "Does not write Obsidian until user approves. Use when unsure or when changing a decision note."
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
            },
            "required": ["title", "body"],
        },
    },
]


def _vault_local() -> bool:
    return bool(VAULT_ROOT) and os.path.isdir(VAULT_ROOT)


def _ssh_cli(args: list[str], payload: dict | None = None) -> Any:
    """Call /usr/local/bin/hinddian-memory-cli on DMIT; return JSON. Payload via stdin."""
    remote = "/usr/local/bin/hinddian-memory-cli " + " ".join(shlex_quote(a) for a in args)
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", SSH_HOST, remote]
    stdin = json.dumps(payload, ensure_ascii=False) if payload is not None else None
    p = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "ssh failed")[:400])
    line = (p.stdout or "").strip().splitlines()[-1]
    return json.loads(line)


def shlex_quote(s: str) -> str:
    import shlex
    return shlex.quote(s)


def _notes_mod():
    from . import notes

    if VAULT_ROOT:
        notes.VAULT = __import__("pathlib").Path(VAULT_ROOT)
    return notes


def call_tool(name: str, args: dict) -> Any:
    args = args or {}
    if name == "routing_global":
        if _vault_local():
            return _notes_mod().routing_global()
        return _ssh_cli(["routing_global"])

    if name == "routing_project":
        proj = args.get("project") or ""
        if not proj:
            raise ValueError("project required")
        if _vault_local():
            return _notes_mod().routing_project(proj)
        return _ssh_cli(["routing_project", "--project", proj])

    if name == "get_note":
        nid = args.get("id") or ""
        if _vault_local():
            n = _notes_mod().get_note(nid)
        else:
            n = _ssh_cli(["get_note", "--id", nid])
        if not n:
            return {"error": "not_found", "id": nid}
        return n

    if name == "list_notes":
        kw = dict(
            project=args.get("project"),
            type_=args.get("type"),
            status=args.get("status") or "active",
            limit=int(args.get("limit") or 50),
        )
        if _vault_local():
            return _notes_mod().list_notes(**kw)
        cmd = ["list_notes", f"--limit={kw['limit']}", f"--status={kw['status']}"]
        if kw["project"]:
            cmd += ["--project", kw["project"]]
        if kw["type_"]:
            cmd += ["--type", kw["type_"]]
        return _ssh_cli(cmd)

    if name == "upsert_note":
        payload = dict(args)
        # Never allow auto_verdict to bypass decision gate silently: keep flags.
        if payload.get("auto_verdict"):
            typ = (payload.get("type") or "").lower()
            if typ in ("decision",) and not (
                payload.get("user_confirmed") or payload.get("face_correction")
            ):
                # Force suggest path instead of silent auto write
                payload["mode"] = payload.get("mode") or "suggest"
            else:
                cands = call_tool(
                    "list_notes",
                    {"project": payload.get("project"), "type": payload.get("type"), "status": "active", "limit": 20},
                )
                digest = f"{payload.get('title')}\n{payload.get('scene')}\n{payload.get('practice')}"
                ver = jev.write_verdict(digest, cands if isinstance(cands, list) else [])
                if ver.ok:
                    if isinstance(ver.value, str):
                        payload["action"] = ver.value
                    elif isinstance(ver.raw, dict) and ver.raw.get("verdict"):
                        payload["action"] = ver.raw["verdict"]
                        if ver.raw.get("target_id"):
                            payload["id"] = ver.raw["target_id"]
            payload.pop("auto_verdict", None)
        if _vault_local():
            return _notes_mod().upsert_note(payload)
        return _ssh_cli(["upsert_note"], payload)

    if name == "suggest_correction":
        payload = dict(args)
        payload["mode"] = "suggest"
        if _vault_local():
            return _notes_mod().enqueue_correction(payload)
        return _ssh_cli(["suggest_correction"], payload)

    if name == "push_draft":
        meta_keys = (
            "type", "confidence", "origin", "session_id", "jev_source",
            "turn_count", "finalize_reason",
        )
        meta = {k: args[k] for k in meta_keys if k in args and args[k] is not None}
        # also accept nested meta
        if isinstance(args.get("meta"), dict):
            for k, v in args["meta"].items():
                meta.setdefault(k, v)
        kw = dict(
            project=args.get("project") or "通用-未定",
            title=args.get("title") or "session",
            body=args.get("body") or "",
            meta=meta,
        )
        if _vault_local():
            return _notes_mod().push_draft(**kw)
        return _ssh_cli(["push_draft"], {"project": kw["project"], "title": kw["title"], "body": kw["body"], "meta": kw["meta"]})

    if name == "recall":
        return _recall(args)

    raise ValueError(f"unknown tool {name}")


def _recall(args: dict) -> dict:
    query = args.get("query") or ""
    project = args.get("project") or ""
    typ = args.get("type") or ""
    budget = args.get("budget") or "mid"
    # Prefer Hindsight HTTP recall if available; else local list+filter
    headers = {"Authorization": f"Bearer {HINDSIGHT_KEY}"} if HINDSIGHT_KEY else {}
    q = query
    if project:
        q = f"[project:{project}] {q}"
    if typ:
        q = f"[type:{typ}] {q}"
    try:
        with httpx.Client(timeout=45.0) as client:
            # Hindsight slim API variants; try common paths
            for path in (f"/v1/default/banks/{BANK}/memories/recall", f"/v1/banks/{BANK}/memories/recall", f"/banks/{BANK}/recall"):
                url = HINDSIGHT_BASE + path
                r = client.post(url, headers=headers, json={"query": q, "budget": budget})
                if r.status_code == 404:
                    continue
                if r.status_code >= 400:
                    continue
                data = r.json()
                items = data.get("results") or data.get("memories") or data.get("items") or data
                return {"ok": True, "via": "hindsight", "query": q, "results": _filter_active(items, project, typ)}
    except Exception as e:
        hindsight_err = str(e)[:200]
    else:
        hindsight_err = "no_endpoint"
    # fallback: local notes keyword
    notes = call_tool("list_notes", {"project": project or None, "type": typ or None, "status": "active", "limit": 100})
    qlow = query.lower()
    scored = []
    if isinstance(notes, list):
        for n in notes:
            blob = (n.get("title") or "").lower()
            score = sum(1 for w in qlow.split() if w and w in blob)
            if score:
                scored.append({**n, "score": score})
        scored.sort(key=lambda x: -x["score"])
    return {"ok": True, "via": "local-fallback", "error": hindsight_err, "query": q, "results": scored[:12]}


def _filter_active(items: Any, project: str, typ: str) -> Any:
    if not isinstance(items, list):
        return items
    out = []
    for it in items:
        if not isinstance(it, dict):
            out.append(it)
            continue
        meta = it.get("metadata") or it.get("meta") or {}
        status = (meta.get("status") or it.get("status") or "active").lower()
        if status not in ("active", ""):
            continue
        if project and (meta.get("project") or it.get("project")) not in (project, None, ""):
            # soft filter — keep if missing
            p = meta.get("project") or it.get("project")
            if p and p != project:
                continue
        if typ:
            t = meta.get("type") or it.get("type")
            if t and t != typ:
                continue
        out.append(it)
    return out


def _check_auth(authorization: str | None) -> None:
    if not MCP_TOKEN:
        return
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Bearer required")
    if authorization.split(" ", 1)[1].strip() != MCP_TOKEN:
        raise HTTPException(403, "invalid token")


def _tool_result(data: Any) -> dict:
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": text}], "isError": False}


def _rpc(msg: dict) -> dict | None:
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
                "serverInfo": {"name": "hinddian-memory", "version": "0.5.0"},
            },
        }
    if method == "notifications/initialized" or method == "initialized":
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            result = call_tool(name, args)
            return {"jsonrpc": "2.0", "id": mid, "result": _tool_result(result)}
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True},
            }
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}


@router.api_route("/mcp", methods=["GET", "POST", "DELETE"])
@router.api_route("/mcp/", methods=["GET", "POST", "DELETE"])
async def mcp_endpoint(request: Request, authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    if request.method == "GET":
        # lightweight discovery
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
    if isinstance(msg, list):
        out = []
        for m in msg:
            r = _rpc(m)
            if r is not None:
                out.append(r)
        return JSONResponse(out)
    r = _rpc(msg)
    if r is None:
        return Response(status_code=202)
    return JSONResponse(r)


# -------- REST for host hooks (curl-friendly) --------
@router.get("/api/memory/routing/global")
def api_routing_global(authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    return call_tool("routing_global", {})


@router.get("/api/memory/routing/project/{project}")
def api_routing_project(project: str, authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    return call_tool("routing_project", {"project": project})


@router.post("/api/memory/recall")
async def api_recall(request: Request, authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    args = await request.json()
    return call_tool("recall", args)


@router.post("/api/memory/push_draft")
async def api_push_draft(request: Request, authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    args = await request.json()
    return call_tool("push_draft", args)


@router.post("/api/memory/upsert_note")
async def api_upsert(request: Request, authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    args = await request.json()
    return call_tool("upsert_note", args)


@router.get("/api/memory/gates/backend")
async def api_jev_backend(authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    return jev.backend_info()


@router.post("/api/memory/gates/should_recall")
async def api_should_recall(request: Request, authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    args = await request.json()
    g = call_tool("routing_global", {})
    projects = [p["name"] for p in g.get("projects", [])]
    r = jev.should_recall(args.get("cwd", ""), args.get("message", ""), projects)
    return {"ok": r.ok, "should_recall": r.value, "confidence": r.confidence, "source": r.source, "error": r.error}


@router.post("/api/memory/gates/classify_turn")
async def api_classify_turn(request: Request, authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    args = await request.json()
    g = call_tool("routing_global", {})
    projects = [p["name"] for p in g.get("projects", [])]
    r = jev.classify_turn(args.get("turn", "") or args.get("text", ""), projects)
    return {"ok": r.ok, "value": r.value, "confidence": r.confidence, "source": r.source, "error": r.error}


@router.get("/api/memory/corrections")
def api_list_corrections(status: str = "pending", authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    if _vault_local():
        return _notes_mod().list_corrections(status=status)
    return _ssh_cli(["list_corrections", f"--status={status}"])


@router.post("/api/memory/corrections/{cid}/approve")
async def api_approve_correction(cid: str, authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    if _vault_local():
        return _notes_mod().decide_correction(cid, approve=True)
    return _ssh_cli(["decide_correction", "--id", cid, "--approve"])


@router.post("/api/memory/corrections/{cid}/reject")
async def api_reject_correction(cid: str, request: Request, authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    reason = str((body or {}).get("reason") or "")
    if _vault_local():
        return _notes_mod().decide_correction(cid, approve=False, reason=reason)
    return _ssh_cli(["decide_correction", "--id", cid, "--reject", "--reason", reason])


@router.post("/api/memory/suggest_correction")
async def api_suggest_correction(request: Request, authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    args = await request.json()
    return call_tool("suggest_correction", args)
