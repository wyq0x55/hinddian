#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "$0")/../.." && pwd)"
units="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
bin="$HOME/.local/bin"
install -d "$units" "$bin"

wrapper="$(mktemp "$bin/.hinddian-batch.XXXXXX")"
trap 'rm -f -- "$wrapper"' EXIT
printf '#!/usr/bin/env bash\nexec python3 %q "$@"\n' "$repo/classify/hinddian_batch.py" > "$wrapper"
chmod 755 "$wrapper"
mv -fT -- "$wrapper" "$bin/hinddian-batch"

install -m 644 "$repo"/classify/deploy/hinddian-classify.{service,timer} "$units/"
systemctl --user daemon-reload
systemctl --user enable --now hinddian-classify.timer
