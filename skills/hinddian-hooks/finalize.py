"""Finalize a session buffer → POST it to the server, which runs Jev and push_draft.

Jev runs on the hinddian server (POST /api/memory/finalize); the hook never calls Jev itself and
needs no JEV_BASE_URL. Server unreachable / Jev unavailable there → keep the buffer and retry
with backoff — "no loose auto-keep" means *don't write yet*, not *throw the session away*.

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

import hookcfg  # noqa: E402
import session_buf  # noqa: E402

req = hookcfg.req
FINALIZE_TIMEOUT = 120.0


def repo_root(cwd: str) -> Path | None:
    """Nearest enclosing git work tree of cwd (only its basename is sent to the server)."""
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


def client_id() -> str:
    cid = os.environ.get("HINDDIAN_CLIENT_ID") or str(hookcfg.load_config().get("client_id") or "")
    return (cid.strip() or socket.gethostname() or "unknown")[:64]


def _base(p: str) -> str | None:
    return os.path.basename(str(p or "").rstrip("/\\"))[:128] or None


def payload(buf: dict, *, reason: str) -> dict:
    """Whitelisted turn text only (session_buf already stored user + final assistant turns, with
    <private> blocks redacted); cwd and repo are sent as basenames, never full paths."""
    cwd = str(buf.get("cwd") or "")
    root = repo_root(cwd) if cwd else None
    turns = buf.get("turns") or []
    return {
        "session_id": str(buf.get("session_id") or "")[:128],
        "project": str(buf.get("project") or "")[:128] or None,
        "cwd": _base(cwd),
        "repo": root.name[:128] if root else None,
        "client_id": client_id(),
        "finalize_reason": reason,
        "turn_count": len(turns),
        "turns": [{"text": session_buf.clip(str(t.get("text") or ""), 20000, 6000)} for t in turns if (t.get("text") or "").strip()],
    }


def finalize_buffer(buf: dict, *, reason: str) -> dict:
    sid = buf.get("session_id") or ""
    if not session_buf.session_corpus(buf).strip():
        session_buf.mark_finalized(sid, "empty")
        return {"ok": True, "skipped": "empty", "session_id": sid, "reason": reason}
    try:
        out = req("POST", "/api/memory/finalize", payload(buf, reason=reason), timeout=FINALIZE_TIMEOUT)
    except Exception as e:  # server unreachable / 5xx: keep the buffer, retry next finalize
        err = f"server_unreachable: {type(e).__name__}: {str(e)[:120]}"
        d = session_buf.defer(sid, err)
        return {"ok": False, "deferred": not d["gave_up"], **d, "session_id": sid, "reason": reason, "error": err}
    out = out if isinstance(out, dict) else {}
    if out.get("retry"):
        err = str(out.get("error") or out.get("outcome") or "retry")[:200]
        d = session_buf.defer(sid, err)
        return {"ok": False, "deferred": not d["gave_up"], **d, "session_id": sid, "reason": reason, "error": err,
                "source": out.get("source")}
    outcome = str(out.get("outcome") or "done")
    session_buf.mark_finalized(sid, outcome)
    res = {"ok": True, "session_id": sid, "reason": reason, "source": out.get("source"), "keep": out.get("keep"),
           "outcome": outcome, "draft_path": out.get("draft_path")}
    if outcome == "pushed":
        res["pushed"] = True
    else:
        res["skipped"] = outcome
    return res


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
