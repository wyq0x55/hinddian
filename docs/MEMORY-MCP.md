# hinddian-memory MCP（现行）

> 权威说明在本仓库。Vault 旧笔记若仍写「直连 hindsight MCP / retain」或以 Magpie 为记忆系统，一律以本文为准。

## 应挂的 MCP

| 名 | URL | 用途 |
|----|-----|------|
| **`hinddian-memory`** | `https://<api-host>:8444/hinddian/mcp`（Bearer `HINDDIAN_MCP_TOKEN`） | Agent **唯一**记忆入口：路由 / recall / 直接写入 / push_draft |

Header：`Authorization: Bearer <HINDDIAN_MCP_TOKEN>`（常与 Hindsight tenant key 同源；只放 secrets，勿进笔记）。

写入：记住/纠正用 `upsert_note` 或兼容名 `suggest_correction`，所有类型（包括 decision）的 add/update/supersede/obsolete 均直写 Obsidian，不进入 pending 队列。仪表盘审批是可选审阅/旧队列兼容功能；**不要**用手调 `push_draft` 代替纠正——草稿只进批处理蒸馏，不进「Agent 修正」队列，空 ops 时面板上看不到改动。

## 维护取代关系

`upsert_note` 和 `suggest_correction` 共用以下接口：

- `action="update", id="现行笔记 id", supersedes=["旧笔记 id"]`：追加并去重前驱，保留原有 `supersedes`；同步设置旧笔记的 `status: superseded` 和 `superseded_by`。省略 `supersedes` 或传 `[]` 均保留已有关系，不表示撤销退役。
- `action="supersede", successor_id="已有现行笔记 id", supersedes=["旧笔记 id"]`：复用已有 active 笔记作为继任者，不新建笔记。此模式只连接关系，不传 `id`、`target_id` 或正文、分类等字段；正文修改另用 update。
- 不传 `successor_id` 的 supersede 仍按原方式新建继任笔记，需填写完整原子笔记字段。两种 supersede 都要求非空 `supersedes`。
- 重新指定后继时，旧继任者的 `supersedes` 会移除对应旧笔记，避免残留反向关系。

所有关系请求在写入前校验。错误返回 `ok: false` 和明确的 `error`，包括 `invalid_supersedes`、`supersedes_not_found`（附缺失 ids）、`self_supersession`、`supersession_cycle`、`successor_not_active`、`successor_not_found`、`invalid_successor_id`、`successor_id_requires_supersede`、`successor_link_only`、`supersede_needs_predecessors`。update 的目标不存在时返回 `update_needs_existing_id`，不再隐式新增笔记。非法 id 类型返回 `invalid_id`；obsolete/noop 不接受 `supersedes`，返回 `supersedes_not_supported`。

## 禁止 / 已移除

| 项 | 说明 |
|----|------|
| 原生 **`hindsight` MCP** | **不要**挂给 Agent；不得 `retain` |
| 旧 vault 直写 MCP | 人读用 Obsidian App / LiveSync |
| 把 Magpie 当作记忆产品 | Magpie 只是可选宿主；记忆系统是 hinddian |

Hindsight bank（`HINDSIGHT_BANK`，默认 `hinddian`） 仍由 API 主机 **`hinddian-hindsight-sync.timer`** 从 Obsidian active 笔记同步索引；Agent 只经 hinddian-memory 的 `recall`。

`recall` 的行为：

- 默认返回紧凑索引：`id, title, type, date, score`；不含正文。Hindsight 同一笔记多条事实合并，分数取最高。日期来自 vault 的 `updated`（每批最多 20 条，超过继续分批）。候选用 vault 校验存在性、status、project/type，删除/退役立即被滤掉；vault 不可用时返回索引数据并标 `vault_verified: false`，日期缺失为 `null`。
- `recall(query, project, format="full")` 保留原结果结构（Hindsight 的 `text/metadata/scores/facts` 或本地的 `scene/practice/score`），关联笔记的正文/元数据取当前 vault 文件。仪表盘继续使用此格式显示摘要。
- 未关联笔记的 Hindsight 事实保留 `resolvable: false`，其 id 不能传给 `get_note`。
- 带 `project` 不带 `type`：返回该项目笔记 **+ 全局技巧**（`tags_match: any_strict`）；带 `type` 时按类型严格过滤。
- 插件的自动召回会带上会话开始时从 cwd 匹配到的项目，默认附最多 6 条标题（不附摘要）。

