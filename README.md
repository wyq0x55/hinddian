# hinddian

Obsidian 原子笔记为唯一人读来源；**hinddian-memory MCP** 供 Agent 读写路由/召回/写入；Hindsight 仅作最后一层检索索引。

## Agent plugin install (Claude Code / Codex) — primary

Hindian ships as an **Agent Plugins** package under `plugins/hinddian/` with MCP + SessionStart/Stop hooks.

| Market | MCP + Hooks in one plugin? | Install |
|--------|----------------------------|---------|
| **Claude Code** | **Yes** | marketplace add → install |
| **Codex CLI / desktop** | **Yes** (hooks need user **trust**; public directory rejects hook plugins) | marketplace add → plugin add |
| Magpie Library Hooks | WebDAV **does not** sync Hooks | separate Magpie skill / install.ps1 |

### Claude Code

```bash
claude plugin marketplace add wyq0x55/hinddian
# in session:
# /plugin install hinddian@hinddian-plugins

# or one-shot without marketplace:
claude --plugin-dir ./plugins/hinddian
claude plugin validate ./plugins/hinddian
```

### Codex

```bash
codex plugin marketplace add wyq0x55/hinddian
codex plugin add hinddian@hinddian-plugins
# then enable + review/trust plugin hooks
```

Private repo: sign in to GitHub for Claude/Codex git fetch, or clone and:

```bash
claude --plugin-dir /path/to/hinddian/plugins/hinddian
codex plugin marketplace add /path/to/hinddian
codex plugin add hinddian@hinddian-plugins
```

Details: [`plugins/INSTALL.md`](plugins/INSTALL.md).


## Quick start (Huawei)

```bash
cp .env.example .env   # fill HINDSIGHT_API_KEY; Jev uses Magpie :3425/v1/systemone (optional TYPESAFE_API_KEY cloud fallback)
pip install -e .
uvicorn hinddian.api:app --host 127.0.0.1 --port 8787
```

MCP: `POST http://127.0.0.1:8787/mcp` (Bearer). Public: `http://<huawei>/hinddian/mcp` via Caddy.

## Magpie

WebDAV syncs MCP / skills / instructions / settings / providers (whole-file LWW).

## Magpie install (marketplace-style)

**Can Magpie marketplace one-click install Library Hooks?**  
**No (hard limit).** Upstream Magpie: WebDAV/backup `Bundle` does **not** carry Hooks; `magpie plugin add` is for providers/middleware/tools/pages — enabling a plugin does **not** write Library Hooks.

**Closest marketplace-grade paths that work:**

| Path | User action | Writes Hooks? |
|------|-------------|---------------|
| **A. Library Skills (GitHub)** | Magpie → Library → Skills → paste `wyq0x55/hinddian` → install `hinddian-hooks` → run `install.ps1` once | Yes (after install.ps1) |
| **B. Plugins** | `magpie plugin add github:wyq0x55/hinddian` → agent calls `hinddian_install` (or install.ps1) | Yes (tool/script) |
| **C. WebDAV skill** | `magpie webdav now` then install.ps1 | Yes |

### Windows（推荐 A 或 C）

```powershell
# After skill is present (WebDAV or Library→Skills from GitHub):
magpie webdav now
& "$env:USERPROFILE\.config\magpie\library\skills\hinddian-hooks\install.ps1"
```

Or plugin:

```powershell
magpie plugin add github:wyq0x55/hinddian
# then ask any agent: 安装 hinddian
```

Private repo needs Magpie → Settings → GitHub token.

### Verify

Magpie → **Library → Hooks**: `hinddian-session-start`, `hinddian-turn-end`  
**Library → MCP**: `hinddian-memory`

Do **not** run `apply_library.py` on non-DMIT machines.


**Magpie does NOT sync Hooks yet** (upstream `library.Bundle` has no `Hooks` field).
Turn-end buffers by `session_id` (whitelist user+assistant); finalize on next session-start/idle → one draft.
DMIT keeps hooks locally. Other PCs get the `hinddian-hooks` **skill** via WebDAV, then
run install once so the Hooks panel fills.

1. DMIT: `python3 deploy/magpie/apply_library.py` then `disable_otel.py` then `magpie webdav now`
2. Windows (after pull), PowerShell:
   `py -3 "$env:USERPROFILE\.config\magpie\library\skills\hinddian-hooks\install.py"`
   then `magpie library sync`
3. Open Magpie → Library → Hooks → `hinddian-session-start`, `hinddian-turn-end`
4. OTLP off: settings `otel.enabled=false` + local `MAGPIE_OTEL_ENABLED=0`

Do not run `apply_library.py` on non-DMIT hosts.

## Jev

Primary: Magpie local gateway `POST /v1/systemone` (Bearer `magpie`, model `typesafe/jev-latest`). On Magpie hosts the hooks call it directly; on Huawei `magpie-tunnel.service` forwards `:3425` to DMIT Magpie. Add the provider once on Magpie: `magpie provider add typesafe <key>` then `magpie provider models typesafe +jev-latest`. Optional cloud: `TYPESAFE_API_KEY`. If both fail: **do not write** this session (`source=none`). No loose LLM auto-keep.

## Docs

See `ARCHITECTURE.md` and vault `项目/笔记系统/MAGPIE-MCP.md`.
