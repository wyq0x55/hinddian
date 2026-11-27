"""Capture one final reply locally, without a model or network transport."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import socket
import subprocess
from pathlib import Path

from hook_runtime import record

import draft_store
import extract
import paths

UNKNOWN_PROJECT = "通用-未定"


def settings() -> tuple[str, int]:
    config = paths.load_config()
    legacy_url = os.environ.get("HINDDIAN_MEMORY_URL") or os.environ.get("CLAUDE_PLUGIN_OPTION_HINDDIAN_MEMORY_URL") or config.get("url")
    mode = os.environ.get("HINDDIAN_CAPTURE_MODE") or config.get("capture_mode") or ("http" if legacy_url else "local")
    if mode != "local":
        raise ValueError("capture_mode must be local")
    fallback = os.environ.get("HINDDIAN_NO_CLOSING") or config.get("no_closing", "skip")
    if fallback not in ("skip", "summary"):
        raise ValueError("no_closing must be skip or summary")
    limit = int(os.environ.get("HINDDIAN_SUMMARY_CHARS") or config.get("summary_chars", 500))
    if not 1 <= limit <= 20_000:
        raise ValueError("summary_chars must be between 1 and 20000")
    return fallback, limit


def _git(cwd: Path, *args: str) -> str | None:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    try:
        result = subprocess.run(["git", "--no-optional-locks", "-C", str(cwd), *args], env=env,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                encoding="utf-8", errors="replace", timeout=0.7)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.rstrip("\r\n") if result.returncode == 0 else None


def repository(cwd: str) -> dict[str, str]:
    meta = dict.fromkeys(("repo", "branch", "commit"), "")
    if not cwd or not (common := _git(Path(cwd), "rev-parse", "--path-format=absolute", "--git-common-dir")):
        return meta
    checkout = Path(cwd)
    common_path = Path(common)
    root = common_path.parent if common_path.name == ".git" else Path(_git(checkout, "rev-parse", "--show-toplevel") or "")
    commit = _git(checkout, "rev-parse", "--short", "HEAD") or ""
    if commit and _git(checkout, "status", "--porcelain", "--untracked-files=normal"):
        commit += "-dirty"
    return {"repo": root.name, "branch": _git(checkout, "symbolic-ref", "--quiet", "--short", "HEAD") or "",
            "commit": commit}


def _project(hint: str, repo: str, cwd: str, projects: list[str]) -> str:
    if hint:
        return hint
    for name in (repo, cwd):
        if name:
            matches = [project for project in projects if project.lower() in name.lower()]
            if matches:
                return max(matches, key=len)
    return repo or UNKNOWN_PROJECT


def _field(payload: dict, *keys: str) -> str:
    return next((payload[key] for key in keys if isinstance(payload.get(key), str) and payload[key].strip()), "")


def capture(payload: dict) -> dict | None:
    fallback, limit = settings()
    reply, message_id = extract.final_message(payload)
    sid = (_field(payload, "session_id", "sessionId", "conversation_id", "conversationId", "thread_id")
           or next((os.environ[name] for name in ("MAGPIE_SESSION_ID", "CLAUDE_SESSION_ID", "CODEX_SESSION_ID",
                                                 "CURSOR_SESSION_ID") if os.environ.get(name)), ""))
    try:
        closing = extract.closing(reply)
    except extract.MarkdownParserUnavailable:
        record("skip", reason="missing_markdown_parser", dependency="markdown-it-py", session_id=sid)
        return None
    if closing:
        kind, text = "closing", closing
    elif fallback == "summary" and reply.strip():
        kind, text = "summary", reply.strip()[:limit]
    else:
        record("skip", reason="no_closing", session_id=sid)
        return None

    cwd = (_field(payload, "cwd", "cwd_path", "working_directory", "workdir")
           or os.environ.get("MAGPIE_CWD", ""))
    host = os.environ.get("HINDDIAN_CLIENT_ID") or socket.gethostname()
    basename = cwd.rstrip("/\\").replace("\\", "/").rsplit("/", 1)[-1]
    meta = {"session_id": sid, "host": host, "cwd": basename, **repository(cwd), "kind": kind}
    vault = paths.vault_dir()
    project = _project(_field(payload, "project"), meta["repo"], basename, draft_store.project_names(vault))
    explicit = _field(payload, "turn_id", "turnId", "message_id") or message_id
    identity = [sid, host, explicit] if explicit else [sid, host, cwd, reply]
    turn = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
    at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    return draft_store.append_capture(paths.drafts_dir(), paths.processed_dir(), vault=vault, project=project,
                                      meta=meta, turn=turn, at=at, text=text)
