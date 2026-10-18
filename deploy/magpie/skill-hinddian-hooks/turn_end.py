"""TurnEnd: whitelist extract → append session buffer (no per-turn push_draft).

Finalize happens on session-start / idle / project-switch (see finalize.py).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import extract
import finalize
import session_buf


def main() -> None:
    stdin = ""
    if not sys.stdin.isatty():
        stdin = sys.stdin.read(200000)
    payload = extract.parse_hook_payload(stdin)
    turn = payload.get("turn_text") or ""
    if not turn.strip():
        # still run idle finalize
        results = finalize.finalize_idle_and_others()
        if results:
            print(json.dumps({"idle_finalize": results}, ensure_ascii=False)[:500])
        return

    sid = session_buf.stable_session_id(payload.get("session_id"), payload.get("cwd") or "", turn[:80])
    # Finalize other idle / previous sessions first
    others = finalize.finalize_idle_and_others(current_sid=sid)
    buf = session_buf.append_turn(
        session_id=sid,
        turn_text=turn,
        cwd=payload.get("cwd") or "",
    )
    out = {
        "ok": True,
        "buffered": True,
        "session_id": sid,
        "turns": len(buf.get("turns") or []),
        "chars": len(turn),
        "finalized_others": others,
    }
    print(json.dumps(out, ensure_ascii=False)[:500])


if __name__ == "__main__":
    main()
