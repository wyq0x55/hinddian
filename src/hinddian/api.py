"""Read-only pipeline dashboard and optional HTTP session collector."""
from __future__ import annotations

import hmac
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, hooks_api, jev_log, notes
from .config import get_settings

WEB_DIR = Path(__file__).resolve().parents[2] / "web"
app = FastAPI(title="hinddian", version=__version__, description="hinddian notes pipeline")
app.include_router(hooks_api.router)


def require_dashboard(
    authorization: str | None = Header(default=None),
    x_hinddian_dashboard: str | None = Header(default=None),
) -> None:
    settings = get_settings()
    token = settings.auth_token
    if not token:
        if settings.hinddian_allow_no_auth:
            return
        raise HTTPException(503, "dashboard disabled: set AUTH_TOKEN")
    collector = settings.hinddian_mcp_token
    if collector and hmac.compare_digest(token.encode(), collector.encode()):
        raise HTTPException(503, "AUTH_TOKEN must differ from HINDDIAN_MCP_TOKEN")
    got = hooks_api.bearer(authorization) or (x_hinddian_dashboard or "").strip()
    if not got:
        raise HTTPException(401, "dashboard token required")
    if not hmac.compare_digest(got.encode(), token.encode()):
        raise HTTPException(403, "invalid token")


dash = [Depends(require_dashboard)]


def _soft(fn) -> tuple[Any, str | None]:
    try:
        return fn(), None
    except (OSError, ValueError) as exc:
        return None, str(exc)[:200]


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "service": "hinddian", "version": __version__}


@app.get("/api/overview", dependencies=dash)
def overview() -> dict:
    stats, vault_error = _soft(notes.vault_stats)
    batch, draft_error = _soft(notes.batch_status)
    projects = (batch or {}).get("projects", [])
    return {
        "version": __version__,
        "vault": {"ok": vault_error is None, "error": vault_error,
                  **(stats or dict.fromkeys(("projects", "decisions", "lessons", "tips"), 0))},
        "drafts": {"ok": draft_error is None, "error": draft_error,
                   "total": sum(project["drafts"] for project in projects),
                   "processed": sum(project["processed"] for project in projects)},
    }


@app.get("/api/batch", dependencies=dash)
def batch_status() -> dict:
    data, error = _soft(notes.batch_status)
    if error:
        raise HTTPException(503, error)
    return data


@app.get("/api/drafts", dependencies=dash)
def list_session_drafts(project: str | None = None, status: str = "pending", limit: int = 100) -> list[dict]:
    status = status.lower()
    if status not in ("pending", "processed", "all"):
        raise HTTPException(400, "status must be pending|processed|all")
    return notes.list_drafts(project=project or None, status=status, limit=limit)


@app.get("/api/draft", dependencies=dash)
def session_draft(id: str) -> dict:
    draft = notes.get_draft(id)
    if not draft:
        raise HTTPException(404, "draft not found")
    return draft


@app.get("/api/jev-decisions", dependencies=dash)
def jev_decisions(limit: int = 100) -> dict:
    return {"items": jev_log.recent(max(1, min(int(limit), 500))), "summary": jev_log.summary()}


@app.get("/", dependencies=dash)
def index() -> FileResponse:
    index_path = WEB_DIR / "index.html"
    if not index_path.is_file():
        raise HTTPException(404, "web/index.html missing")
    return FileResponse(index_path, headers={"Cache-Control": "no-cache"})


if WEB_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
