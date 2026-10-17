---
name: hinddian-hooks
description: Install hinddian Magpie session-start / turn-end hooks on this computer (WebDAV does not sync Magpie hooks).
---

# hinddian-hooks

Magpie **WebDAV does not sync hooks** (upstream `library.Bundle` has no `Hooks` field).
MCP / skills / instructions sync; the Hooks panel on another PC stays empty until you install locally.

## Windows (once after WebDAV pull)

In PowerShell:

```powershell
magpie webdav now
py -3 "$env:USERPROFILE\.config\magpie\library\skills\hinddian-hooks\install.py"
magpie library sync
```

If the skill path differs, search:

```powershell
Get-ChildItem -Path "$env:USERPROFILE\.config\magpie","$env:APPDATA\magpie","$env:LOCALAPPDATA\magpie" -Recurse -Filter install.py -ErrorAction SilentlyContinue | Where-Object { $_.Directory.Name -eq 'hinddian-hooks' }
```

Then open Magpie → **Library → Hooks**. You should see:

- `hinddian-session-start` (session-start)
- `hinddian-turn-end` (turn-end)

## Linux / macOS

```bash
magpie webdav now
python3 ~/.config/magpie/library/skills/hinddian-hooks/install.py
magpie library sync
```

## Do not

- Do not run `apply_library.py` on non-DMIT hosts (library SoT is DMIT).
- Do not expect WebDAV alone to fill the Hooks panel — that is a Magpie limitation until upstream carries hooks.
