#!/usr/bin/env python3
import os, sys
from pathlib import Path
root = Path(os.environ.get("PLUGIN_ROOT") or os.environ.get("CLAUDE_PLUGIN_ROOT") or Path(__file__).resolve().parents[1])
os.environ.setdefault("HINDDIAN_MEMORY_URL", "http://124.70.90.224/hinddian")
sys.path.insert(0, str(root / "scripts"))
import session_start  # noqa: F401 — module runs on import? better exec
# session_start is a script with main logic at module level typically
path = root / "scripts" / "session_start.py"
os.execv(sys.executable, [sys.executable, str(path)])
