"""Filesystem settings shared by hooks, the batch engine and the dashboard."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import stat
import threading
from typing import Any


def config_path() -> Path:
    if path := os.environ.get("HINDDIAN_CONFIG"):
        return Path(path).expanduser()
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "hinddian/config.json"


def _read_config(path: Path) -> dict[str, Any]:
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            raise ValueError("hinddian config must be a regular file")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
    except FileNotFoundError:
        return {}
    with os.fdopen(fd, encoding="utf-8") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("hinddian config must be a regular file")
        data = json.load(stream)
    if not isinstance(data, dict):
        raise ValueError("hinddian config must be a JSON object")
    return data


def load_config() -> dict[str, Any]:
    result = queue.Queue(maxsize=1)
    path = config_path()

    def read():
        try:
            result.put(_read_config(path))
        except Exception as exc:
            result.put(exc)

    threading.Thread(target=read, daemon=True).start()
    try:
        config = result.get(timeout=0.5)
    except queue.Empty:
        raise TimeoutError("hinddian config read timed out") from None
    if isinstance(config, Exception):
        raise config
    return config


def _path(config: dict, key: str, *env_names: str) -> Path | None:
    for name in env_names:
        if value := os.environ.get(name):
            return Path(value).expanduser()
    value = config.get(key)
    return Path(value).expanduser() if isinstance(value, str) and value else None


def vault_dir() -> Path:
    return _path(load_config(), "vault", "HINDDIAN_VAULT", "VAULT_ROOT", "HC_VAULT") or Path.home() / "Obsidian/vault"


def state_dir() -> Path:
    default = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "hinddian"
    return _path(load_config(), "state_dir", "HINDDIAN_STATE_DIR", "HB_BASE") or default


def drafts_dir() -> Path:
    legacy_base = os.environ.get("HB_BASE")
    default = Path(legacy_base).expanduser() / "drafts" if legacy_base else Path.home() / "Obsidian/drafts"
    return _path(load_config(), "drafts_dir", "HINDDIAN_DRAFTS_DIR", "HB_DRAFTS") or default


def processed_dir() -> Path:
    return _path(load_config(), "processed_dir", "HINDDIAN_PROCESSED_DIR", "HB_PROCESSED") or drafts_dir().parent / "processed"


def jev_log_path() -> Path:
    return _path(load_config(), "jev_log", "HINDDIAN_JEV_LOG") or state_dir() / "jev-decisions.jsonl"


def check_draft_root(root: Path, vault: Path) -> None:
    root, vault = root.resolve(), vault.resolve()
    if root.is_relative_to(vault) or vault.is_relative_to(root):
        raise ValueError(f"draft storage must be outside the vault: {root}")
