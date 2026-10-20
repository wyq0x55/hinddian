"""Finalize a session buffer → Jev keep → one push_draft (or discard).

Transient failures (Jev unreachable, server down) keep the buffer and retry with backoff —
"no loose auto-keep" means *don't write yet*, not *throw the session away*.

CLI (spawned detached by the hooks):  finalize.py [--current SID]
"""
from __future__ import annotations

import json
import os
import socket
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


UNKNOWN_PROJECT = "通用-未定"


def repo_root(cwd: str) -> Path | None:
    """Nearest enclosing git work tree of cwd (the session's directory on this machine)."""
    try:
        p = Path(cwd).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    home = Path.home()
    for d in (p, *p.parents):
        if d == home or d == d.parent:
            return None
        if (d / ".git").exists():
            return d
    return None


def pick_project(cwd: str, jev_project: str | None, projects: list[str]) -> str:
    """Where the session's draft goes. The directory beats the text: an existing project named
    in the path, else the enclosing git repo (a new project accumulates drafts and waits for
    approval in the dashboard), else what Jev read from the text, else 通用-未定 (tips only)."""
    low = (cwd or "").lower()
    hits = [p for p in projects if p and p.lower() in low]
    if hits:
        return max(hits, key=len)
    root = repo_root(cwd) if cwd else None
    if root:
        same = [p for p in projects if p.lower() == root.name.lower()]
        return same[0] if same else root.name
    if jev_project and jev_project != UNKNOWN_PROJECT:
        return jev_project
    return UNKNOWN_PROJECT


def _classify(corpus: str, projects: list[str], cwd: str = "") -> dict:
    """Local Jev first, then the server's gate. Raises if neither answers."""
    try:
        r = jev.classify_turn(corpus, projects, cwd)
        return {"ok": r.ok, "value": r.value, "confidence": r.confidence, "source": r.source, "error": r.error}
    except Exception as e:
        try:
            return req("POST", "/api/memory/gates/classify_turn", {"turn": corpus, "cwd": cwd}, timeout=60)
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


def _finalize_buffer(buf: dict, *, reason: str) -> dict:
    sid = buf.get("session_id") or ""
    corpus = session_buf.session_corpus(buf)
    if not corpus.strip():
        return _done(sid, reason, "empty", source="none")

    projects = projects_list()
    try:
        klass = _classify(session_buf.clip(corpus), projects, buf.get("cwd") or "")
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
        return _done(sid, reason, "keep_false", keep=False, source=src, confidence=klass.get("confidence"), error=klass.get("error"))

    title = val.get("title") or val.get("summary") or f"session-{sid[:12]}"
    typ = val.get("type") or "lesson"
    payload = {
        "project": buf.get("project") or pick_project(buf.get("cwd") or "", val.get("project"), projects),
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
        return _later(sid, reason, f"push_failed: {e}", source=src, keep=True, confidence=klass.get("confidence"))
    session_buf.mark_finalized(sid, "pushed")
    draft = out.get("path") or out.get("id") if isinstance(out, dict) else None
    return {"ok": True, "pushed": out, "source": src, "keep": True, "confidence": klass.get("confidence"),
            "session_id": sid, "reason": reason, "draft_path": draft}


REPORT_TIMEOUT = 4.0


def client_id() -> str:
    cid = os.environ.get("HINDDIAN_CLIENT_ID") or str(hookcfg.load_config().get("client_id") or "")
    return (cid.strip() or socket.gethostname() or "unknown")[:64]


def report_decision(buf: dict, result: dict, *, reason: str) -> None:
    """Tell the dashboard what Jev decided (metadata only, never turn text). Fire-and-forget:
    any failure is swallowed so reporting can never block or break finalize."""
    try:
        if not hookcfg.flag("HINDDIAN_REPORT_JEV", True):
            return
        conf = result.get("confidence")
        body = {
            "session_id": str(buf.get("session_id") or "")[:128],
            "project": str(buf.get("project") or "")[:128] or None,
            "cwd": os.path.basename(str(buf.get("cwd") or "").rstrip("/\\"))[:128] or None,
            "host": client_id(),
            "event": "finalize",
            "finalize_reason": reason,
            "jev_source": str(result.get("source") or "none"),
            "keep": result.get("keep"),
            "confidence": conf if isinstance(conf, (int, float)) else None,
            "outcome": str(result.get("skipped") or ("pushed" if result.get("pushed") else ("deferred" if result.get("deferred") else "gave_up" if result.get("gave_up") else "")))[:40],
            "error": str(result.get("error") or "")[:200] or None,
            "turn_count": len(buf.get("turns") or []),
            "pushed": bool(result.get("pushed")),
            "draft_path": str(result.get("draft_path") or "")[:256] or None,
            "ts": time.time(),
        }
        req("POST", "/api/memory/gates/report", body, timeout=REPORT_TIMEOUT)
    except Exception:
        pass


def finalize_buffer(buf: dict, *, reason: str) -> dict:
    try:
        result = _finalize_buffer(buf, reason=reason)
    except Exception as e:
        report_decision(buf, {"source": "none", "error": f"finalize_error: {type(e).__name__}: {e}"}, reason=reason)
        raise
    report_decision(buf, result, reason=reason)
    return result


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
