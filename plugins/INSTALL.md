# Install hinddian as an agent plugin (Claude Code / Codex)

This is **not** Magpie’s plugin market. These are **Claude Code** and **Codex / Agent Plugins** marketplace installs.

## What ships in one plugin

| Component | Claude Code | Codex CLI / desktop |
|-----------|-------------|---------------------|
| MCP `hinddian-memory` (HTTP) | Yes (`.mcp.json`) | Yes (`.mcp.json` / `mcp.json`) |
| Lifecycle hooks SessionStart + Stop | Yes | Yes, but **user must trust hooks**; not eligible for public directory with hooks |
| Skills (`setup`, `memory`) | Yes | Yes |

## Claude Code

```bash
# Add this repo as a marketplace, then install
claude plugin marketplace add wyq0x55/hinddian
# or in-session:
# /plugin marketplace add wyq0x55/hinddian
# /plugin install hinddian@hinddian-plugins

# Dev without marketplace:
claude --plugin-dir ./plugins/hinddian
claude plugin validate ./plugins/hinddian
```

## Codex

```bash
codex plugin marketplace add wyq0x55/hinddian
codex plugin add hinddian@hinddian-plugins
# or local:
codex plugin marketplace add ./   # repo root with .agents/plugins/marketplace.json
```

After enable: **review/trust** bundled hooks in Codex settings. Public Codex directory rejects plugins that ship lifecycle hooks — use marketplace / desktop / CLI install.

## Magpie (separate host)

Magpie WebDAV **does not sync Library Hooks**. Use `skills/hinddian-hooks` + `install.ps1`, or Magpie `plugin add` tools — see repo README Magpie section.

## Windows

Need `python3` or `py -3` on PATH for hook scripts.
