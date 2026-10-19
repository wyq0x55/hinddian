#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _entry import run  # noqa: E402

run("turn_end.py")
