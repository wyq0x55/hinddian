#!/usr/bin/env python3
"""Embed Magpie hook scripts into library hook *commands* (WebDAV LWW sufficient).

No /usr/local/lib, no HTTP bootstrap. The command string carries a base64 payload
of jev.py + session_start.py + turn_end.py; on first run it extracts under
~/.config/magpie/hinddian-hooks/ (override HINDDIAN_MAGPIE_HOOK_DIR) then execs.
"""
from __future__ import annotations

import base64
import io
import os
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT_NAMES = ("jev.py", "session_start.py", "turn_end.py")
DEFAULT_VER = "20261017.7"
MEMORY_URL = os.environ.get("HINDDIAN_MEMORY_URL", "http://124.70.90.224/hinddian")


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
    """Python source that extracts payload then execs session_start|turn_end."""
    # Keep only double-quoted strings so the outer shell can wrap in single quotes.
    return f'''
import base64, io, os, sys, tarfile, pathlib
V = "{ver}"
B = "{scripts_b64}"
D = pathlib.Path(os.environ.get("HINDDIAN_MAGPIE_HOOK_DIR") or (pathlib.Path.home() / ".config/magpie/hinddian-hooks"))
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
            if name not in ("jev.py", "session_start.py", "turn_end.py"):
                continue
            (D / name).write_bytes(tf.extractfile(m).read())
    (D / ".version").write_text(V + "\\n")
os.environ.setdefault("HINDDIAN_MEMORY_URL", "{MEMORY_URL}")
sys.path.insert(0, str(D))
os.execv(sys.executable, [sys.executable, str(D / (which + ".py"))] + sys.argv[2:])
'''.strip()


def shell_command(which: str, src_dir: Path | None = None, memory_url: str | None = None) -> str:
    """Full Magpie hook command string (shell + embedded python)."""
    if which.replace("-", "_") not in ("session_start", "turn_end"):
        raise ValueError(which)
    which = which.replace("-", "_")
    ver = hooks_version()
    scripts_b64 = pack_scripts_b64(src_dir)
    src = extractor_source(ver, scripts_b64)
    # Double-encode so -c stays one physical line (shell won't mangle newlines).
    src_b64 = base64.b64encode(src.encode()).decode("ascii")
    if "'" in src_b64:
        raise RuntimeError("unexpected quote in source base64")
    wrapper = f"import base64; exec(base64.b64decode(\"{src_b64}\").decode())"
    mem = memory_url or MEMORY_URL
    return (
        f"HINDDIAN_MEMORY_URL={mem} "
        f"HINDDIAN_MCP_TOKEN=${{HINDDIAN_MCP_TOKEN:-${{HINDSIGHT_API_KEY:-}}}} "
        f"python3 -c '{wrapper}' {which}"
    )


if __name__ == "__main__":
    import json
    import sys

    w = (sys.argv[1] if len(sys.argv) > 1 else "session_start").replace("-", "_")
    cmd = shell_command(w)
    print(json.dumps({"which": w, "cmd_len": len(cmd), "ver": hooks_version()}))
    if "--print" in sys.argv:
        print(cmd)
