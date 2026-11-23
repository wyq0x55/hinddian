"""SessionStart: schedule finalization of previous session buffers without emitting context."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import extract  # noqa: E402
import hookcfg  # noqa: E402
import session_buf  # noqa: E402


def main() -> None:
    if hookcfg.transport_problem():
        return
    stdin = sys.stdin.read(50000) if not sys.stdin.isatty() else ""
    payload = extract.parse_hook_payload(stdin, include_turn=False)
    if payload["raw_data"].get("source") in ("compact", "resume"):
        return
    sid = session_buf.stable_session_id(payload["session_id"], payload["cwd"], "new")
    if not hookcfg.spawn_finalize("--current", sid, log=session_buf.hook_dir() / "finalize.log"):
        import finalize

        finalize.finalize_idle_and_others(current_sid=sid)


if __name__ == "__main__":
    main()
