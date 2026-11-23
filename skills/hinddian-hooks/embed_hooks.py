"""Install versioned runtime files and build short Magpie hook commands."""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT_NAMES = (
    "hook_runtime.py", "capture.py", "extract.py", "session_start.py",
    "turn_end.py", "setup.py", "draft_store.py", "note_format.py", "paths.py",
)


def hooks_version() -> str:
    return (HERE / "HOOKS_VERSION").read_text(encoding="utf-8").strip()


def python_bin() -> str:
    if executable := os.environ.get("HINDDIAN_PYTHON"):
        return executable
    if os.name == "nt" and shutil.which("py"):
        return "py -3"
    return "python3" if shutil.which("python3") else "python"


def hook_defs(src_dir: Path | None = None) -> list[dict]:
    cfg = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    root = Path(os.environ.get("HINDDIAN_MAGPIE_HOOK_DIR") or cfg / "magpie/hinddian-hooks").expanduser()
    runtime = root.resolve() / hooks_version()
    runtime.mkdir(parents=True, exist_ok=True)
    for name in SCRIPT_NAMES:
        source = (src_dir or HERE) / name
        target = runtime / name
        if not target.is_file() or target.read_bytes() != source.read_bytes():
            shutil.copyfile(source, target)
    executable = python_bin()

    def command(script: str) -> str:
        path = str(runtime / script)
        argument = subprocess.list2cmdline([path]) if os.name == "nt" else shlex.quote(path)
        return f"{executable} {argument}"

    agents = ["claude", "codex", "grok", "pi", "cursor", "gemini"]
    return [
        {
            "name": "hinddian-session-start",
            "description": "Check local capture configuration",
            "event": "session-start",
            "command": command("session_start.py"),
            "agents": agents,
            "timeout": 45,
        },
        {
            "name": "hinddian-turn-end",
            "description": "Capture the final reply's closing sections locally",
            "event": "turn-end",
            "command": command("turn_end.py"),
            "agents": agents,
            "timeout": 90,
        },
    ]
