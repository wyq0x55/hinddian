"""Bridge to the batch engine (`hinddian-batch`) and index status, for the dashboard.

The batch engine runs where the vault is. When VAULT_ROOT is mounted on this host it is run
locally (repo copy of classify/hinddian_batch.py, else `hinddian-batch` on PATH); otherwise it is
reached over the existing root SSH alias (CLASSIFY_SSH_HOST):

  ssh vault-host hinddian-batch gate --json
  ssh vault-host hinddian-batch approve <project>
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .config import get_settings

_cache: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()
_REPO_BATCH = Path(__file__).resolve().parents[2] / "classify" / "hinddian_batch.py"
_PROJ = re.compile(r"^[\w一-鿿.-]{1,40}$")
SYNC_STATUS = "/var/lib/hinddian/hindsight-sync-status.json"


class RemoteError(RuntimeError):
    pass


def _command(args: list[str]) -> list[str]:
    s = get_settings()
    if s.vault_local:
        if _REPO_BATCH.is_file():
            return [sys.executable, str(_REPO_BATCH), *args]
        if shutil.which("hinddian-batch"):
            return ["hinddian-batch", *args]
        raise RemoteError("hinddian-batch not installed on this host")
    return [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
        "-o", "ControlMaster=auto", "-o", f"ControlPath={s.ssh_control_path}",
        "-o", "ControlPersist=300",
        s.classify_ssh_host, "hinddian-batch", *args,
    ]


def _run(args: list[str], timeout: int = 25) -> Any:
    try:
        r = subprocess.run(_command(args), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise RemoteError("vault host timeout") from e
    except OSError as e:  # ssh / python missing
        raise RemoteError(f"cannot run batch engine: {e.strerror or e}") from e
    out = (r.stdout or "").strip()
    try:
        data = json.loads(out.splitlines()[-1]) if out else None
    except (json.JSONDecodeError, IndexError) as e:
        raise RemoteError(f"bad output (rc={r.returncode}): {(r.stderr or out)[-200:]}") from e
    if data is None:
        raise RemoteError(f"no output (rc={r.returncode}): {(r.stderr or '')[-200:]}")
    return data


def invalidate() -> None:
    with _lock:
        _cache.clear()


def gate() -> dict:
    with _lock:
        hit = _cache.get("gate")
        if hit and time.time() - hit[0] < 15:
            return hit[1]
    data = _run(["gate", "--json"])
    with _lock:
        _cache["gate"] = (time.time(), data)
    return data


def approve_batch(project: str) -> dict:
    if not _PROJ.match(project) or project in ("holdout", "通用-未定"):
        raise RemoteError("bad project")
    data = _run(["approve", project], timeout=40)
    invalidate()
    return data


def hindsight_stats() -> dict | None:
    """Hindsight bank stats (local REST on the API host). None when not configured."""
    s = get_settings()
    if not s.hindsight_api_key:
        return None
    import urllib.request

    req = urllib.request.Request(
        f"{s.hindsight_base_url.rstrip('/')}/v1/default/banks/{s.hindsight_bank}/stats",
        headers={"Authorization": f"Bearer {s.hindsight_api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            d = json.loads(r.read().decode())
        return {
            "documents": d.get("total_documents", 0),
            "pending_operations": d.get("pending_operations", 0),
            "failed_operations": d.get("failed_operations", 0),
            "last_write_at": d.get("last_memory_write_at"),
        }
    except Exception:  # noqa: BLE001
        return {"error": "unreachable"}


def sync_status() -> dict | None:
    try:
        with open(SYNC_STATUS) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None
