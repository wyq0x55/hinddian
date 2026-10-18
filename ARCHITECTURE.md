# Architecture — hinddian (v0.5)

## 一句话

**会话是原料，原子笔记才是记忆；权威在 Obsidian，Hindsight 只做最后一层索引；Agent 只走 hinddian-memory MCP。**

## 流水线

```
收件箱 → 过滤 → 隔离 | drafts/<project>/
                       ↓
              turn-end：白名单抽取 → 会话缓冲；session-start/idle：Jev(keep) → 一次 push_draft
                       ↓
         分析：新项目攒到阈值(20)你批准 | 已批准增量自动 | 技巧自动
              + 定时 run-force（已批准项目草稿不足阈值也分析）
                       ↓
              pi / batch → 原子笔记（status: active|superseded|obsolete）
                       ↓
              Obsidian（人读 SoT）→ 同步 → Hindsight（检索索引）
```

开局：SessionStart hook → routing_global →（匹配项目）routing_project → Jev should-recall 门 → 按需 MCP recall。  
写入：禁止 Agent 调 Hindsight retain；显式 upsert_note 或 turn-end 草稿 → 批量/增量。

## MCP：hinddian-memory

工具：`routing_global` · `routing_project` · `recall`（默认过滤非 active）· `get_note` · `list_notes` · `upsert_note`（四态 add/update/supersede/noop）· `push_draft`  
Magpie Library 只挂本 MCP，不再挂原生 Hindsight MCP。

## Jev（System One）门控

**优先走 Magpie 本机网关**（不要求华为上填云端 `TYPESAFE_API_KEY`）：

- URL：`POST http://127.0.0.1:3425/v1/systemone`（可用 `JEV_BASE_URL` / `MAGPIE_JEV_URL` 覆盖）
- Auth：`Authorization: Bearer magpie`（或 `MAGPIE_GATEWAY_KEY`）
- Model：`typesafe/jev-latest`（Magpie 里需已 `magpie provider add typesafe <key>` 并 expose 模型）
- Magpie 各机：hooks 本机直连网关；写路径 Magpie→cloud，失败不写；会话粒度 push_draft 到华为
- 华为：`magpie-tunnel.service` 把本机 `:3425` 转到 DMIT Magpie；MCP 上的 Jev 同样走该隧道
- 可选云端兜底：`TYPESAFE_API_KEY` → `api.typesafe.ai`；再不行 → Magpie `group/auto-flash`

用于：should-recall、项目匹配、本轮是否值得记、类型/项目分类、写入四态。

## OTLP

Magpie settings `otel.enabled=false`（WebDAV 同步到各机）；`/etc/magpie.env` 保留 `MAGPIE_OTEL_ENABLED=0` 兜底。

## 组件

| 模块 | 职责 |
|------|------|
| `memory_mcp.py` | MCP + REST（hooks） |
| `notes.py` | 原子笔记 / 路由导出 / 四态写入 |
| `jev.py` | Jev 门控 + LLM fallback |
| `classify/hinddian_batch.py` | 草稿批量/增量（DMIT） |
| `deploy/huawei/obsidian_hindsight_sync.py` | Obsidian → Hindsight |
| `deploy/magpie/*` | Hooks 嵌在 library（仅本机）；WebDAV **不同步 hooks**，靠 skill `hinddian-hooks` + 各机 `install.py` 写入 Hooks UI |
