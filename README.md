# hinddian

Obsidian 原子笔记为唯一人读来源；**hinddian-memory MCP** 供 Agent 读写路由/召回/写入；Hindsight 仅作最后一层检索索引。

## Quick start (Huawei)

```bash
cp .env.example .env   # fill HINDSIGHT_API_KEY; Jev uses Magpie :3425/v1/systemone (optional TYPESAFE_API_KEY cloud fallback)
pip install -e .
uvicorn hinddian.api:app --host 127.0.0.1 --port 8787
```

MCP: `POST http://127.0.0.1:8787/mcp` (Bearer). Public: `http://<huawei>/hinddian/mcp` via Caddy.

## Magpie

WebDAV syncs MCP / skills / instructions / settings / providers (whole-file LWW).

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
