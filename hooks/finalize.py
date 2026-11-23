"""Finalize a session buffer with local Jev and draft storage, or send it to the HTTP collector.

Keep the buffer and retry with backoff if Jev or the collector is unavailable.

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
import draft_store  # noqa: E402
import note_format as nf  # noqa: E402
import paths  # noqa: E402
import session_finalize  # noqa: E402
from hook_runtime import quiet, record  # noqa: E402

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
    texts = [session_buf.clip(nf.redact(str(turn.get("text") or "")), 19000, 6000)
             for turn in turns if (turn.get("text") or "").strip()]
    if len(texts) > session_finalize.MAX_TURNS or sum(map(len, texts)) > session_finalize.MAX_TOTAL_CHARS:
        texts = [session_finalize.clip("\n\n---\n\n".join(texts))]
    return {
        "session_id": str(buf.get("session_id") or ""),
        "project": str(buf.get("project") or "")[:128] or None,
        "cwd": _base(cwd),
        "repo": root.name[:128] if root else None,
        "client_id": client_id(),
        "finalize_reason": reason,
        "turn_count": len(turns),
        "turns": [{"text": text} for text in texts],
    }


def finalize_buffer(buf: dict, *, reason: str) -> dict:
    sid = buf.get("session_id") or ""
    mode = hookcfg.capture_mode()
    try:
        args = payload(buf, reason=reason)
        if not args["turns"]:
            out = {"outcome": "empty"}
        elif mode == "http":
            out = req("POST", "/api/memory/finalize", args, timeout=FINALIZE_TIMEOUT)
        elif mode == "local":
            out = session_finalize.finalize(
                args, projects=lambda: draft_store.project_names(paths.vault_dir()),
                push=draft_store.save_payload, mode="local",
            )
        else:
            raise ValueError("unknown capture mode")
    except Exception as e:
        label = "server_unreachable" if mode == "http" else "finalize_failed"
        out = {"retry": True, "error": f"{label}: {type(e).__name__}"}
    if not isinstance(out, dict) or not (out.get("retry") or out.get("outcome")):
        out = {"retry": True, "error": "invalid finalize response"}
    with session_buf.claim(sid, kind="state") as acquired:
        if not acquired:
            record("lock_busy", entry="finalize")
            return {"ok": True, "skipped": "lock_busy", "session_id": sid, "reason": reason}
        current = session_buf.load(sid)
        if not current or current.get("updated_at") != buf.get("updated_at") or current.get("finalized"):
            return {"ok": True, "skipped": "buffer_changed", "session_id": sid, "reason": reason}
        return _settle(sid, reason, out)


def _settle(sid: str, reason: str, out: dict) -> dict:
    if out.get("retry"):
        record("finalize_retry")
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


def finalize_idle_and_others(*, current_sid: str | None = None) -> list[dict]:
    """Finalize idle buffers and buffers outside the active session."""
    results: list[dict] = []
    now = time.time()
    for buf in session_buf.list_open():
        sid = buf.get("session_id")
        if not session_buf.due(buf, now):
            continue
        is_current = bool(current_sid and sid == current_sid)
        idle = now - float(buf.get("updated_at") or 0) >= session_buf.IDLE_SEC
        if is_current and not idle:
            continue
        if current_sid and not is_current:
            reason = "session-start"
        else:
            reason = "idle"
        with session_buf.claim(sid) as mine:
            if mine and (fresh := session_buf.load(sid)) and not fresh.get("finalized") and session_buf.due(fresh):
                if is_current and reason == "idle" and time.time() - float(fresh.get("updated_at") or 0) < session_buf.IDLE_SEC:
                    continue
                results.append(finalize_buffer(fresh, reason=reason))
    return results


@quiet
def main(argv: list[str]) -> None:
    current = argv[argv.index("--current") + 1] if "--current" in argv and argv.index("--current") + 1 < len(argv) else None
    if why := hookcfg.capture_problem():
        print(json.dumps({"skipped": why}, ensure_ascii=False))
        return
    results = finalize_idle_and_others(current_sid=current)
    pruned = session_buf.prune()
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    print(json.dumps({"at": stamp, "finalized": results, "pruned": pruned}, ensure_ascii=False)[:4000])


if __name__ == "__main__":
    main(sys.argv[1:])
