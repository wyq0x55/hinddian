"""FastAPI: health + pipeline observability endpoints + static dashboard."""

from __future__ import annotations

from pathlib import Path

from fastapi import Body, Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from . import classify_remote
from .config import Settings, get_settings
from .models import DistillJob, FilterResult, InboxItem, MergeEvent, PipelineStats, TopicDocStatus
from .store import (
    StatusStore,
    build_topic_statuses,
    collect_filters,
    compute_stats,
    demo_inbox,
    demo_stats,
    demo_topics,
    scan_inbox,
    seed_demo_if_empty,
)

WEB_DIR = Path(__file__).resolve().parents[2] / "web"

app = FastAPI(title="hinddian", version=__version__, description="Topic memory pipeline dashboard")


def _settings() -> Settings:
    return get_settings()


def require_auth(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(_settings),
) -> None:
    token = settings.auth_token
    if not token:
        return
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    got = authorization.split(" ", 1)[1].strip()
    if got != token:
        raise HTTPException(status_code=403, detail="Invalid token")


def _paths_missing(settings: Settings) -> bool:
    return not settings.inbox_dir.is_dir()


@app.on_event("startup")
def _startup() -> None:
    settings = get_settings()
    settings.status_db.parent.mkdir(parents=True, exist_ok=True)
    # Never seed demo when USE_DEMO_DATA=false (production).
    if settings.use_demo_data and _paths_missing(settings):
        seed_demo_if_empty(settings)


@app.get("/api/health")
def health(settings: Settings = Depends(_settings)) -> dict:
    return {
        "ok": True,
        "service": "hinddian",
        "version": __version__,
        "demo": settings.use_demo_data and _paths_missing(settings),
        "use_demo_data": settings.use_demo_data,
        "vault_root": str(settings.vault_root) if settings.vault_root else None,
        "vault_mounted": bool(settings.vault_root and settings.vault_root.is_dir()),
        "inbox_dir": str(settings.inbox_dir),
        "inbox_exists": settings.inbox_dir.is_dir(),
    }


@app.get("/api/stats", response_model=PipelineStats, dependencies=[Depends(require_auth)])
def stats(settings: Settings = Depends(_settings)) -> PipelineStats:
    if settings.use_demo_data and _paths_missing(settings):
        seed_demo_if_empty(settings)
        real = compute_stats(settings)
        d = demo_stats()
        d.jobs_pending = real.jobs_pending or d.jobs_pending
        d.jobs_running = real.jobs_running or d.jobs_running
        d.jobs_done = real.jobs_done or d.jobs_done
        d.jobs_failed = real.jobs_failed or d.jobs_failed
        d.pending_ingests = real.pending_ingests or d.pending_ingests
        d.topics_tracked = max(real.topics_tracked, d.topics_tracked)
        return d
    return compute_stats(settings)


@app.get("/api/inbox", response_model=list[InboxItem], dependencies=[Depends(require_auth)])
def inbox(settings: Settings = Depends(_settings)) -> list[InboxItem]:
    items = scan_inbox(settings)
    if not items and settings.use_demo_data and _paths_missing(settings):
        return demo_inbox()
    return items


@app.get("/api/jobs", response_model=list[DistillJob], dependencies=[Depends(require_auth)])
def jobs(settings: Settings = Depends(_settings)) -> list[DistillJob]:
    if settings.use_demo_data and _paths_missing(settings):
        seed_demo_if_empty(settings)
    return StatusStore(settings.status_db).list_jobs()


@app.get("/api/filters", response_model=list[FilterResult], dependencies=[Depends(require_auth)])
def filters(settings: Settings = Depends(_settings)) -> list[FilterResult]:
    live = collect_filters(settings)
    if live:
        return live
    if settings.use_demo_data and _paths_missing(settings):
        seed_demo_if_empty(settings)
        return StatusStore(settings.status_db).filter_results()
    return []


