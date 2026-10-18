"""TurnEnd: whitelist extract → append session buffer (no per-turn push_draft).

Finalize (Jev + network) runs in a detached finalize.py so the host's turn never waits on it;
it handles session-start / idle / project-switch (see finalize.py).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import extract  # noqa: E402
import hookcfg  # noqa: E402
import session_buf  # noqa: E402


def main() -> None:
    why = hookcfg.transport_problem()
    if why:
        # Nothing could ever be delivered — don't keep conversation text on disk for it.
        print(json.dumps({"ok": False, "buffered": False, "reason": why}, ensure_ascii=False))
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
    buf = session_buf.append_turn(session_id=sid, turn_text=turn, cwd=payload.get("cwd") or "")
    background = hookcfg.spawn_finalize("--current", sid, log=log)
    out = {
        "ok": True,
        "buffered": True,
        "session_id": sid,
        "turns": len(buf.get("turns") or []),
        "chars": len(turn),
        "finalize": "background" if background else _sync_finalize(sid),
    }
    print(json.dumps(out, ensure_ascii=False)[:500])


def _sync_finalize(sid: str | None) -> list[dict]:
    import finalize

    return finalize.finalize_idle_and_others(current_sid=sid)


if __name__ == "__main__":
    main()
