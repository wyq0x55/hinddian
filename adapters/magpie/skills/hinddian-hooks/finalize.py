"""Finalize a session buffer → Jev keep → one push_draft (or discard).

Transient failures (Jev unreachable, server down) keep the buffer and retry with backoff —
"no loose auto-keep" means *don't write yet*, not *throw the session away*.

CLI (spawned detached by the hooks):  finalize.py [--current SID]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import extract  # noqa: E402
import hookcfg  # noqa: E402
import jev  # noqa: E402
import session_buf  # noqa: E402

req = hookcfg.req


def projects_list() -> list[str]:
    try:
        g = req("GET", "/api/memory/routing/global", timeout=12)
        return [p.get("name") for p in (g.get("projects") or []) if p.get("name")]
    except Exception:
        return []


def _norm_source(src: str | None) -> str:
    s = str(src or "")
    if s.startswith("jev:local") or s in ("magpie", "local") or (s.startswith("jev:") and ("magpie" in s or "local" in s)):
        return "jev:local"
    if s.startswith("jev:cloud") or s in ("cloud", "typesafe-cloud") or (s.startswith("jev:") and "cloud" in s):
        return "jev:cloud"
    return s if s.startswith("jev:") else "none"


def _classify(corpus: str, projects: list[str]) -> dict:
    """Local Jev first, then the server's gate. Raises if neither answers."""
    try:
        r = jev.classify_turn(corpus, projects)
        return {"ok": r.ok, "value": r.value, "confidence": r.confidence, "source": r.source, "error": r.error}
    except Exception as e:
        try:
            return req("POST", "/api/memory/gates/classify_turn", {"turn": corpus}, timeout=60)
        except Exception as e2:
            raise RuntimeError(f"{type(e).__name__}:{e}; remote:{e2}") from e2


def _done(sid: str, reason: str, outcome: str, **extra) -> dict:
    session_buf.mark_finalized(sid, outcome)
    return {"ok": True, "skipped": outcome, "session_id": sid, "reason": reason, **extra}


def _later(sid: str, reason: str, error: str, **extra) -> dict:
    d = session_buf.defer(sid, error)
    return {"ok": False, "deferred": not d["gave_up"], **d, "session_id": sid, "reason": reason, "error": error[:200], **extra}


def _body(val: dict, title: str, typ: str) -> str:
    decisions = val.get("decision") or []
    lessons = val.get("lesson") or []
    preferences = val.get("preference") or []
    if decisions or lessons or preferences:
        # push_draft writes the "# title" heading itself
        return extract.structured_body(decisions=decisions, lessons=lessons, preferences=preferences)
    nl = "\n"
    block = f"### {title}{nl}- 场景：{val.get('scene') or ''}{nl}- 做法：{val.get('practice') or ''}{nl}- 理由：{val.get('reason') or ''}{nl}"
    if typ == "decision":
        return f"## DECISIONS{nl}{block}{nl}## LESSONS{nl}{nl}## PREFERENCES{nl}"
    if typ == "preference":
        return f"## DECISIONS{nl}{nl}## LESSONS{nl}{nl}## PREFERENCES{nl}{block}"
    return f"## DECISIONS{nl}{nl}## LESSONS{nl}{block}{nl}## PREFERENCES{nl}"


def finalize_buffer(buf: dict, *, reason: str) -> dict:
    sid = buf.get("session_id") or ""
    corpus = session_buf.session_corpus(buf)
    if not corpus.strip():
        return _done(sid, reason, "empty", source="none")

    try:
        klass = _classify(session_buf.clip(corpus), projects_list())
    except RuntimeError as e:
        return _later(sid, reason, f"jev_unavailable: {e}", source="none")

    src_raw = str(klass.get("source") or "none")
    if src_raw.startswith("llm"):
        return _done(sid, reason, "llm_forbidden", source="none")
    src = _norm_source(src_raw)
    if src == "none":
        return _later(sid, reason, f"jev_unavailable: {klass.get('error')}", source="none")

    val = klass.get("value") or {}
    if not isinstance(val, dict) or not val.get("keep"):
        return _done(sid, reason, "keep_false", source=src, confidence=klass.get("confidence"), error=klass.get("error"))

    title = val.get("title") or val.get("summary") or f"session-{sid[:12]}"
    typ = val.get("type") or "lesson"
    payload = {
        "project": val.get("project") or buf.get("project") or "通用-未定",
        "title": title,
        "body": _body(val, title, typ),
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
    except Exception as e:
        return _later(sid, reason, f"push_failed: {e}", source=src)
    session_buf.mark_finalized(sid, "pushed")
    return {"ok": True, "pushed": out, "source": src, "session_id": sid, "reason": reason}


def finalize_idle_and_others(*, current_sid: str | None = None, project: str | None = None) -> list[dict]:
    """Finalize open buffers that are not the active session, or idle, or project-switched."""
    results: list[dict] = []
    now = time.time()
    for buf in session_buf.list_open():
        sid = buf.get("session_id")
        if not session_buf.due(buf, now):
            continue
        is_current = bool(current_sid and sid == current_sid)
        idle = now - float(buf.get("updated_at") or 0) >= session_buf.IDLE_SEC
        switched = bool(is_current and project and session_buf.project_switched(buf, project))
        if is_current and not idle and not switched:
            continue
        if is_current and switched:
            reason = "project-switch"
        elif current_sid and not is_current:
            reason = "session-start"
        else:
            reason = "idle"
        with session_buf.claim(sid) as mine:
            if mine:
                results.append(finalize_buffer(buf, reason=reason))
    return results


def main(argv: list[str]) -> None:
    current = argv[argv.index("--current") + 1] if "--current" in argv and argv.index("--current") + 1 < len(argv) else None
    if hookcfg.transport_problem():
        print(json.dumps({"skipped": hookcfg.transport_problem()}, ensure_ascii=False))
        return
    results = finalize_idle_and_others(current_sid=current)
    pruned = session_buf.prune()
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    print(json.dumps({"at": stamp, "finalized": results, "pruned": pruned}, ensure_ascii=False)[:4000])


if __name__ == "__main__":
    main(sys.argv[1:])
