"""Local session draft buffer (one host session → one push_draft).

Many hosts expose session-start + turn-end only (no portable session-end).
Strategy:
  - turn-end: append whitelisted turn into buffer for session_id (no remote write)
  - session-start: finalize any *other* open session buffer → Jev keep → push_draft
  - turn-end also finalizes buffers idle longer than IDLE_SEC
  - a finalize that couldn't reach Jev / the server stays pending and is retried with backoff
  - finalized buffers (plain conversation text) are deleted after RETAIN_SEC
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Iterator

IDLE_SEC = int(os.environ.get("HINDDIAN_SESSION_IDLE_SEC", "1800"))  # 30 min
RETAIN_SEC = int(os.environ.get("HINDDIAN_BUFFER_RETAIN_SEC", str(3 * 86400)))
MAX_ATTEMPTS = int(os.environ.get("HINDDIAN_FINALIZE_MAX_ATTEMPTS", "8"))
MAX_AGE_SEC = int(os.environ.get("HINDDIAN_FINALIZE_MAX_AGE_SEC", str(7 * 86400)))
LOCK_STALE_SEC = 900


def _cfg_home() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return Path(xdg) if xdg else (Path.home() / ".config")


def hook_dir() -> Path:
    env = os.environ.get("HINDDIAN_HOOK_DIR") or os.environ.get("HINDDIAN_MAGPIE_HOOK_DIR")
    return Path(env) if env else (_cfg_home() / "hinddian" / "hooks")


def sessions_dir() -> Path:
    d = hook_dir() / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    legacy = _cfg_home() / "magpie" / "hinddian-hooks" / "sessions"
    if legacy.is_dir() and legacy.resolve() != d.resolve():
        for p in legacy.glob("*.json"):  # one-time move from the pre-0.6 location
            with contextlib.suppress(OSError):
                if not (d / p.name).exists():
                    shutil.move(str(p), d / p.name)
    return d


def stable_session_id(explicit: str | None, cwd: str = "", seed: str = "") -> str:
    if explicit and str(explicit).strip():
        return str(explicit).strip()[:120]
    base = (cwd or "") + "|" + (seed or "")[:200]
    if not base.strip("|"):
        base = f"anon-{int(time.time() // 3600)}"
    return "sid-" + hashlib.sha1(base.encode()).hexdigest()[:16]


def _path(sid: str) -> Path:
    return side_file(sid, "json")


def side_file(sid: str, kind: str) -> Path:
    """Per-session file next to the buffer: <sid>.json (buffer), <sid>.recalled.json, <sid>.project."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in sid)[:100]
    return sessions_dir() / f"{safe}.{kind}"


def load(sid: str) -> dict[str, Any] | None:
    p = _path(sid)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save(buf: dict[str, Any]) -> Path:
    p = _path(buf["session_id"])
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(buf, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with contextlib.suppress(OSError):
        os.chmod(tmp, 0o600)
    tmp.replace(p)
    return p


PRIVATE = re.compile(r"<private>.*?(?:</private>|\Z)", re.S | re.I)


def strip_private(text: str) -> str:
    """<private>…</private> is never buffered, recalled on, or sent anywhere. Unclosed → to the end."""
    return PRIVATE.sub("[private]", text or "")


def append_turn(
    *,
    session_id: str,
    turn_text: str,
    cwd: str = "",
    project_hint: str | None = None,
) -> dict[str, Any]:
    text = strip_private(turn_text).strip()
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
    buf.pop("next_try_at", None)
    buf.pop("finalize_attempts", None)
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
        except (OSError, ValueError):
            continue
        if b.get("finalized"):
            continue
        if b.get("turns"):
            out.append(b)
    return out


def mark_finalized(sid: str, outcome: str = "") -> None:
    buf = load(sid)
    if not buf:
        return
    buf["finalized"] = True
    buf["finalized_at"] = time.time()
    if outcome:
        buf["outcome"] = outcome
    save(buf)


def defer(sid: str, error: str) -> dict[str, Any]:
    """Finalize failed for a transient reason: keep the buffer, retry later with backoff.
    Gives up (marks finalized) after MAX_ATTEMPTS or MAX_AGE_SEC."""
    buf = load(sid) or {}
    n = int(buf.get("finalize_attempts") or 0) + 1
    age = time.time() - float(buf.get("created_at") or time.time())
    if n >= MAX_ATTEMPTS or age >= MAX_AGE_SEC:
        mark_finalized(sid, outcome=f"gave_up: {error}"[:200])
        return {"gave_up": True, "attempts": n}
    buf["finalize_attempts"] = n
    buf["next_try_at"] = time.time() + min(6 * 3600, 300 * 2 ** (n - 1))
    buf["last_error"] = error[:200]
    save(buf)
    return {"gave_up": False, "attempts": n, "next_try_at": buf["next_try_at"]}


def due(buf: dict[str, Any], now: float | None = None) -> bool:
    now = now if now is not None else time.time()
    return float(buf.get("next_try_at") or 0) <= now


def prune(now: float | None = None) -> int:
    """Delete finalized buffers older than RETAIN_SEC (they hold raw conversation text)."""
    now = now if now is not None else time.time()
    n = 0
    for p in sessions_dir().iterdir():
        if p.name.endswith((".recalled.json", ".project")):  # side files: by age
            with contextlib.suppress(OSError):
                if now - p.stat().st_mtime >= RETAIN_SEC:
                    p.unlink()
                    n += 1
            continue
        if p.suffix != ".json":
            continue
        try:
            b = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(b, dict) and b.get("finalized") and now - float(b.get("finalized_at") or 0) >= RETAIN_SEC:
            with contextlib.suppress(OSError):
                p.unlink()
                n += 1
    return n


@contextlib.contextmanager
def claim(sid: str) -> Iterator[bool]:
    """Per-session lock file so two background finalizers never push the same session."""
    lock = _path(sid).with_suffix(".lock")
    with contextlib.suppress(OSError):
        if time.time() - lock.stat().st_mtime > LOCK_STALE_SEC:
            lock.unlink()
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        yield False
        return
    os.close(fd)
    try:
        yield True
    finally:
        with contextlib.suppress(OSError):
            lock.unlink()


def session_corpus(buf: dict[str, Any]) -> str:
    parts = []
    for t in buf.get("turns") or []:
        tx = (t.get("text") or "").strip()
        if tx:
            parts.append(tx)
    return "\n\n---\n\n".join(parts)


def clip(text: str, limit: int = 12000, head: int = 4000) -> str:
    """Keep the start (the ask) and the end (where conclusions land) of a long session."""
    if len(text) <= limit:
        return text
    return text[:head] + "\n\n…（中间省略）…\n\n" + text[-(limit - head) :]


def idle_sessions(now: float | None = None) -> list[dict[str, Any]]:
    now = now if now is not None else time.time()
    return [b for b in list_open() if (now - float(b.get("updated_at") or 0)) >= IDLE_SEC]


def project_switched(buf: dict[str, Any], new_project: str | None) -> bool:
    old = (buf.get("project") or "").strip()
    new = (new_project or "").strip()
    return bool(old and new and old != new)
