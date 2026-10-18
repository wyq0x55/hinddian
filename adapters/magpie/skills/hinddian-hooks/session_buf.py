"""Local session draft buffer (one host session → one push_draft).

Many hosts expose session-start + turn-end only (no portable session-end).
Strategy:
  - turn-end: append whitelisted turn into buffer for session_id (no remote write)
  - session-start: finalize any *other* open session buffer → Jev keep → push_draft
  - turn-end also finalizes buffers idle longer than IDLE_SEC
"""
from __future__ import annotations

import json
import os
import time
import hashlib
from pathlib import Path
from typing import Any

IDLE_SEC = int(os.environ.get("HINDDIAN_SESSION_IDLE_SEC", "1800"))  # 30 min


def _cfg_root() -> Path:
    home = Path.home()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    cfg = Path(xdg) if xdg else (home / ".config")
    return Path(os.environ.get("HINDDIAN_MAGPIE_HOOK_DIR") or (cfg / "magpie" / "hinddian-hooks"))


def sessions_dir() -> Path:
    d = _cfg_root() / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def stable_session_id(explicit: str | None, cwd: str = "", seed: str = "") -> str:
    if explicit and str(explicit).strip():
        return str(explicit).strip()[:120]
    base = (cwd or "") + "|" + (seed or "")[:200]
    if not base.strip("|"):
        base = f"anon-{int(time.time() // 3600)}"
    return "sid-" + hashlib.sha1(base.encode()).hexdigest()[:16]


def _path(sid: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in sid)[:100]
    return sessions_dir() / f"{safe}.json"


def load(sid: str) -> dict[str, Any] | None:
    p = _path(sid)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def save(buf: dict[str, Any]) -> Path:
    sid = buf["session_id"]
    p = _path(sid)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(buf, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)
    return p


def append_turn(
    *,
    session_id: str,
    turn_text: str,
    cwd: str = "",
    project_hint: str | None = None,
) -> dict[str, Any]:
    text = (turn_text or "").strip()
    now = time.time()
    buf = load(session_id) or {
        "session_id": session_id,
        "cwd": cwd or "",
        "project": project_hint,
        "created_at": now,
        "updated_at": now,
        "turns": [],
        "finalized": False,
    }
    if buf.get("finalized"):
        # reopen for more turns in same session (unusual but ok)
        buf["finalized"] = False
    if cwd and not buf.get("cwd"):
        buf["cwd"] = cwd
    if project_hint:
        buf["project"] = project_hint
    if text:
        # de-dupe identical last turn
        turns = buf.setdefault("turns", [])
        if not turns or turns[-1].get("text") != text:
            turns.append({"at": now, "text": text})
    buf["updated_at"] = now
    save(buf)
    return buf


def list_open() -> list[dict[str, Any]]:
    out = []
    for p in sessions_dir().glob("*.json"):
        try:
            b = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if b.get("finalized"):
            continue
        if b.get("turns"):
            out.append(b)
    return out


def mark_finalized(sid: str) -> None:
    buf = load(sid)
    if not buf:
        return
    buf["finalized"] = True
    buf["finalized_at"] = time.time()
    save(buf)


def session_corpus(buf: dict[str, Any]) -> str:
    parts = []
    for t in buf.get("turns") or []:
        tx = (t.get("text") or "").strip()
        if tx:
            parts.append(tx)
    return "\n\n---\n\n".join(parts)


def idle_sessions(now: float | None = None) -> list[dict[str, Any]]:
    now = now if now is not None else time.time()
    return [b for b in list_open() if (now - float(b.get("updated_at") or 0)) >= IDLE_SEC]


def project_switched(buf: dict[str, Any], new_project: str | None) -> bool:
    old = (buf.get("project") or "").strip()
    new = (new_project or "").strip()
    return bool(old and new and old != new)
