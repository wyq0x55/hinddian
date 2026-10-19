#!/bin/bash
# Install the vault-host side of hinddian. Run as root from a checkout of the repo on the vault host
# (e.g. /opt/hinddian). Re-run after EVERY git pull / rsync of the checkout — otherwise the
# CLI entrypoints go stale and timers can hit: bash: /usr/local/bin/hinddian-batch: Permission denied (rc=126).
#
#   hinddian-batch        drafts → atomic notes (systemd timers below)
#   hinddian-memory-cli   vault ops the API host calls over SSH
#
# Entry points under /usr/local/bin are small bash wrappers (chmod 755) that exec python3 on the
# checkout scripts, so a non-executable .py after rsync still runs. We also chmod 755 the targets
# (repo stores them as 100755) and refresh systemd units.
# Prereq: an OpenAI-compatible gateway for the batch LLM at HB_GATEWAY (default 127.0.0.1:3425).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
BATCH_PY="$REPO/classify/hinddian_batch.py"
CLI_PY="$REPO/deploy/vault-host/hinddian-memory-cli"
chmod 755 "$BATCH_PY" "$CLI_PY" "$REPO/classify/deploy/install-vault-host.sh"

install_py_wrapper() {
  local dest="$1" target="$2"
  cat >"$dest" <<EOF
#!/bin/bash
exec python3 "$target" "\$@"
EOF
  chmod 755 "$dest"
}
install_py_wrapper /usr/local/bin/hinddian-batch "$BATCH_PY"
install_py_wrapper /usr/local/bin/hinddian-memory-cli "$CLI_PY"

install -d -m 755 /var/lib/hinddian /var/lib/hinddian/drafts /var/lib/hinddian/agent_corrections
install -m 644 "$REPO"/classify/deploy/hinddian-classify.{service,timer} \
               "$REPO"/classify/deploy/hinddian-batch-force.{service,timer} /etc/systemd/system/
install -m 644 "$REPO/classify/deploy/logrotate.conf" /etc/logrotate.d/hinddian
systemctl daemon-reload
systemctl enable --now hinddian-classify.timer hinddian-batch-force.timer
echo "ok: $(hinddian-batch gate --json | head -c 120)…"
