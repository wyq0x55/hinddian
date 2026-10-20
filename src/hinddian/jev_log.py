"""Client-reported Jev decisions (metadata only) — append-only JSONL on the API host.

Jev runs in the client hooks; without these reports the server cannot tell "finalize never
fired" from "Jev source=none" from "keep=false". Never stores turn text or secrets.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import Counter
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024  # rotate to .1 past this (one old generation kept)
_LOCK = threading.Lock()
EVENTS = ("finalize", "turn")
STR_FIELDS = {  # name -> max length
    "session_id": 128, "project": 128, "cwd": 128, "host": 64, "finalize_reason": 40,
    "jev_source": 40, "outcome": 40, "error": 200, "draft_path": 256,
}
_SECRETish = re.compile(r"(?i)(bearer\s+\S+|(?:token|api[_-]?key|secret|password)\s*[=:]\s*\S+|sk-[A-Za-z0-9_-]{8,})")


class ReportError(ValueError):
    pass


def log_path() -> Path:
    return Path(os.environ.get("HINDDIAN_JEV_LOG") or "/var/lib/hinddian/jev-decisions.jsonl")


def _clean(v, n: int) -> str | None:
    if v is None:
        return None
    if not isinstance(v, (str, int, float)):
        raise ReportError("string expected")
    s = re.sub(r"[\x00-\x1f]+", " ", str(v)).strip()
    s = _SECRETish.sub("[redacted]", s)
    return s[:n] or None


def validate(args: dict) -> dict:
    if not isinstance(args, dict):
        raise ReportError("object expected")
    if len(json.dumps(args, ensure_ascii=False, default=str)) > 4096:
        raise ReportError("report too large")
    rec: dict = {}
    for k, n in STR_FIELDS.items():
        try:
            rec[k] = _clean(args.get(k), n)
        except ReportError as e:
            raise ReportError(f"{k}: {e}") from e
    if not rec["session_id"]:
        raise ReportError("session_id required")
    rec["host"] = rec["host"] or "unknown"
    rec["jev_source"] = rec["jev_source"] or "none"
    ev = args.get("event") or "finalize"
    if ev not in EVENTS:
        raise ReportError("event must be finalize|turn")
    rec["event"] = ev
    keep = args.get("keep")
    if keep is not None and not isinstance(keep, bool):
        raise ReportError("keep must be bool|null")
    rec["keep"] = keep
    rec["pushed"] = bool(args.get("pushed"))
    conf = args.get("confidence")
    rec["confidence"] = round(float(conf), 3) if isinstance(conf, (int, float)) and not isinstance(conf, bool) else None
    tc = args.get("turn_count")
    rec["turn_count"] = max(0, min(int(tc), 100000)) if isinstance(tc, int) and not isinstance(tc, bool) else None
    now = time.time()
    ts = args.get("ts")
    rec["client_ts"] = float(ts) if isinstance(ts, (int, float)) and not isinstance(ts, bool) else None
    rec["ts"] = now  # server receive time is authoritative
    return rec


def append(rec: dict) -> None:
    p = log_path()
    line = json.dumps(rec, ensure_ascii=False) + "\n"
    with _LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            if p.stat().st_size + len(line) > MAX_BYTES:
                os.replace(p, p.with_suffix(p.suffix + ".1"))
        except FileNotFoundError:
            pass
        with open(p, "a", encoding="utf-8") as f:
            f.write(line)


def _read(p: Path) -> list[dict]:
    out = []
    try:
        with open(p, encoding="utf-8") as f:
            for ln in f:
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    continue
    except FileNotFoundError:
        pass
    return out


def recent(limit: int = 100) -> list[dict]:
    p = log_path()
    rows = _read(p.with_suffix(p.suffix + ".1")) + _read(p)
    rows.sort(key=lambda r: r.get("ts") or 0, reverse=True)
    return rows[: max(1, min(int(limit), 1000))]


def summary(now: float | None = None) -> dict:
    now = time.time() if now is None else now
    rows = recent(1000)
    hosts: dict[str, dict] = {}
    for r in rows:  # newest first
        h = r.get("host") or "unknown"
        hosts.setdefault(h, {"host": h, "last_ts": r.get("ts"), "last_source": r.get("jev_source"),
                             "last_keep": r.get("keep"), "last_pushed": r.get("pushed"), "count_24h": 0})
        if (r.get("ts") or 0) >= now - 86400:
            hosts[h]["count_24h"] += 1
    day = [r for r in rows if (r.get("ts") or 0) >= now - 86400]
    return {
        "last_ts": rows[0].get("ts") if rows else None,
        "hosts": sorted(hosts.values(), key=lambda h: h["last_ts"] or 0, reverse=True),
        "by_source_24h": dict(Counter(r.get("jev_source") or "none" for r in day)),
        "keep_24h": sum(1 for r in day if r.get("keep") is True),
        "drop_24h": sum(1 for r in day if r.get("keep") is False),
        "pushed_24h": sum(1 for r in day if r.get("pushed")),
        "total_24h": len(day),
    }
