"""Authenticated HTTP fallback for session capture."""
from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException

from . import draft_store, jev, jev_log, note_format, paths, session_finalize
from .config import get_settings


def bearer(authorization: str | None) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def require_collector(authorization: str | None = Header(default=None)) -> None:
    settings = get_settings()
    token = settings.hinddian_mcp_token
    if not token:
        if settings.hinddian_allow_no_auth:
            return
        raise HTTPException(503, "HINDDIAN_MCP_TOKEN not configured")
    got = bearer(authorization)
    if not got:
        raise HTTPException(401, "Bearer required")
    if not hmac.compare_digest(got.encode(), token.encode()):
        raise HTTPException(403, "invalid token")


router = APIRouter(prefix="/api/memory", dependencies=[Depends(require_collector)])


def _project_names() -> list[str]:
    return draft_store.project_names(paths.vault_dir())


@router.post("/finalize")
def finalize_session(payload: dict) -> dict:
    try:
        return session_finalize.finalize(payload, projects=_project_names, push=draft_store.save_payload)
    except session_finalize.FinalizeError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/push_draft")
def push_draft(payload: dict) -> dict:
    if not isinstance(payload.get("body", ""), str):
        raise HTTPException(422, "body must be a string")
    try:
        return draft_store.save_payload(payload)
    except (ValueError, OSError, note_format.VaultBusy) as exc:
        raise HTTPException(503, "draft storage unavailable") from exc


@router.get("/gates/backend")
@router.get("/jev-backend")
def jev_backend() -> dict:
    return jev.backend_info()


@router.post("/gates/classify_turn")
def classify_turn(payload: dict) -> dict:
    text = note_format.redact(str(payload.get("turn") or payload.get("text") or ""))
    cwd = note_format.redact(str(payload.get("cwd") or ""))
    result = jev.classify_turn(text, [note_format.redact(name) for name in _project_names()], cwd)
    return {"ok": result.ok, "value": result.value, "confidence": result.confidence,
            "source": result.source, "error": result.error}


@router.post("/gates/report")
def report(payload: dict) -> dict:
    try:
        record = jev_log.validate(payload)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        jev_log.append(record)
    except (OSError, note_format.VaultBusy) as exc:
        raise HTTPException(503, "jev log unavailable") from exc
    return {"ok": True}
