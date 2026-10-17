#!/bin/bash
# Run on DMIT as root from the repo's classify/ dir (rsynced to /opt/hinddian-classify/src).
# Prereq: /usr/local/bin/pi (pi 1.x on private node22) and
#         /etc/hinddian-classify/secrets.env (600) with HINDSIGHT_API_KEY=...
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
H=/opt/hinddian-classify
install -d -m 700 "$H" "$H/pi-agent" "$H/skills" "$H/work"
install -m 755 "$SRC/hinddian_classify.py" /usr/local/bin/hinddian-classify
install -m 600 "$SRC/pi-agent/models.json" "$SRC/pi-agent/mcp.json" "$SRC/pi-agent/settings.json" "$H/pi-agent/"
install -m 600 "$SRC/AGENTS.md" "$H/pi-agent/AGENTS.md"
rm -rf "$H/skills/topic-merge"; cp -r "$SRC/skills/topic-merge" "$H/skills/"
install -m 644 "$SRC/deploy/hinddian-classify.service" "$SRC/deploy/hinddian-classify.timer" /etc/systemd/system/
install -d -m 700 /var/lib/hinddian-classify
systemctl daemon-reload
echo "installed. enable with: systemctl enable --now hinddian-classify.timer"
