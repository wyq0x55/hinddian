---
name: setup
description: After installing the hinddian plugin, verify MCP connection and explain hooks trust / Windows Python.
---

# hinddian setup

1. Confirm MCP: ask the agent to list tools or call `routing_global` / `recall` on **hinddian-memory**.
2. **Claude Code**: hooks from the plugin load with the plugin. New session → SessionStart; after a reply → Stop buffers the turn.
3. **Codex**: enable the plugin, then **review and trust** plugin hooks (Codex skips untrusted plugin hooks). Hooks work best on Codex desktop / local CLI, not the public web directory path.
4. Optional env: `HINDDIAN_MEMORY_URL` (default `http://124.70.90.224/hinddian`), `HINDDIAN_MCP_TOKEN` if MCP needs Bearer auth.
5. Need Magpie hosts too: Magpie WebDAV does **not** sync Library Hooks — use Magpie skill `hinddian-hooks` install.ps1 on each PC.

Do not put secrets in the repo. Prefer Magpie local Jev at `127.0.0.1:3425` when Magpie is the gateway.
