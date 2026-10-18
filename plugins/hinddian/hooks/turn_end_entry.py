#!/usr/bin/env python3
import os, sys
from pathlib import Path
root = Path(os.environ.get("PLUGIN_ROOT") or os.environ.get("CLAUDE_PLUGIN_ROOT") or Path(__file__).resolve().parents[1])
os.environ.setdefault("HINDDIAN_MEMORY_URL", "http://124.70.90.224/hinddian")
path = root / "scripts" / "turn_end.py"
os.execv(sys.executable, [sys.executable, str(path)])
