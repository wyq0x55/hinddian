# hinddian

Obsidian 原子笔记为唯一人读来源；**hinddian-memory MCP** 供 Agent 读写路由/召回/写入；Hindsight 仅作最后一层检索索引。

## Quick start (Huawei)

```bash
cp .env.example .env   # fill HINDSIGHT_API_KEY; optional TYPESAFE_API_KEY for Jev
pip install -e .
uvicorn hinddian.api:app --host 127.0.0.1 --port 8787
```

MCP: `POST http://127.0.0.1:8787/mcp` (Bearer). Public: `http://<huawei>/hinddian/mcp` via Caddy.

## Magpie

1. Install hooks: copy `deploy/magpie/*.py` → `/usr/local/lib/hinddian-magpie/`
2. On DMIT Magpie host: `python3 deploy/magpie/apply_library.py` then `python3 deploy/magpie/disable_otel.py`
3. Other PCs: Magpie sync **pull first**, then apply / let settings sync (`otel.enabled=false`)

## Jev

Set `TYPESAFE_API_KEY` in `/opt/hinddian/.env` or `/etc/hinddian-memory.env`. Without it, gates fall back to Magpie `group/auto-flash`.

## Docs

See `ARCHITECTURE.md` and vault `项目/笔记系统/MAGPIE-MCP.md`.
