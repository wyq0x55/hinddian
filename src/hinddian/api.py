"""FastAPI app. Two channels with separate credentials:

  agent channel     /mcp, /api/memory/*  — Bearer HINDDIAN_MCP_TOKEN (memory_mcp.py)
  dashboard channel /, /api/*            — AUTH_TOKEN, as Bearer or as the X-Hinddian-Dashboard
                                           header a TLS/mTLS proxy injects. Approvals live here only.
"""

from __future__ import annotations

import hmac
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from . import classify_remote
from . import memory_mcp
from .config import Settings, get_settings
from .models import FilterResult, InboxItem, PipelineStats, TopicDocStatus
from .store import build_topic_statuses, collect_filters, compute_stats, scan_inbox

WEB_DIR = Path(__file__).resolve().parents[2] / "web"

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    get_settings().status_db.parent.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="hinddian", version=__version__, description="Topic memory pipeline dashboard", lifespan=_lifespan)
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


dash = [Depends(require_dashboard)]
dash_write = [Depends(require_dashboard), Depends(require_csrf)]


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "service": "hinddian", "version": __version__}


@app.get("/api/stats", response_model=PipelineStats, dependencies=dash)
def stats(settings: Settings = Depends(_settings)) -> PipelineStats:
    return compute_stats(settings)


@app.get("/api/inbox", response_model=list[InboxItem], dependencies=dash)
def inbox(settings: Settings = Depends(_settings)) -> list[InboxItem]:
    return scan_inbox(settings)


@app.get("/api/filters", response_model=list[FilterResult], dependencies=dash)
def filters(settings: Settings = Depends(_settings)) -> list[FilterResult]:
    return collect_filters(settings)


@app.get("/api/topics", response_model=list[TopicDocStatus], dependencies=dash)
def topics(settings: Settings = Depends(_settings)) -> list[TopicDocStatus]:
    return build_topic_statuses(settings)


def _classify_guard(settings: Settings) -> None:
    if not settings.classify_enabled:
        raise HTTPException(503, "classify stage disabled")


@app.get("/api/classify/stats", dependencies=dash)
def classify_stats(settings: Settings = Depends(_settings)) -> dict:
    _classify_guard(settings)
    try:
        data = classify_remote.stats()
        data["reachable"] = True
    except classify_remote.RemoteError as e:
        data = {"reachable": False, "error": str(e)}
    data["hindsight"] = classify_remote.hindsight_stats()
    sync = classify_remote.sync_status()
    data["obsidian_sync"] = sync
    data["hindsight_retain_enabled"] = settings.hindsight_retain_enabled or bool(sync)
    return data


@app.get("/api/gate", dependencies=dash)
def batch_gate(settings: Settings = Depends(_settings)) -> dict:
    _classify_guard(settings)
    try:
        return classify_remote.gate()
    except classify_remote.RemoteError as e:
        raise HTTPException(502, str(e)) from e


@app.post("/api/gate/{project}/approve", dependencies=dash_write)
def batch_approve(project: str, settings: Settings = Depends(_settings)) -> dict:
    _classify_guard(settings)
    try:
        return classify_remote.approve_batch(project)
    except classify_remote.RemoteError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/classify/proposals", dependencies=dash)
def classify_proposals(status: str = "pending", settings: Settings = Depends(_settings)) -> list[dict]:
    _classify_guard(settings)
    try:
        return classify_remote.proposals(status)
    except classify_remote.RemoteError as e:
        raise HTTPException(502, str(e)) from e


@app.get("/api/classify/recent", dependencies=dash)
def classify_recent(limit: int = 30, settings: Settings = Depends(_settings)) -> list[dict]:
    _classify_guard(settings)
    try:
        return classify_remote.recent(limit)
    except classify_remote.RemoteError as e:
        raise HTTPException(502, str(e)) from e


@app.post("/api/classify/proposals/{pid}/approve", dependencies=dash_write)
def classify_approve(pid: str, settings: Settings = Depends(_settings)) -> dict:
    _classify_guard(settings)
    try:
        return classify_remote.decide(pid, True)
    except classify_remote.RemoteError as e:
        raise HTTPException(502, str(e)) from e


@app.post("/api/classify/proposals/{pid}/reject", dependencies=dash_write)
def classify_reject(pid: str, payload: dict = Body(default={}), settings: Settings = Depends(_settings)) -> dict:
    _classify_guard(settings)
    try:
        return classify_remote.decide(pid, False, str(payload.get("reason") or ""))
    except classify_remote.RemoteError as e:
        raise HTTPException(502, str(e)) from e


@app.post("/api/classify/proposals/batch", dependencies=dash_write)
def classify_batch(payload: dict = Body(...), settings: Settings = Depends(_settings)) -> dict:
    """{ids: [...], action: approve|reject, reason?} — DMIT applies sequentially under one lock,
    re-reading the target before each write and renumbering D-/L- ids."""
    _classify_guard(settings)
    action = payload.get("action")
    if action not in ("approve", "reject"):
        raise HTTPException(400, "action must be approve|reject")
    try:
        return classify_remote.batch(list(payload.get("ids") or []), action == "approve", str(payload.get("reason") or ""))
    except classify_remote.RemoteError as e:
        raise HTTPException(502, str(e)) from e


@app.post("/api/classify/proposals/{pid}/restore", dependencies=dash_write)
def classify_restore(pid: str, settings: Settings = Depends(_settings)) -> dict:
    _classify_guard(settings)
    try:
        return classify_remote.restore(pid)
    except classify_remote.RemoteError as e:
        raise HTTPException(502, str(e)) from e


@app.get("/api/corrections", dependencies=dash)
def list_agent_corrections(status: str = "pending") -> list[dict]:
    """Agent gated-upsert suggestions queued on DMIT (alongside distill proposals)."""
    try:
        return memory_mcp.vault("list_corrections", status=status, limit=100)
    except Exception as e:
        raise HTTPException(502, str(e)[:300]) from e


@app.post("/api/corrections/{cid}/approve", dependencies=dash_write)
def approve_agent_correction(cid: str) -> dict:
    try:
        return memory_mcp.vault("decide_correction", id=cid, approve=True)
    except Exception as e:
        raise HTTPException(502, str(e)[:300]) from e


@app.post("/api/corrections/{cid}/reject", dependencies=dash_write)
def reject_agent_correction(cid: str, payload: dict = Body(default={})) -> dict:
    reason = str((payload or {}).get("reason") or "")
    try:
        return memory_mcp.vault("decide_correction", id=cid, approve=False, reason=reason)
    except Exception as e:
        raise HTTPException(502, str(e)[:300]) from e


@app.get("/", dependencies=dash)
def index() -> FileResponse:
    index_path = WEB_DIR / "index.html"
    if not index_path.is_file():
        raise HTTPException(404, "web/index.html missing")
    return FileResponse(index_path)


if WEB_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
