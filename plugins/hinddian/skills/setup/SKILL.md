---
name: setup
description: After installing the hinddian plugin, verify MCP connection and explain hooks trust / Windows Python.
---

# hinddian setup

1. Confirm MCP: ask the agent to list tools or call `routing_global` / `recall` on **hinddian-memory**.
2. **Claude Code**: hooks from the plugin load with the plugin. New session → SessionStart; after a reply → Stop buffers the turn.
3. **Codex**: enable the plugin, then **review and trust** plugin hooks (Codex skips untrusted plugin hooks). Hooks work best on Codex desktop / local CLI, not the public web directory path.
4. Required env (no built-in server): `HINDDIAN_MEMORY_URL` (https base incl. `/hinddian`, e.g. `https://<host>:8444/hinddian`) and `HINDDIAN_MCP_TOKEN`. The MCP config expands both; hooks refuse plain http to non-loopback hosts. Self-signed server cert: `HINDDIAN_CA_FILE` (hooks) + `NODE_EXTRA_CA_CERTS` (Claude Code MCP).
5. Need Magpie hosts too: Magpie WebDAV does **not** sync Library Hooks — use Magpie skill `hinddian-hooks` install.ps1 on each PC.

Do not put secrets in the repo. Prefer Magpie local Jev at `127.0.0.1:3425` when Magpie is the gateway.
