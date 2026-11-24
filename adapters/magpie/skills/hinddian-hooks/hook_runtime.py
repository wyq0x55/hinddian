"""Bounded, metadata-only diagnostics for silent hook entry points."""
from __future__ import annotations

import contextlib
import datetime
import functools
import json
import os
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
if not (HERE / "paths.py").is_file():
    sys.path.insert(0, str(HERE.parent / "src/hinddian"))

LOG_LIMIT = 128 * 1024


def record(event: str, **metadata) -> None:
    default = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "hinddian/hooks"
    root = Path(os.environ.get("HINDDIAN_HOOK_DIR") or os.environ.get("HINDDIAN_MAGPIE_HOOK_DIR") or default)
    data = json.dumps({"at": datetime.datetime.now().astimezone().isoformat(), "event": event, **metadata})
    line = (data + "\n").encode("ascii")
    if len(line) > LOG_LIMIT:
        return
    from note_format import private_append, vault_lock, write_atomic

    for directory in dict.fromkeys((root, default)):
        try:
            directory = directory.absolute()
            if any(part.is_symlink() for part in (*directory.parents, directory)):
                continue
            with vault_lock(directory / "hook-log.lock", timeout=0, private=True):
                path = directory / "capture.log"
                with private_append(path, "ab") as (stream, info):
                    if info.st_size + len(line) <= LOG_LIMIT:
                        stream.write(line)
                        return
                write_atomic(path, line.decode("ascii"))
                return
        except Exception:
            continue


def quiet(main):
    @functools.wraps(main)
    def run(*args, **kwargs):
        try:
            with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                main(*args, **kwargs)
        except (Exception, SystemExit, KeyboardInterrupt) as exc:
            with contextlib.suppress(Exception):
                record("error", entry=main.__module__, error=type(exc).__name__)

    return run


def run_hook(main):
    with open(os.devnull, "wb") as sink:
        for fd in (1, 2):
            os.dup2(sink.fileno(), fd)
    deadline = threading.Timer(2.5, os._exit, args=(0,))
    deadline.daemon = True
    deadline.start()
    try:
        main()
    finally:
        deadline.cancel()
