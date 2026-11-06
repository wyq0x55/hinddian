"""Best-effort API-host sync kick after a successful vault write.

The shipped systemd API service enables this; development defaults to timer-only.
No request waits for indexing, SSH or systemctl. The timer covers failures and coalesced starts.
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading

log = logging.getLogger(__name__)


def _start() -> None:
    try:
        subprocess.run(
            ["systemctl", "--no-block", "start", "hinddian-hindsight-sync.service"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            timeout=2, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        log.warning("Could not kick Hindsight sync; the two-minute timer will retry")


def kick() -> None:
    if os.environ.get("HINDDIAN_SYNC_KICK", "").lower() in ("1", "true", "yes"):
        try:
            threading.Thread(target=_start, name="hinddian-sync-kick", daemon=True).start()
        except (OSError, RuntimeError):
            log.warning("Could not schedule Hindsight sync; the two-minute timer will retry")
