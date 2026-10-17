# hinddian

**Hindsight + Obsidian** 双管线记忆：主题笔记、会话提炼、Magpie 风格管线仪表盘。

> Session is feedstock. **Topic documents** are memory.  
> 会话是原料；**主题文档**才是记忆。

## Why hinddian

旧路径「一条会话一条笔记」会把同一主题拆碎，人改不动，agent 也召不准。hinddian 把管线收成三层：

| 层 | 角色 | 存储 |
|----|------|------|
| **原料** | OTLP / 导出 / inbox，可丢可隔离 | inbox / quarantine / processed |
| **主题（人读 SoT）** | 按项目目录 + 固定全局主题合并的 Markdown | Obsidian vault |
| **检索（agent）** | 可召回片段；主题变更后再 retain / forget | Hindsight Recall MCP |

**权威在 Obsidian。** 人改/删主题笔记 → 再同步到 Hindsight。不要在 Hindsight 里单独养一套「人写笔记」。

## Fixed global topic

每个会话每个项目都可能贡献的通用主题：

| document_id | vault 路径（约定） | 说明 |
|-------------|-------------------|------|
| `topic/agent-usage-tips` | `00-系统/agent使用技巧.md`（或根目录 `Agent使用技巧.md`） | agent 使用技巧，跨项目归并 |

项目主题：`topic/project/<slug>` → 对应 vault 项目目录下的 `记忆.md` / `PROJECT.md`。

提炼结果应 **propose merge into topic docs**，默认不再写「一会话一笔记」。

## Repo layout

```
src/hinddian/     FastAPI + topic resolver + status store + sync stubs
web/              Magpie-like dark dashboard (static SPA)
scripts/          run_dev.sh
deploy/           systemd + Caddy snippet examples
ARCHITECTURE.md   三层模型与同步方向
```

## Quick start (local)

```bash
cd hinddian
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 填本地路径；勿提交真实密钥
./scripts/run_dev.sh
# API  http://127.0.0.1:8787/api/health
# UI   http://127.0.0.1:8787/
```

空库时 API 会返回 **demo 占位数据**，仪表盘看起来是活的。

## Environment (see `.env.example`)

- `VAULT_ROOT` — Obsidian vault 根（例：`/srv/obsidian/vault`）
- `INBOX_DIR` — session-distill inbox（例：`/opt/session-distill/inbox`）
- `HINDSIGHT_BASE_URL` / `HINDSIGHT_MCP_URL` — 勿把 token 写进仓库
- `AUTH_TOKEN` — 仪表盘 / API Bearer（部署时用）
- `STATUS_DB` — SQLite 路径（默认 `./data/hinddian.db`）

## Deploy outline (later)

1. Clone 到华为（或与 session-distill 同机）
2. systemd 跑 `hinddian-api`（见 `deploy/systemd/`）
3. Caddy 反代 + Bearer / basic auth（见 `deploy/caddy.snippet.example`）
4. 接现有 inbox / worker：把 distill 输出改成主题 upsert（`distill_hooks`）
5. Obsidian 改/删 → `sync_hindsight` retain / forget

**本仓库第一期 = 可用骨架 + 架构文档 + 可观测 UI，不是完整生产部署。**

## Related ops notes (not in this repo)

- session-distill：华为 `/opt/session-distill/`
- Hindsight MCP（公网示例）：`http://<host>/hindsight/mcp/wanwan/`（需 Bearer）
- Vault：DMIT `/srv/obsidian/vault`

## License

Private — wyq0x55.
