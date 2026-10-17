#!/usr/bin/env python3
"""Magpie hook entry: ensure local hinddian-magpie scripts, then run session_start/turn_end.

Library command (self-heal on every Magpie host after WebDAV pulls library):

  HINDDIAN_MEMORY_URL=http://124.70.90.224/hinddian \\
  HINDDIAN_MCP_TOKEN=${HINDDIAN_MCP_TOKEN:-${HINDSIGHT_API_KEY:-}} \\
  python3 -c "import urllib.request as u; exec(u.urlopen('http://124.70.90.224/hinddian-static/bootstrap.py', timeout=30).read())" session_start
"""
from __future__ import annotations

import io
import os
import sys
import tarfile
import urllib.request
from pathlib import Path

STATIC = os.environ.get(
    "HINDDIAN_HOOKS_BASE", "http://124.70.90.224/hinddian-static"
).rstrip("/")
TGZ_URL = os.environ.get("HINDDIAN_HOOKS_TGZ", f"{STATIC}/magpie-hooks.tgz")
VER_URL = os.environ.get("HINDDIAN_HOOKS_VER_URL", f"{STATIC}/HOOKS_VERSION")


def hook_dir() -> Path:
    env = (os.environ.get("HINDDIAN_MAGPIE_HOOK_DIR") or "").strip()
    if env:
        return Path(env)
    root = Path("/usr/local/lib/hinddian-magpie")
    try:
        root.mkdir(parents=True, exist_ok=True)
        test = root / ".write_test"
        test.write_text("ok")
        test.unlink(missing_ok=True)
        return root
    except OSError:
        return Path.home() / ".local/lib/hinddian-magpie"


def remote_version() -> str:
    try:
        with urllib.request.urlopen(VER_URL, timeout=15) as r:
            return r.read().decode().strip() or "0"
    except Exception:
        return "0"


def local_version(d: Path) -> str:
    p = d / ".version"
    if p.is_file():
        return p.read_text().strip()
    return ""


def need_install(d: Path, want: str) -> bool:
    required = ("session_start.py", "turn_end.py", "jev.py")
    if any(not (d / name).is_file() for name in required):
        return True
    if want and want != "0" and local_version(d) != want:
        return True
    return False


def _member_name(name: str) -> str | None:
    name = name.lstrip("./")
    if not name or name.startswith("/") or ".." in name.split("/"):
        return None
    parts = name.split("/")
    if parts[0] in ("magpie-hooks", "magpie", ".") and len(parts) > 1:
        name = "/".join(parts[1:])
    elif len(parts) > 1:
        name = parts[-1]
    return name or None


def install(d: Path, want: str) -> None:
    d.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(TGZ_URL, timeout=60) as r:
        blob = r.read()
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        for m in tf.getmembers():
            name = _member_name(m.name)
            if not name:
                continue
            if m.isdir():
                (d / name).mkdir(parents=True, exist_ok=True)
                continue
            if not m.isfile():
                continue
            f = tf.extractfile(m)
            if f is None:
                continue
            target = d / Path(name).name  # flat install
            target.write_bytes(f.read())
            if target.suffix in (".py", ".sh"):
                target.chmod(0o755)
    ver = want
    vfile = d / "HOOKS_VERSION"
    if (not ver or ver == "0") and vfile.is_file():
        ver = vfile.read_text().strip()
    if ver and ver != "0":
        (d / ".version").write_text(ver + "\n")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    which = (argv[0] if argv else "").strip().replace("-", "_")
    if which not in ("session_start", "turn_end"):
        print("usage: bootstrap.py session_start|turn_end", file=sys.stderr)
        return 2
    d = hook_dir()
    want = remote_version()
    if need_install(d, want):
        try:
            install(d, want)
            print(f"hinddian-magpie hooks installed → {d} ver={local_version(d) or want}", flush=True)
        except Exception as e:
            if not (d / f"{which}.py").is_file():
                print(
                    f"hinddian-magpie install failed: {type(e).__name__}: {e}",
                    file=sys.stderr,
                )
                return 1
            print(
                f"hinddian-magpie install skipped ({type(e).__name__}); using existing"
            )
    script = d / f"{which}.py"
    if not script.is_file():
        print(f"missing {script}", file=sys.stderr)
        return 1
    os.environ.setdefault("HINDDIAN_MEMORY_URL", "http://124.70.90.224/hinddian")
    os.execv(sys.executable, [sys.executable, str(script), *argv[1:]])
    return 0


# Works as `python3 bootstrap.py …` and as `python3 -c "…exec(urlopen…)" …`
raise SystemExit(main())
