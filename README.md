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

WebDAV syncs **library / settings / providers** (whole-file LWW).

Hook scripts are **embedded inside library hook `command` strings** (gzip+base64
self-extract on first run into `~/.config/magpie/hinddian-hooks/`). Other computers
only need `magpie webdav now` — no `/usr/local/lib` install and no HTTP bootstrap.

1. DMIT (library SoT): run `python3 deploy/magpie/apply_library.py` then
   `python3 deploy/magpie/disable_otel.py`, then `magpie webdav now`.
2. Other PCs: `magpie webdav now` (or wait ~3m), open a new session.
3. OTLP off: settings `otel.enabled=false` (synced) + local `/etc/magpie.env`
   `MAGPIE_OTEL_ENABLED=0`.

Do **not** run `apply_library.py` on non-DMIT hosts (LWW overwrite risk).

## Jev

Primary: Magpie local gateway `POST /v1/systemone` (Bearer `magpie`, model `typesafe/jev-latest`). On Magpie hosts the hooks call it directly; on Huawei `magpie-tunnel.service` forwards `:3425` to DMIT Magpie. Add the provider once on Magpie: `magpie provider add typesafe <key>` then `magpie provider models typesafe +jev-latest`. Optional cloud: `TYPESAFE_API_KEY`. Else LLM fallback `group/auto-flash`.

## Docs

See `ARCHITECTURE.md` and vault `项目/笔记系统/MAGPIE-MCP.md`.
