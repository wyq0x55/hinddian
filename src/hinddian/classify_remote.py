"""Bridge to the DMIT classify stage (pi 归类).

hinddian runs on Huawei; the vault + pi classifier run on DMIT. We reuse the
existing root SSH trust (same as session-distill worker → DMIT) and call the
`hinddian-classify` CLI. No new public port, no extra token.

  ssh dmit-vps hinddian-classify stats --json
  ssh dmit-vps hinddian-classify proposals --json --status pending
  ssh dmit-vps hinddian-classify recent --json
  ssh dmit-vps hinddian-classify approve <id> | reject <id> --reason ...
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from typing import Any

from .config import get_settings

_PID = re.compile(r"^p-[0-9A-Za-z_-]{6,40}$")
_cache: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()


class RemoteError(RuntimeError):
    pass


def _ssh(args: list[str], timeout: int = 25, binary: str = "hinddian-classify") -> Any:
    s = get_settings()
    cmd = [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
        "-o", "ControlMaster=auto", "-o", "ControlPath=/run/hinddian-ssh-%C",
        "-o", "ControlPersist=300",
        s.classify_ssh_host, binary, *args,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:  # pragma: no cover
        raise RemoteError("DMIT classify timeout") from e
    out = (r.stdout or "").strip()
    try:
        data = json.loads(out) if out else None
    except json.JSONDecodeError as e:
        raise RemoteError(f"bad output (rc={r.returncode}): {(r.stderr or out)[-200:]}") from e
    if data is None:
        raise RemoteError(f"no output (rc={r.returncode}): {(r.stderr or '')[-200:]}")
    return data


def cached(key: str, args: list[str], ttl: float = 15.0) -> Any:
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    data = _ssh(args)
    with _lock:
        _cache[key] = (time.time(), data)
    return data


def invalidate() -> None:
    with _lock:
        _cache.clear()


def stats() -> dict:
    return cached("stats", ["stats", "--json"])


def proposals(status: str = "pending") -> list[dict]:
    if status not in ("pending", "applied", "rejected", "ignored_by_rule", "all"):
        status = "pending"
    return cached(f"proposals:{status}", ["proposals", "--json", "--status", status, "--limit", "100"])


def recent(limit: int = 30) -> list[dict]:
    limit = max(1, min(int(limit), 100))
    return cached(f"recent:{limit}", ["recent", "--json", "--limit", str(limit)])


def decide(pid: str, approve: bool, reason: str = "") -> dict:
    if not _PID.match(pid):
        raise RemoteError("bad proposal id")
    if approve:
        args = ["approve", pid]
    else:
        # quote-free: strip anything shell-meaningful; remote side gets argv via ssh string
        safe = re.sub(r"[^\w\u4e00-\u9fff ，。、,.!?！？:：()（）-]", "", reason)[:200]
        args = ["reject", pid] + (["--reason", f"'{safe}'"] if safe else [])
    data = _ssh(args, timeout=40)
    invalidate()
    return data


def _safe_reason(reason: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff ，。、,.!?！？:：()（）-]", "", reason or "")[:200]


def batch(ids: list[str], approve: bool, reason: str = "") -> dict:
    ids = [i for i in ids if isinstance(i, str)][:100]
    if not ids or not all(_PID.match(i) for i in ids):
        raise RemoteError("bad proposal ids")
    args = ["approve-batch" if approve else "reject-batch", *ids]
    if not approve and _safe_reason(reason):
        args += ["--reason", f"'{_safe_reason(reason)}'"]
    data = _ssh(args, timeout=120)
    invalidate()
    return data


def restore(pid: str) -> dict:
    if not _PID.match(pid):
        raise RemoteError("bad proposal id")
    data = _ssh(["restore", pid], timeout=30)
    invalidate()
    return data


def hindsight_stats() -> dict | None:
    """Hindsight bank stats (local REST on Huawei). None when not configured."""
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
            "nodes": d.get("total_nodes", 0),
            "pending_operations": d.get("pending_operations", 0),
            "failed_operations": d.get("failed_operations", 0),
            "last_write_at": d.get("last_memory_write_at"),
        }
    except Exception:  # noqa: BLE001
        return {"error": "unreachable"}


# ---------------- batch gate (hinddian-batch on DMIT) ----------------
_PROJ = re.compile(r"^[\w\u4e00-\u9fff.-]{1,40}$")
SYNC_STATUS = "/var/lib/hinddian/hindsight-sync-status.json"


def gate() -> dict:
    now = time.time()
    with _lock:
        hit = _cache.get("gate")
        if hit and now - hit[0] < 15:
            return hit[1]
    data = _ssh(["gate", "--json"], binary="hinddian-batch")
    with _lock:
        _cache["gate"] = (time.time(), data)
    return data


def approve_batch(project: str) -> dict:
    if not _PROJ.match(project) or project in ("holdout", "通用-未定"):
        raise RemoteError("bad project")
    data = _ssh(["approve", project], timeout=40, binary="hinddian-batch")
    invalidate()
    return data


def sync_status() -> dict | None:
    try:
        with open(SYNC_STATUS) as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return None
