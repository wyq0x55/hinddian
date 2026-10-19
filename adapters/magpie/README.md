# Magpie adapter (optional)

**hinddian core does not depend on Magpie.** This directory is a thin host adapter for machines that still run Magpie daily.

| Path | Role |
|------|------|
| `skills/hinddian-hooks/` | Magpie Library skill + installers (`install.ps1` / `install.py`) — SoT under adapters |
| `deploy/` | vault host `apply_library.py` (reads the skill pack from `skills/hinddian-hooks/`) |
| `plugin/` | Magpie/`opencode` plugin UI (`hinddian_install` tool) |
| `package.json` | Magpie-local package metadata |

## Install (Magpie hosts only)

WebDAV **does not sync Library Hooks**. After skill is present:

```powershell
# Windows
magpie webdav now
& "$env:USERPROFILE\.config\magpie\library\skills\hinddian-hooks\install.ps1"
```

```bash
# Linux / macOS
magpie webdav now
python3 "$HOME/.config/magpie/library/skills/hinddian-hooks/install.py"
```

Do **not** run `apply_library.py` on non-vault-host machines.

## Relation to core

- Memory API / MCP: hinddian-memory (API host) — host-agnostic
- Jev: any OpenAI-compatible System One at `JEV_BASE_URL` (default `http://127.0.0.1:3425/v1/systemone`). Magpie may expose that port on some hosts; it is not required branding.
- Primary product install: Claude Code / Codex plugin (`plugins/hinddian/`)

## Dual locations (compat)

| Path | Why |
|------|-----|
| `adapters/magpie/` | **Documented home** of the optional Magpie adapter |
| `skills/hinddian-hooks/` | Magpie GitHub skill discovery still probes repo `skills/` — generated mirror |

Hook scripts come from repo `hooks/` (+ `src/hinddian/jev.py`); the Magpie-only installer files
(`SKILL.md`, `install.*`, `embed_hooks.py`) live in `adapters/magpie/skills/hinddian-hooks/`.
After editing either, run `python tools/sync_hooks.py` — it regenerates every copy and
`HOOKS_VERSION` (content hash, so Magpie hosts re-extract automatically). CI fails on drift.

Hooks need `HINDDIAN_MEMORY_URL` (https) and `HINDDIAN_MCP_TOKEN`; installers need
`HINDDIAN_MCP_URL` or `HINDDIAN_MEMORY_URL`. There is no built-in server address.
