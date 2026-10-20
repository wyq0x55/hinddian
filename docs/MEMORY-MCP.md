# hinddian-memory MCP（现行）

> 权威说明在本仓库。Vault 旧笔记若仍写「直连 hindsight MCP / retain」或以 Magpie 为记忆系统，一律以本文为准。

## 应挂的 MCP

| 名 | URL | 用途 |
|----|-----|------|
| **`hinddian-memory`** | `https://<api-host>:8444/hinddian/mcp`（Bearer `HINDDIAN_MCP_TOKEN`） | Agent **唯一**记忆入口：路由 / recall / 门控写入 / push_draft |

Header：`Authorization: Bearer <HINDDIAN_MCP_TOKEN>`（常与 Hindsight tenant key 同源；只放 secrets，勿进笔记）。

写入分工：记住/纠正用 `upsert_note`（tip/preference/lesson）或 `suggest_correction`（decision）；**不要**用手调 `push_draft` 代替纠正——草稿只进批处理蒸馏，不进「Agent 修正」队列，空 ops 时面板上看不到改动。

## 禁止 / 已移除

| 项 | 说明 |
|----|------|
| 原生 **`hindsight` MCP** | **不要**挂给 Agent；不得 `retain` |
| 旧 vault 直写 MCP | 人读用 Obsidian App / LiveSync |
| 把 Magpie 当作记忆产品 | Magpie 只是可选宿主；记忆系统是 hinddian |

Hindsight bank（`HINDSIGHT_BANK`，默认 `hinddian`） 仍由 API 主机 **`hinddian-hindsight-sync.timer`** 从 Obsidian active 笔记同步索引；Agent 只经 hinddian-memory 的 `recall`。

`recall` 的行为：

- 每条笔记只返回一行（Hindsight 按事实召回，同一笔记的多条事实合并，`facts` 为命中数，分数取最高）。
- 带 `project` 不带 `type`：返回该项目笔记 **+ 全局技巧**（`tags_match: any_strict`）；带 `type` 时按类型严格过滤。
- 插件的自动召回会带上会话开始时从 cwd 匹配到的项目。

## Host hooks

- **首选**：Claude / Codex 插件（`plugins/hinddian/`）自带 lifecycle hooks。
- **可选 Magpie**：WebDAV 不同步 Hooks → [`adapters/magpie/README.md`](../adapters/magpie/README.md)。

## Jev 判断上报（客户端判断，服务端只记录）

Jev 仍在客户端 hooks 里跑（本地 Magpie → 云端；都失败 = `source=none`，不写入，不让 LLM 自动 keep）。
每次 finalize 判断完（含 `none`、`keep=false`、Jev 不可达被延后、finalize 异常），hook 都会
**fire-and-forget** 地 `POST /api/memory/gates/report`（Bearer `HINDDIAN_MCP_TOKEN`，超时 4s，失败静默吞掉，绝不阻塞 hook）。

上报字段只含元数据：`session_id, project, cwd(仅目录名), host, event(finalize|turn), finalize_reason,
jev_source, keep(bool|null), confidence, outcome, error(≤200 字，疑似密钥会脱敏), turn_count, pushed, draft_path, ts`。
**不含会话正文。** 请求体 >4KB 或字段类型不对返回 422。

服务端追加到 `HINDDIAN_JEV_LOG`（默认 `/var/lib/hinddian/jev-decisions.jsonl`，超 2MB 轮转为 `.1`，只保留一代）。
面板「草稿」页顶部「Jev 判断记录」读 `GET /api/jev-decisions`（AUTH_TOKEN）：最近记录 + 每台主机最后上报时间 + 24h 按来源计数，
某台主机长时间不上报即「客户端沉默」。

客户端开关：`HINDDIAN_REPORT_JEV=0` 关闭上报；`HINDDIAN_CLIENT_ID`（或配置文件 `client_id`）覆盖默认主机名。
`GET /api/memory/jev-backend` 现为 `gates/backend` 的别名。
