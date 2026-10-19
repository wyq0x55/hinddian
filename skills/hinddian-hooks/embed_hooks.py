#!/usr/bin/env python3
"""Embed Magpie hook scripts into library hook *commands*.

Important: Magpie WebDAV/backup Bundle does NOT carry hooks yet (upstream).
These commands are for local library.json after apply_library / skill install.
Skills + this packager sync via WebDAV; install.py writes hooks on each PC.
"""
from __future__ import annotations

import base64
import io
import os
import shutil
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT_NAMES = ("jev.py", "hookcfg.py", "extract.py", "session_buf.py", "finalize.py", "session_start.py", "turn_end.py", "setup.py")
DEFAULT_VER = "20261018.1"
MEMORY_URL = (os.environ.get("HINDDIAN_MEMORY_URL") or "").strip()  # baked into the hook command; empty = read env at run time


def hooks_version() -> str:
    p = HERE / "HOOKS_VERSION"
    if p.is_file():
        return p.read_text().strip() or DEFAULT_VER
    return DEFAULT_VER


def pack_scripts_b64(src_dir: Path | None = None) -> str:
    root = src_dir or HERE
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name in SCRIPT_NAMES:
            data = (root / name).read_bytes()
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o644
            tf.addfile(info, io.BytesIO(data))
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    if "'" in b64:
        raise RuntimeError("unexpected quote in base64")
    return b64


def extractor_source(ver: str, scripts_b64: str) -> str:
    return f'''
import base64, io, os, sys, tarfile, pathlib
V = "{ver}"
B = "{scripts_b64}"
MEM = "{MEMORY_URL}"
home = pathlib.Path.home()
cfg = pathlib.Path(os.environ.get("XDG_CONFIG_HOME") or (home / ".config"))
D = pathlib.Path(os.environ.get("HINDDIAN_MAGPIE_HOOK_DIR") or (cfg / "magpie" / "hinddian-hooks"))
which = (sys.argv[1] if len(sys.argv) > 1 else "").replace("-", "_")
if which not in ("session_start", "turn_end"):
    sys.stderr.write("usage: session_start|turn_end\\n")
    raise SystemExit(2)
need = (
    not (D / "jev.py").is_file()
    or not (D / ".version").is_file()
    or (D / ".version").read_text().strip() != V
    or not (D / (which + ".py")).is_file()
)
if need:
    D.mkdir(parents=True, exist_ok=True)
    raw = base64.b64decode(B)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
        for m in tf.getmembers():
            if not m.isfile():
                continue
            name = pathlib.Path(m.name).name
            if name not in {SCRIPT_NAMES!r}:
                continue
            (D / name).write_bytes(tf.extractfile(m).read())
    (D / ".version").write_text(V + "\\n")
if MEM:
    os.environ.setdefault("HINDDIAN_MEMORY_URL", MEM)
sys.path.insert(0, str(D))
os.execv(sys.executable, [sys.executable, str(D / (which + ".py"))] + sys.argv[2:])
'''.strip()


def python_bin() -> str:
    """Interpreter name for Magpie hook command on *this* OS."""
    force = (os.environ.get("HINDDIAN_PYTHON") or "").strip()
    if force:
        return force
    if sys.platform.startswith("win"):
        # Windows: prefer py -3 launcher, then python
        if shutil.which("py"):
            return "py -3"
        if shutil.which("python"):
            return "python"
        if shutil.which("python3"):
            return "python3"
        return "py -3"
    # Unix Magpie hosts
    if shutil.which("python3"):
        return "python3"
    if shutil.which("python"):
        return "python"
    return "python3"


def shell_command(which: str, src_dir: Path | None = None, memory_url: str | None = None, py: str | None = None) -> str:
    if which.replace("-", "_") not in ("session_start", "turn_end"):
        raise ValueError(which)
    which = which.replace("-", "_")
    ver = hooks_version()
    scripts_b64 = pack_scripts_b64(src_dir)
    # memory URL baked into extractor (no shell env / bash ${} — breaks Windows cmd)
    global MEMORY_URL
    old = MEMORY_URL
    if memory_url:
        MEMORY_URL = memory_url
    try:
        src = extractor_source(ver, scripts_b64)
    finally:
        MEMORY_URL = old
    src_b64 = base64.b64encode(src.encode()).decode("ascii")
    if "'" in src_b64:
        raise RuntimeError("unexpected quote in source base64")
    wrapper = f"import base64; exec(base64.b64decode(\"{src_b64}\").decode())"
    exe = py or python_bin()
    # No bash-only env assignment; token read inside session_start/turn_end via os.environ
    return f"{exe} -c '{wrapper}' {which}"


def hook_defs(src_dir: Path | None = None, py: str | None = None) -> list[dict]:
    ss = shell_command("session_start", src_dir=src_dir, py=py)
    te = shell_command("turn_end", src_dir=src_dir, py=py)
    agents = ["claude", "codex", "grok", "pi", "cursor", "gemini"]
    return [
        {
            "name": "hinddian-session-start",
            "description": "SessionStart: finalize prior session draft + routing + Jev should-recall (WebDAV does not sync hooks)",
            "event": "session-start",
            "command": ss,
            "agents": agents,
            "timeout": 45,
        },
        {
            "name": "hinddian-turn-end",
            "description": "TurnEnd: whitelist extract → session buffer (finalize on session-start/idle)",
            "event": "turn-end",
            "command": te,
            "agents": agents,
            "timeout": 90,
        },
    ]


if __name__ == "__main__":
    import json
    w = (sys.argv[1] if len(sys.argv) > 1 else "session_start").replace("-", "_")
    print(json.dumps({"which": w, "cmd_len": len(shell_command(w)), "ver": hooks_version(), "py": python_bin()}))
