"""Git snapshots and path checks for local organization."""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import tempfile

from hinddian import note_format as nf

_COMMIT = re.compile(r"^[0-9a-fA-F]{4,64}(?:-dirty)?$")


def source_ref(session_id, commit):
    if isinstance(session_id, str) and session_id.strip() and isinstance(commit, str) and _COMMIT.fullmatch(commit):
        return f"{session_id}@{commit}"
    return None


def has_source(sources):
    return any("@" in ref and source_ref(*ref.rsplit("@", 1)) for ref in sources)


def writable_path(vault, rel):
    segments = rel.split("/")
    if (any(not part or part in {".", ".."} or "\\" in part for part in segments)
            or not (rel == "00-系统/INDEX" or (len(segments) > 1 and segments[0] in {"项目", "技巧"}))):
        raise nf.UnsafePath(f"vault write outside allowlist: {rel!r}")
    target = vault / (rel + ".md")
    if any(path.is_symlink() for path in (target, *target.parents) if path != vault and path.is_relative_to(vault)):
        raise nf.UnsafePath(f"vault write through symlink: {rel!r}")
    return nf.within(vault, rel)


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
