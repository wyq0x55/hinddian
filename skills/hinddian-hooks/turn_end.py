"""TurnEnd: whitelist extract → append session buffer (no per-turn push_draft).

Finalize (Jev + network) runs in a detached finalize.py so the host's turn never waits on it;
it handles session-start / idle / project-switch (see finalize.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hook_runtime import quiet, record  # noqa: E402


@quiet
def main() -> None:
    import extract
    import hookcfg
    import session_buf

    hookcfg.load_config()
    why = hookcfg.capture_problem()
    if why:
        record("capture_disabled", entry="turn_end")
        return
    stdin = ""
    if not sys.stdin.isatty():
        stdin = sys.stdin.read(200000)
    payload = extract.parse_hook_payload(stdin)
    turn = payload.get("turn_text") or ""
    log = session_buf.hook_dir() / "finalize.log"
    if not turn.strip():
        hookcfg.spawn_finalize(log=log) or _sync_finalize(None)
        return

    sid = session_buf.stable_session_id(payload.get("session_id"), payload.get("cwd") or "", turn[:80])
    session_buf.append_turn(session_id=sid, turn_text=turn, cwd=payload.get("cwd") or "")
    hookcfg.spawn_finalize("--current", sid, log=log) or _sync_finalize(sid)


def _sync_finalize(sid: str | None) -> list[dict]:
    import finalize

    return finalize.finalize_idle_and_others(current_sid=sid)


if __name__ == "__main__":
    main()
