"""Authenticated API for explicitly submitted drafts."""
from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException

from . import draft_store, note_format
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


@router.post("/push_draft")
def push_draft(payload: dict) -> dict:
    if not isinstance(payload.get("body", ""), str):
        raise HTTPException(422, "body must be a string")
    try:
        return draft_store.save_payload(payload)
    except (ValueError, OSError, note_format.VaultBusy) as exc:
        raise HTTPException(503, "draft storage unavailable") from exc


