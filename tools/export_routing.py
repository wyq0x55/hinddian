#!/usr/bin/env python3
"""Export global/project routing JSON from the Obsidian vault (vault host)."""
from __future__ import annotations
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("VAULT_ROOT", os.environ.get("HC_VAULT", "/srv/obsidian/vault"))
from hinddian.notes import export_routing
if __name__ == "__main__":
    print(__import__("json").dumps(export_routing(), ensure_ascii=False, indent=2))
