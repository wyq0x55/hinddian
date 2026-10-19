#!/bin/bash
# Install the vault-host side of hinddian. Run as root from a checkout of the repo on the vault host
# (e.g. /opt/hinddian; update with git pull / rsync, then re-run).
#
#   hinddian-batch        drafts → atomic notes (systemd timers below)
#   hinddian-memory-cli   vault ops the API host calls over SSH
#
# Both are symlinks into the checkout, so they import the checkout's src/hinddian (note_format etc.).
# Prereq: an OpenAI-compatible gateway for the batch LLM at HB_GATEWAY (default 127.0.0.1:3425).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
chmod 755 "$REPO/classify/hinddian_batch.py" "$REPO/deploy/vault-host/hinddian-memory-cli"
ln -sf "$REPO/classify/hinddian_batch.py" /usr/local/bin/hinddian-batch
ln -sf "$REPO/deploy/vault-host/hinddian-memory-cli" /usr/local/bin/hinddian-memory-cli
install -d -m 755 /var/lib/hinddian /var/lib/hinddian/drafts /var/lib/hinddian/agent_corrections
install -m 644 "$REPO"/classify/deploy/hinddian-classify.{service,timer} \
               "$REPO"/classify/deploy/hinddian-batch-force.{service,timer} /etc/systemd/system/
install -m 644 "$REPO/classify/deploy/logrotate.conf" /etc/logrotate.d/hinddian
systemctl daemon-reload
systemctl enable --now hinddian-classify.timer hinddian-batch-force.timer
echo "ok: $(hinddian-batch gate --json | head -c 120)…"
