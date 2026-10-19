---
name: setup
description: Configure or troubleshoot the hinddian plugin (server URL + token, MCP connection, hooks trust).
---

# hinddian setup

Configuration is one command the **user** runs in a terminal — do not ask for or handle the token yourself:

```bash
python3 "<plugin root>/scripts/setup.py"            # interactive (token not echoed)
python3 "<plugin root>/scripts/setup.py" --check    # self-check only
```

The SessionStart hook prints the exact path when hinddian is not configured. `setup.py` writes
`~/.config/hinddian/config.json` (mode 600), shared by the hooks and the local MCP bridge, and checks
TLS, auth and the MCP tool list.

Troubleshooting:
- `[fail] … HTTP 410`: only the retired `:80` entry returns 410 (`:8444` does not). If your URL already has `:8444`, check that `HINDDIAN_MEMORY_URL` is not still `http://…/hinddian` (env overrides config). Use `https://<host>:8444/hinddian`.
- `[fail] 鉴权失败`: the token must be the server's `HINDDIAN_MCP_TOKEN`, not the dashboard `AUTH_TOKEN`.
- Certificate errors: re-run with `--ca /path/to/fullchain.pem` (self-signed server).
- MCP shows 0 tools: not configured yet, or the server is unreachable — run `--check`.
- **Codex**: review and **trust** the plugin hooks (Codex skips untrusted plugin hooks).
- Magpie hosts: Magpie WebDAV does not sync Library Hooks — use the `hinddian-hooks` skill installer on each PC.
