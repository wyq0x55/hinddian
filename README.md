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

WebDAV syncs **library / settings / providers** (whole-file LWW). It does **not** sync
hook script files under `/usr/local/lib/hinddian-magpie/`.

Durable install path:

1. DMIT (source of truth): copy `deploy/magpie/*` → `/usr/local/lib/hinddian-magpie/`,
   run `python3 apply_library.py` then `python3 disable_otel.py`, then `magpie webdav now`.
2. Library hook commands bootstrap from `http://124.70.90.224/hinddian-static/` on first
   run (download `magpie-hooks.tgz` when missing/outdated). Other PCs only need a WebDAV
   pull; opening a session installs scripts automatically.
3. Manual one-liner if you want scripts before the next session:
   `curl -fsSL http://124.70.90.224/hinddian-static/install.sh | bash`
4. Keep OTLP off: settings `otel.enabled=false` (synced) + `/etc/magpie.env`
   `MAGPIE_OTEL_ENABLED=0` (local only).

## Jev

Primary: Magpie local gateway `POST /v1/systemone` (Bearer `magpie`, model `typesafe/jev-latest`). On Magpie hosts the hooks call it directly; on Huawei `magpie-tunnel.service` forwards `:3425` to DMIT Magpie. Add the provider once on Magpie: `magpie provider add typesafe <key>` then `magpie provider models typesafe +jev-latest`. Optional cloud: `TYPESAFE_API_KEY`. Else LLM fallback `group/auto-flash`.

## Docs

See `ARCHITECTURE.md` and vault `项目/笔记系统/MAGPIE-MCP.md`.
