"""FastAPI app. Two channels with separate credentials:

  agent channel     /mcp, /api/memory/*  — Bearer HINDDIAN_MCP_TOKEN (memory_mcp.py)
  dashboard channel /, /api/*            — AUTH_TOKEN, as Bearer or as the X-Hinddian-Dashboard
                                           header a TLS/mTLS proxy injects. Approvals live here only.
"""

from __future__ import annotations

import hmac
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from . import classify_remote
from . import memory_mcp
from .config import Settings, get_settings

WEB_DIR = Path(__file__).resolve().parents[2] / "web"


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    yield


app = FastAPI(title="hinddian", version=__version__, description="hinddian memory dashboard", lifespan=_lifespan)
app.include_router(memory_mcp.router)


def _settings() -> Settings:
    return get_settings()


def require_dashboard(
    authorization: str | None = Header(default=None),
    x_hinddian_dashboard: str | None = Header(default=None),
    settings: Settings = Depends(_settings),
) -> None:
    token = settings.auth_token
    if not token:
        if settings.hinddian_allow_no_auth:
            return
        raise HTTPException(503, "dashboard disabled: set AUTH_TOKEN (distinct from HINDDIAN_MCP_TOKEN)")
    if settings.hinddian_mcp_token and hmac.compare_digest(token.encode(), settings.hinddian_mcp_token.encode()):
        raise HTTPException(503, "AUTH_TOKEN must differ from HINDDIAN_MCP_TOKEN")
    got = memory_mcp.bearer(authorization) or (x_hinddian_dashboard or "").strip()
    if not got:
        raise HTTPException(401, "dashboard token required")
    if not hmac.compare_digest(got.encode(), token.encode()):
        raise HTTPException(403, "invalid token")


def require_csrf(x_hinddian: str | None = Header(default=None)) -> None:
    """Mutations need a custom header → cross-site forms/fetch can't send it without CORS."""
    if x_hinddian != "1":
        raise HTTPException(403, "missing X-Hinddian header")


NOTE_TYPES = ("decision", "lesson", "tip")
dash = [Depends(require_dashboard)]
dash_write = [Depends(require_dashboard), Depends(require_csrf)]


def _vault(op: str, **kw: Any) -> Any:
    try:
        return memory_mcp.vault(op, **kw)
    except Exception as e:  # noqa: BLE001 — surfaced to the dashboard as a 502
        raise HTTPException(502, f"vault host: {str(e)[:300]}") from e


def _soft(fn, *args) -> tuple[Any, str | None]:
    try:
        return fn(*args), None
    except Exception as e:  # noqa: BLE001
        return None, str(e)[:200]


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "service": "hinddian", "version": __version__}


@app.get("/api/overview", dependencies=dash)
def overview() -> dict:
    """Everything the 概览 tab and the tab badges need, each part failing independently."""
    routing, routing_err = _soft(memory_mcp.vault, "routing_global")
    gate, gate_err = _soft(classify_remote.gate)
    corr, corr_err = _soft(lambda: memory_mcp.vault("list_corrections", status="pending", limit=100))
    projects = (routing or {}).get("projects") or []
    gate_projects = (gate or {}).get("projects") or []
    return {
        "version": __version__,
        "vault": {
            "ok": routing_err is None,
            "error": routing_err,
            "projects": len(projects),
            "decisions": sum(p.get("decisions", 0) for p in projects),
            "lessons": sum(p.get("lessons", 0) for p in projects),
            "tips": ((routing or {}).get("tips") or {}).get("count", 0),
        },
        "drafts": {
            "ok": gate_err is None,
            "error": gate_err,
            "total": sum(p.get("drafts", 0) for p in gate_projects),
            "ready": sum(1 for p in gate_projects if p.get("state") == "ready"),
            "processed": sum(p.get("processed", 0) for p in gate_projects),
        },
        "corrections": {"ok": corr_err is None, "error": corr_err, "pending": len(corr or [])},
        "sync": classify_remote.sync_status(),
        "hindsight": classify_remote.hindsight_stats(),
    }


@app.get("/api/notes", dependencies=dash)
def notes(project: str | None = None, type: str | None = None, status: str = "active", q: str = "", limit: int = 200) -> list[dict]:
    limit = max(1, min(int(limit), 500))
    if q.strip():
        return _vault("search_notes", query=q.strip()[:200], project=project or None, type=type or None, limit=min(limit, 50))
    rows = _vault("list_notes", project=project or None, type=type or None, status=status, limit=limit)
    # hub / project-state pages are navigation, not memory
    return rows if type else [r for r in rows if r.get("type") in NOTE_TYPES]


@app.get("/api/note", dependencies=dash)
def note(id: str) -> dict:
    n = _vault("get_note", id=id)
    if not n:
        raise HTTPException(404, "note not found")
    return n


@app.post("/api/recall", dependencies=dash)
def recall(payload: dict = Body(...)) -> dict:
    """The same recall the agent gets — lets you check what auto-recall would inject."""
    query = str(payload.get("query") or "").strip()
    if not query:
        raise HTTPException(400, "query required")
    return memory_mcp.call_tool("recall", {"query": query[:500], "project": payload.get("project") or "", "budget": "low"})


@app.get("/api/gate", dependencies=dash)
def batch_gate(settings: Settings = Depends(_settings)) -> dict:
    if not settings.classify_enabled:
        raise HTTPException(503, "batch stage disabled")
    try:
        return classify_remote.gate()
    except classify_remote.RemoteError as e:
        raise HTTPException(502, str(e)) from e


@app.post("/api/gate/{project}/approve", dependencies=dash_write)
def batch_approve(project: str, settings: Settings = Depends(_settings)) -> dict:
    if not settings.classify_enabled:
        raise HTTPException(503, "batch stage disabled")
    try:
        return classify_remote.approve_batch(project)
    except classify_remote.RemoteError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/corrections", dependencies=dash)
def list_agent_corrections(status: str = "pending") -> list[dict]:
    """Agent gated-upsert suggestions queued on the vault host."""
    return _vault("list_corrections", status=status, limit=100)


@app.post("/api/corrections/{cid}/approve", dependencies=dash_write)
def approve_agent_correction(cid: str) -> dict:
    return _vault("decide_correction", id=cid, approve=True)


@app.post("/api/corrections/{cid}/reject", dependencies=dash_write)
def reject_agent_correction(cid: str, payload: dict = Body(default={})) -> dict:
    return _vault("decide_correction", id=cid, approve=False, reason=str((payload or {}).get("reason") or ""))


@app.get("/", dependencies=dash)
def index() -> FileResponse:
    index_path = WEB_DIR / "index.html"
    if not index_path.is_file():
        raise HTTPException(404, "web/index.html missing")
    return FileResponse(index_path, headers={"Cache-Control": "no-cache"})


if WEB_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
