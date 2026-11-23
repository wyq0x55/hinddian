"""Shared silent bootstrap for plugin hook entry points."""
import os
import runpy
import sys
from pathlib import Path


def run(script: str) -> None:
    root = Path(os.environ.get("PLUGIN_ROOT") or os.environ.get("CLAUDE_PLUGIN_ROOT") or Path(__file__).resolve().parents[1])
    path = root / "scripts" / script
    sys.path.insert(0, str(path.parent))
    try:
        from hook_runtime import quiet
    except Exception:
        scripts = Path(__file__).resolve().parents[1] / "scripts"
        sys.path.insert(0, str(scripts))
        try:
            from hook_runtime import quiet
        except Exception:
            return
    @quiet
    def entry():
        runpy.run_path(str(path), run_name="__main__")

    entry()
