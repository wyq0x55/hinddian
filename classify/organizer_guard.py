"""Git snapshots and path checks for local organization."""
from __future__ import annotations

import os
import pathlib
import re
import stat
import subprocess
import tempfile

from hinddian import note_format as nf, paths

_COMMIT = re.compile(r"^[0-9a-fA-F]{4,64}(?:-dirty)?$")


def source_ref(session_id, commit):
    if isinstance(session_id, str) and session_id.strip() and isinstance(commit, str) and _COMMIT.fullmatch(commit):
        return f"{session_id}@{commit}"
    return None


def has_source(sources):
    return any("@" in ref and source_ref(*ref.rsplit("@", 1)) for ref in sources)


def no_symlinks(path):
    path = path.absolute()
    if any(part.is_symlink() for part in (*reversed(path.parents), path)):
        raise nf.UnsafePath(f"organizer path uses a symlink: {path}")
    return path


def external_path(vault, path):
    path = no_symlinks(path)
    paths.check_draft_root(path, vault)
    return path


def check_regular_file(path, *, private=False):
    try:
        info = path.stat()
    except FileNotFoundError:
        return
    if not stat.S_ISREG(info.st_mode) or (private and info.st_nlink != 1):
        raise nf.UnsafePath(f"unsafe organizer file: {path}")


def open_ledger(vault, state, path):
    state, path = external_path(vault, state), external_path(vault, path)
    if path.parent != state:
        raise nf.UnsafePath(f"ledger must be in the organizer state directory: {path}")
    check_regular_file(path, private=True)
    state.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    stream = os.fdopen(fd, "a", encoding="utf-8")
    info = os.fstat(stream.fileno())
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        stream.close()
        raise nf.UnsafePath(f"unsafe organizer ledger: {path}")
    return stream


def writable_path(vault, rel):
    segments = rel.split("/")
    if (any(not part or part in {".", ".."} or "\\" in part for part in segments)
            or not (rel == "00-系统/INDEX" or (len(segments) > 1 and segments[0] in {"项目", "技巧"}))):
        raise nf.UnsafePath(f"vault write outside allowlist: {rel!r}")
    target = no_symlinks(vault / (rel + ".md"))
    check_regular_file(target)
    nf.within(vault, rel)
    return target


def _git(vault, *args, index=None):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    if index is not None:
        env["GIT_INDEX_FILE"] = str(index)
    return subprocess.run(["git", "-c", f"core.hooksPath={os.devnull}", "-C", str(vault), *args], env=env,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=60, check=True).stdout.rstrip("\n")


def snapshot(vault, *, dry=False):
    root = _git(vault, "rev-parse", "--show-toplevel")
    if pathlib.Path(root).resolve() != vault.resolve():
        raise ValueError("vault must be the root of its Git working tree")
    previous = _git(vault, "rev-parse", "--verify", "HEAD")
    status = _git(vault, "status", "--porcelain", "--untracked-files=all")
    if status:
        if dry:
            raise ValueError("dry-run requires a clean vault")
        _git(vault, "add", "-A")
        _git(vault, "commit", "--no-gpg-sign", "-m", "hinddian: snapshot vault before organization")
        return _git(vault, "rev-parse", "HEAD"), True
    return previous, False


def diff_stat(vault, state, baseline):
    with tempfile.TemporaryDirectory(dir=state) as directory:
        index = pathlib.Path(directory) / "index"
        _git(vault, "read-tree", baseline, index=index)
        _git(vault, "add", "-A", index=index)
        return _git(vault, "-c", "core.quotePath=false", "diff", "--cached", "--stat", baseline, index=index)
