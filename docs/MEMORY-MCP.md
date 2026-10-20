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

## 会话 finalize：Jev 在服务端跑

hook 不再自己调 Jev，也不需要客户端 `JEV_BASE_URL`。会话结束（新会话开始 / 空闲 30 分钟 / 切项目）时，
hook `POST /api/memory/finalize`（Bearer `HINDDIAN_MCP_TOKEN`，超时 120s），请求体：

`session_id, project, cwd(仅目录名), repo(git 根目录名), client_id, finalize_reason, turn_count, turns[{text}]`

`turns` 只含 hook 已白名单过的用户轮 + 最终助手轮（`<private>` 已替换）；服务端限制 ≤400 轮、单轮 ≤20k 字、总 ≤200k 字，超出 422。

服务端流程：Jev keep 闸门 + 结构化抽取（`jev.classify_turn`：decision / lesson / preference / open_question）
→ 保留则 `push_draft` 到 `drafts/<project>/session-<id>.md` → 把判断元数据追加到 Jev 判断日志。
Jev 来源顺序：服务端的 `JEV_BASE_URL`（华为上为 Magpie 隧道 `127.0.0.1:3425`）→ 配了 TypeSafe key 时走云端；
都失败 = `source=none`，**不写入**，返回 `retry=true`，客户端保留缓冲按退避重试。LLM 来源一律不自动 keep。

返回：`{ok, outcome: pushed|keep_false|empty|llm_forbidden|jev_unavailable|push_failed, retry, source, keep, pushed, draft_path}`。
服务端不可达 / 5xx / `retry=true` → 客户端不丢缓冲，下次 finalize 重试（最多 `HINDDIAN_FINALIZE_MAX_ATTEMPTS` 次）。

项目归属：hook 给的 project > repo / cwd 目录名命中已知项目 > repo 名（新项目，等面板批准）> Jev 读出的项目 > `通用-未定`。

## Jev 判断记录

服务端每次 finalize 都追加到 `HINDDIAN_JEV_LOG`（默认 `/var/lib/hinddian/jev-decisions.jsonl`，超 2MB 轮转为 `.1`，只保留一代），
字段只含元数据：`session_id, project, cwd, host(=client_id), finalize_reason, jev_source, keep, confidence, outcome, error, turn_count, pushed, draft_path, ts`。
**不含会话正文。**

面板「草稿」页顶部「Jev 判断记录」读 `GET /api/jev-decisions`（AUTH_TOKEN）：最近记录 + 每个客户端最后一次 finalize 时间 + 24h 按来源计数，
某个客户端长时间没有记录即「客户端沉默」（hook 没触发 finalize 或客户端插件未更新）。

`POST /api/memory/gates/report`（#16 的客户端上报）保留兼容旧插件；新 hooks 不再调用。
`HINDDIAN_CLIENT_ID`（或配置文件 `client_id`）覆盖默认主机名。`GET /api/memory/jev-backend` 为 `gates/backend` 的别名，`setup.py --check` 用它显示服务端 Jev 后端。
