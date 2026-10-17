# Architecture — hinddian (v0.5)

## 一句话

**会话是原料，原子笔记才是记忆；权威在 Obsidian，Hindsight 只做最后一层索引；Agent 只走 hinddian-memory MCP。**

## 流水线

```
收件箱 → 过滤 → 隔离 | drafts/<project>/
                       ↓
              turn-end：Jev(+小模型) 只分析本轮 → push_draft
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

TYPESAFE_API_KEY 放在 `/opt/hinddian/.env`（勿进 git）。用于：should-recall、项目匹配、本轮是否值得记、类型/项目分类、写入四态。低置信度 → Magpie 小模型或跳过。

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
| `deploy/magpie/*` | SessionStart / TurnEnd hooks + Library 切换 |
