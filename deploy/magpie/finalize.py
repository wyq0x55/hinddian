"""Finalize a session buffer → Jev keep → one push_draft (or discard)."""
from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Any

import extract
import jev
import session_buf

URL = os.environ.get("HINDDIAN_MEMORY_URL", "http://124.70.90.224/hinddian").rstrip("/")
TOKEN = os.environ.get("HINDDIAN_MCP_TOKEN") or os.environ.get("HINDSIGHT_API_KEY") or ""


def req(method: str, path: str, body: Any = None, timeout: float = 45) -> Any:
    headers = {"Accept": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode()
    r = urllib.request.Request(URL + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read())


def projects_list() -> list[str]:
    try:
        g = req("GET", "/api/memory/routing/global", timeout=12)
        return [p.get("name") for p in (g.get("projects") or []) if p.get("name")]
    except Exception:
        return []


def _norm_source(src: str | None) -> str:
    s = str(src or "")
    if s.startswith("jev:magpie") or s == "magpie":
        return "jev:magpie"
    if s.startswith("jev:cloud") or s in ("cloud", "typesafe-cloud", "jev:typesafe-cloud"):
        return "jev:cloud"
    if s.startswith("jev:"):
        # unknown jev label — keep prefix
        return s if s in ("jev:magpie", "jev:cloud") else ("jev:magpie" if "magpie" in s else "jev:cloud" if "cloud" in s else s)
    return "none"


def finalize_buffer(buf: dict, *, reason: str) -> dict:
    sid = buf.get("session_id") or ""
    corpus = session_buf.session_corpus(buf)
    if not corpus.strip():
        session_buf.mark_finalized(sid)
        return {"ok": True, "skipped": "empty", "session_id": sid, "reason": reason, "source": "none"}

    projects = projects_list()
    try:
        klass_r = jev.classify_turn(corpus[:12000], projects)
        klass = {
            "ok": klass_r.ok,
            "value": klass_r.value,
            "confidence": klass_r.confidence,
            "source": klass_r.source,
            "error": klass_r.error,
        }
    except Exception as e:
        try:
            klass = req("POST", "/api/memory/gates/classify_turn", {"turn": corpus[:12000]}, timeout=60)
        except Exception as e2:
            session_buf.mark_finalized(sid)
            return {
                "ok": True,
                "skipped": "jev_unavailable",
                "source": "none",
                "session_id": sid,
                "reason": reason,
                "error": f"{type(e).__name__}:{e}; remote:{e2}"[:200],
            }

    src_raw = klass.get("source") or "none"
    if src_raw == "llm" or str(src_raw).startswith("llm"):
        session_buf.mark_finalized(sid)
        return {"ok": True, "skipped": "llm_forbidden", "source": "none", "session_id": sid, "reason": reason}

    val = klass.get("value") or {}
    if not isinstance(val, dict) or not val.get("keep"):
        session_buf.mark_finalized(sid)
        return {
            "ok": True,
            "skipped": "keep_false",
            "source": _norm_source(src_raw) if klass.get("ok") else "none",
            "session_id": sid,
            "reason": reason,
            "confidence": klass.get("confidence"),
            "error": klass.get("error"),
        }

    if not klass.get("ok") and _norm_source(src_raw) == "none":
        session_buf.mark_finalized(sid)
        return {"ok": True, "skipped": "jev_unavailable", "source": "none", "session_id": sid, "reason": reason}

    title = val.get("title") or val.get("summary") or f"session-{sid[:12]}"
    typ = val.get("type") or "lesson"
    project = val.get("project") or buf.get("project") or "通用-未定"
    decisions = val.get("decision") or []
    lessons = val.get("lesson") or []
    preferences = val.get("preference") or []
    if not decisions and not lessons and not preferences:
        scene = val.get("scene") or ""
        practice = val.get("practice") or ""
        reason_s = val.get("reason") or ""
        nl = "\n"
        block = f"### {title}{nl}- 场景：{scene}{nl}- 做法：{practice}{nl}- 理由：{reason_s}{nl}"
        if typ == "decision":
            body = f"## DECISIONS{nl}{block}{nl}## LESSONS{nl}{nl}## PREFERENCES{nl}"
        elif typ == "preference":
            body = f"## DECISIONS{nl}{nl}## LESSONS{nl}{nl}## PREFERENCES{nl}{block}"
        else:
            body = f"## DECISIONS{nl}{nl}## LESSONS{nl}{block}{nl}## PREFERENCES{nl}"
    else:
        body = extract.structured_body(
            decisions=decisions, lessons=lessons, preferences=preferences, title=title
        )

    src = _norm_source(src_raw)
    if src == "none":
        session_buf.mark_finalized(sid)
        return {"ok": True, "skipped": "jev_unavailable", "source": "none", "session_id": sid, "reason": reason}

    payload = {
        "project": project,
        "title": title,
        "body": body,
        "type": typ,
        "confidence": klass.get("confidence"),
        "origin": f"session-finalize:{reason}:{src}",
        "session_id": sid,
        "jev_source": src,
        "turn_count": len(buf.get("turns") or []),
        "finalize_reason": reason,
    }
    try:
        out = req("POST", "/api/memory/push_draft", payload, timeout=30)
        session_buf.mark_finalized(sid)
        return {"ok": True, "pushed": out, "source": src, "session_id": sid, "reason": reason}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "session_id": sid, "source": src, "reason": reason}


def finalize_idle_and_others(*, current_sid: str | None = None, project: str | None = None) -> list[dict]:
    """Finalize open buffers that are not the active session, or idle, or project-switched."""
    results: list[dict] = []
    now = time.time()
    idle_sec = session_buf.IDLE_SEC
    for buf in session_buf.list_open():
        sid = buf.get("session_id")
        is_current = bool(current_sid and sid == current_sid)
        age = now - float(buf.get("updated_at") or 0)
        idle = age >= idle_sec
        switched = bool(is_current and project and session_buf.project_switched(buf, project))
        if is_current and not idle and not switched:
            continue
        if is_current and switched:
            reason = "project-switch"
        elif is_current and idle:
            reason = "idle"
        elif current_sid and not is_current:
            reason = "session-start"
        else:
            reason = "idle"
        results.append(finalize_buffer(buf, reason=reason))
    return results