@app.get("/api/topics", response_model=list[TopicDocStatus], dependencies=[Depends(require_auth)])
def topics(settings: Settings = Depends(_settings)) -> list[TopicDocStatus]:
    if settings.use_demo_data and _paths_missing(settings):
        seed_demo_if_empty(settings)
        real = build_topic_statuses(settings)
        if len(real) <= 1 and not (settings.vault_root and settings.vault_root.is_dir()):
            return demo_topics()
        return real
    # Production: real topics only (agent tips always present; vault optional).
    return build_topic_statuses(settings)


@app.get("/api/merges", response_model=list[MergeEvent], dependencies=[Depends(require_auth)])
def merges(settings: Settings = Depends(_settings)) -> list[MergeEvent]:
    if settings.use_demo_data and _paths_missing(settings):
        seed_demo_if_empty(settings)
    return StatusStore(settings.status_db).list_merges()


def _classify_guard(settings: Settings) -> None:
    if not settings.classify_enabled:
        raise HTTPException(503, "classify stage disabled")


def require_csrf(x_hinddian: str | None = Header(default=None)) -> None:
    """Mutations need a custom header → cross-site forms/fetch can't send it without CORS."""
    if x_hinddian != "1":
        raise HTTPException(403, "missing X-Hinddian header")


@app.get("/api/classify/stats", dependencies=[Depends(require_auth)])
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


@app.get("/api/gate", dependencies=[Depends(require_auth)])
def batch_gate(settings: Settings = Depends(_settings)) -> dict:
    _classify_guard(settings)
    try:
        return classify_remote.gate()
    except classify_remote.RemoteError as e:
        raise HTTPException(502, str(e)) from e


@app.post("/api/gate/{project}/approve", dependencies=[Depends(require_auth), Depends(require_csrf)])
def batch_approve(project: str, settings: Settings = Depends(_settings)) -> dict:
    _classify_guard(settings)
    try:
        return classify_remote.approve_batch(project)
    except classify_remote.RemoteError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/classify/proposals", dependencies=[Depends(require_auth)])
def classify_proposals(status: str = "pending", settings: Settings = Depends(_settings)) -> list[dict]:
    _classify_guard(settings)
    try:
        return classify_remote.proposals(status)
    except classify_remote.RemoteError as e:
        raise HTTPException(502, str(e)) from e


@app.get("/api/classify/recent", dependencies=[Depends(require_auth)])
def classify_recent(limit: int = 30, settings: Settings = Depends(_settings)) -> list[dict]:
    _classify_guard(settings)
    try:
        return classify_remote.recent(limit)
    except classify_remote.RemoteError as e:
        raise HTTPException(502, str(e)) from e


@app.post("/api/classify/proposals/{pid}/approve", dependencies=[Depends(require_auth), Depends(require_csrf)])
def classify_approve(pid: str, settings: Settings = Depends(_settings)) -> dict:
    _classify_guard(settings)
    try:
        return classify_remote.decide(pid, True)
    except classify_remote.RemoteError as e:
        raise HTTPException(502, str(e)) from e


@app.post("/api/classify/proposals/{pid}/reject", dependencies=[Depends(require_auth), Depends(require_csrf)])
def classify_reject(pid: str, payload: dict = Body(default={}), settings: Settings = Depends(_settings)) -> dict:
    _classify_guard(settings)
    try:
        return classify_remote.decide(pid, False, str(payload.get("reason") or ""))
    except classify_remote.RemoteError as e:
        raise HTTPException(502, str(e)) from e


@app.post("/api/classify/proposals/batch", dependencies=[Depends(require_auth), Depends(require_csrf)])
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


@app.post("/api/classify/proposals/{pid}/restore", dependencies=[Depends(require_auth), Depends(require_csrf)])
def classify_restore(pid: str, settings: Settings = Depends(_settings)) -> dict:
    _classify_guard(settings)
    try:
        return classify_remote.restore(pid)
    except classify_remote.RemoteError as e:
        raise HTTPException(502, str(e)) from e


@app.get("/")
def index() -> FileResponse:
    index_path = WEB_DIR / "index.html"
    if not index_path.is_file():
        raise HTTPException(404, "web/index.html missing")
    return FileResponse(index_path)


if WEB_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
