---
name: hinddian-hooks
description: Install hinddian Magpie MCP + session-start/turn-end hooks on this computer (WebDAV does not sync Hooks). One-step product install.
---

# hinddian (Magpie install)

Magpie **WebDAV does not sync Hooks** (upstream `library.Bundle` has no `Hooks` field).
Skills / MCP / instructions sync; Hooks must be written **locally** once per PC.

This skill is the product installer: **MCP (`hinddian-memory`) + Hooks** in one step.

## Behaviour (after install)

- **session-start**: finalize prior session buffer (Jev keep → one `push_draft`); inject routing; should-recall gate
- **turn-end**: whitelist extract (user + final assistant only) → append **session buffer** (no per-turn draft)
- **Jev**: Magpie `127.0.0.1:3425/v1/systemone` → optional TypeSafe cloud → if both fail **do not write** (`source=none`)
- Gate threshold **20** = ~session drafts / project, not turn scraps

## Windows (once after WebDAV / GitHub skill pull)

PowerShell:

```powershell
magpie webdav now
# preferred one-liner:
& "$env:USERPROFILE\.config\magpie\library\skills\hinddian-hooks\install.ps1"
# or:
py -3 "$env:USERPROFILE\.config\magpie\library\skills\hinddian-hooks\install.py"
magpie library sync
```

If the skill path differs:

```powershell
Get-ChildItem -Path "$env:USERPROFILE\.config\magpie","$env:APPDATA\magpie","$env:LOCALAPPDATA\magpie" -Recurse -Filter install.py -ErrorAction SilentlyContinue | Where-Object { $_.Directory.Name -eq 'hinddian-hooks' }
```

Then Magpie → **Library → Hooks**:

- `hinddian-session-start` (session-start)
- `hinddian-turn-end` (turn-end)

And **Library → MCP** should list `hinddian-memory`.

## Linux / macOS

```bash
magpie webdav now
python3 ~/.config/magpie/library/skills/hinddian-hooks/install.py
magpie library sync
```

## GitHub skill install (optional)

If Magpie can install skills from GitHub on this build:

```text
Library → Skills → from GitHub → wyq0x55/hinddian
(path: deploy/magpie/skill-hinddian-hooks)
```

Then still run `install.py` / `install.ps1` once so **Hooks** land in local `library.json`.

## Do not

- Do not run `apply_library.py` on non-DMIT hosts (library SoT is DMIT).
- Do not expect WebDAV alone to fill the Hooks panel.
