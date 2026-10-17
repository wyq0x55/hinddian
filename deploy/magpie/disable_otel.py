#!/usr/bin/env python3
"""Set Magpie settings.json otel.enabled=false (preserves other fields; does not print secrets)."""
from __future__ import annotations
import json, shutil, time
from pathlib import Path
SETTINGS = Path("/root/.config/magpie/settings.json")

def main():
    bak = SETTINGS.with_suffix(SETTINGS.suffix + f".bak.{int(time.time())}")
    shutil.copy2(SETTINGS, bak)
    data = json.loads(SETTINGS.read_text())
    otel = data.get("otel") or {}
    otel["enabled"] = False
    # keep endpoint/headers but disable so sync propagates "off"
    data["otel"] = otel
    SETTINGS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"ok": True, "backup": str(bak), "otel.enabled": False}))

if __name__ == "__main__":
    main()
