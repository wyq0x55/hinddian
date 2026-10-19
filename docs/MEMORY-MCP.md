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
