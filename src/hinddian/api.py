"""FastAPI: health + pipeline observability endpoints + static dashboard."""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import Settings, get_settings
from .models import DistillJob, FilterResult, InboxItem, MergeEvent, PipelineStats, TopicDocStatus
from .store import (
    StatusStore,
    build_topic_statuses,
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


@app.on_event("startup")
def _startup() -> None:
    settings = get_settings()
    settings.status_db.parent.mkdir(parents=True, exist_ok=True)
    seed_demo_if_empty(settings)


@app.get("/api/health")
def health(settings: Settings = Depends(_settings)) -> dict:
    return {
        "ok": True,
        "service": "hinddian",
        "version": __version__,
        "demo": settings.use_demo_data,
        "vault_root": str(settings.vault_root),
        "inbox_dir": str(settings.inbox_dir),
    }


@app.get("/api/stats", response_model=PipelineStats, dependencies=[Depends(require_auth)])
def stats(settings: Settings = Depends(_settings)) -> PipelineStats:
    seed_demo_if_empty(settings)
    real = compute_stats(settings)
    # If inbox path missing and demo on, show demo stats overlay for empty dirs
    if settings.use_demo_data and real.inbox_count == 0 and not settings.inbox_dir.is_dir():
        d = demo_stats()
        # Prefer real job counts from seeded DB
        d.jobs_pending = real.jobs_pending or d.jobs_pending
        d.jobs_running = real.jobs_running or d.jobs_running
        d.jobs_done = real.jobs_done or d.jobs_done
        d.jobs_failed = real.jobs_failed or d.jobs_failed
        d.pending_ingests = real.pending_ingests or d.pending_ingests
        d.topics_tracked = max(real.topics_tracked, d.topics_tracked)
        return d
    return real


@app.get("/api/inbox", response_model=list[InboxItem], dependencies=[Depends(require_auth)])
def inbox(settings: Settings = Depends(_settings)) -> list[InboxItem]:
    items = scan_inbox(settings)
    if not items and settings.use_demo_data:
        return demo_inbox()
    return items


@app.get("/api/jobs", response_model=list[DistillJob], dependencies=[Depends(require_auth)])
def jobs(settings: Settings = Depends(_settings)) -> list[DistillJob]:
    seed_demo_if_empty(settings)
    return StatusStore(settings.status_db).list_jobs()


@app.get("/api/filters", response_model=list[FilterResult], dependencies=[Depends(require_auth)])
def filters(settings: Settings = Depends(_settings)) -> list[FilterResult]:
    seed_demo_if_empty(settings)
    return StatusStore(settings.status_db).filter_results()


@app.get("/api/topics", response_model=list[TopicDocStatus], dependencies=[Depends(require_auth)])
def topics(settings: Settings = Depends(_settings)) -> list[TopicDocStatus]:
    seed_demo_if_empty(settings)
    real = build_topic_statuses(settings)
    if len(real) <= 1 and settings.use_demo_data and not settings.vault_root.is_dir():
        return demo_topics()
    # Always ensure agent tips appears
    if not any(t.document_id == "topic/agent-usage-tips" for t in real):
        real = demo_topics()[:1] + real
    return real


@app.get("/api/merges", response_model=list[MergeEvent], dependencies=[Depends(require_auth)])
def merges(settings: Settings = Depends(_settings)) -> list[MergeEvent]:
    seed_demo_if_empty(settings)
    return StatusStore(settings.status_db).list_merges()


@app.get("/")
def index() -> FileResponse:
    index_path = WEB_DIR / "index.html"
    if not index_path.is_file():
        raise HTTPException(404, "web/index.html missing")
    return FileResponse(index_path)


if WEB_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
