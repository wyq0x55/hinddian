"""Shared bootstrap for the plugin's hook entry points.

Claude Code exports plugin userConfig as CLAUDE_PLUGIN_OPTION_<KEY>; map those onto the
names the scripts read. There is no built-in server address.
"""
import os
import sys
from pathlib import Path


def run(script: str) -> None:
    root = Path(os.environ.get("PLUGIN_ROOT") or os.environ.get("CLAUDE_PLUGIN_ROOT") or Path(__file__).resolve().parents[1])
    for key in ("HINDDIAN_MEMORY_URL", "HINDDIAN_MCP_TOKEN"):
        opt = os.environ.get("CLAUDE_PLUGIN_OPTION_" + key)
        if opt and not os.environ.get(key):
            os.environ[key] = opt
    path = root / "scripts" / script
    os.execv(sys.executable, [sys.executable, str(path)])