逐层读取：`recall` 找相关标题 → `timeline(anchor_id, before=3, after=3)` 看同项目时间上下文 → `get_note(id)` 取全文。
`timeline` 按 `updated` 升序、同日按 id 排序；前后各 0–20 条 active 邻居，并包含锚点（锚点可已退役）。
无锚点返回 `not_found`；锚点无日期返回 `undated`，无日期的邻居省略。
`get_note(id="…")` 保持单对象返回；`get_note(id=["…", "…"])` 一次取最多 20 条，按请求顺序返回数组，缺失项为 `{error: "not_found", id}`。
`list_notes(order="recent")` 按 `updated` 降序；默认仍按标题排序。hooks 的 `GET /api/memory/notes?project=…&limit=6&order=recent` 使用同一 Agent 鉴权。
使用 SSH vault 的安装需要同时更新 `hinddian-memory-cli`；旧客户端仍可单条读取及使用 `format="full"`。

## Obsidian 直接管理记忆

改 Obsidian = 管记忆：正文/frontmatter 修改、`status != active`、删除文件均以 vault 为准。
`get_note`、`list_notes`、本地 recall fallback 每次读取文件并按内容指纹复用解析结果，不从 Hindsight 读取正文。
同长度编辑或同步客户端保留 mtime 也能被识别。
软退役保留全文供历史查阅，但不会出现在 active 列表/召回；删文件后 get_note 返回 not_found。

API 主机的 timer 使用 `OnCalendar=*:0/2`、`AccuracySec=1s`，无随机延迟。
选择日历周期是为了让人工文件改动在正常空闲时最多两分钟开始对齐；`OnUnitActiveSec` 可能被频繁 kick 重置。
索引可见延迟通常在两分钟内，但完成还需导出/索引处理时间；长任务、积压及服务故障不保证两分钟完成。
同步优先删除 gone（含非 active）文档，再 retain 新/改笔记；失败项保留待同步状态供下轮重试。

MCP/REST 直写成功后，API 主机通过后台线程执行
`systemctl --no-block start hinddian-hindsight-sync.service`，请求不等待索引。
此能力由部署的 `hinddian.service` 设置 `HINDDIAN_SYNC_KICK=1`；开发默认关闭。
kick 失败或同步已在运行时由 timer 补齐。直接运行 vault CLI/批处理和人在 Obsidian 改文件同样由 timer 捕获。
无需给 Agent 提供 Hindsight retain 或服务控制工具。

## 双可读笔记契约

人读的正文与 Agent 展开的全文是同一份 Obsidian 原子笔记，不维护另一份摘要数据库。

- **标题即命题**：如“部署前先跑 gate.sh”，标题本身说明规则/决定，避免“部署相关”这样的空标题。
- **frontmatter**：稳定 `id`，`type: decision|lesson|tip`，`project`（技巧为 `global`），`status: active|superseded|obsolete`，`updated`。Agent 写入自动生成这些字段，preference 归一为 tip + preference 标签。
- **正文**：`## 场景`、`## 做法`、`## 理由`。Agent 新建/取代必须填齐 title/scene/practice/reason 和项目（tip 除外）；更新可沿用已有非空字段，缺失返回 `incomplete_note` + fields；软退役只需 id。不知道的事实应先澄清，不编造理由。
- **人写扩展**：非托管 frontmatter 键、段落、引用及悬空链接继续 round-trip 保留；不要求人把自由笔记迁移成机器专用文件。

Agent 的 memory map：SessionStart 固定前缀仅包含规则和排序项目名；
易变部分随后附当前项目最近标题。`routing_project` 返回当前状态，以及 decision/lesson 分组的
`id/title/updated`（各最多 40 条，附总数）；更多标题用 list_notes/recall，相关正文再 get_note。
compact recall 的 `date` 是 vault 的 `updated`，保留已有字段名以兼容客户端。
人工编辑后可同步更新 `updated`，未改日期也会按正文变化重新建索引；不引入会话版本缓存。

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
