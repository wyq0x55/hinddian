"""Handle one host Stop/turn-end event."""
from __future__ import annotations

import json
import sys

from hook_runtime import quiet, run_hook


@quiet
def main() -> None:
    from capture import capture

    raw = sys.stdin.read(8_000_001) if not sys.stdin.isatty() else ""
    if len(raw) > 8_000_000:
        raise ValueError("hook payload too large")
    payload = json.loads(raw) if raw.strip() else {}
    if not isinstance(payload, dict):
        raise ValueError("hook payload must be a JSON object")
    capture(payload)


if __name__ == "__main__":
    run_hook(main)
