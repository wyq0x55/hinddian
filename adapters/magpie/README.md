# Magpie adapter (optional)

**hinddian core does not depend on Magpie.** This directory is a thin host adapter for machines that still run Magpie daily.

| Path | Role |
|------|------|
| `skills/hinddian-hooks/` | Magpie Library skill + installers (`install.ps1` / `install.py`) — SoT under adapters |
| `deploy/` | DMIT `apply_library.py`, hook scripts, skill mirror |
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

Do **not** run `apply_library.py` on non-DMIT machines.

## Relation to core

- Memory API / MCP: hinddian-memory (Huawei) — host-agnostic
- Jev: any OpenAI-compatible System One at `JEV_BASE_URL` (default `http://127.0.0.1:3425/v1/systemone`). Magpie may expose that port on some hosts; it is not required branding.
- Primary product install: Claude Code / Codex plugin (`plugins/hinddian/`)

## Dual locations (compat)

| Path | Why |
|------|-----|
| `adapters/magpie/` | **Documented home** of the optional Magpie adapter |
| `skills/hinddian-hooks/` | Magpie GitHub skill discovery still probes repo `skills/` — keep in sync with `adapters/magpie/skills/hinddian-hooks/` |
| `deploy/magpie/` | DMIT `apply_library.py` historical path — mirror of `adapters/magpie/deploy/` |

Edit **`adapters/magpie/skills/hinddian-hooks/`** first, then copy to `skills/hinddian-hooks/` and deploy skill mirrors.
