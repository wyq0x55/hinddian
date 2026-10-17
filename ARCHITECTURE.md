# Architecture — hinddian

## 一句话

**会话是原料，主题才是记忆；权威在 Obsidian，Hindsight 是 agent 检索层。**

## 三层模型

```
┌─────────────────────────────────────────────────────────┐
│  原料层 (feedstock)                                      │
│  OTLP / Magpie export / 手动 ingest                      │
│  → inbox → filter → quarantine | processed               │
│  不当笔记；可丢、可隔离                                   │
└──────────────────────────┬──────────────────────────────┘
                           │ distill (LLM)
                           ▼
┌─────────────────────────────────────────────────────────┐
│  主题层 (human SoT) — Obsidian Markdown                  │
│  • 项目主题：vault/项目/<名>/记忆.md                      │
│  • 全局主题：00-系统/agent使用技巧.md                     │
│  • 待入库：可先写 pending merge，人确认后再定稿           │
│  人可观看 / 修改 / 删除                                   │
└──────────────────────────┬──────────────────────────────┘
                           │ retain / forget (document_id)
                           ▼
┌─────────────────────────────────────────────────────────┐
│  检索层 (agent) — Hindsight                              │
│  Recall MCP；同一 document_id upsert                     │
│  删 Obsidian 笔记 → forget；不反向改 vault                │
└─────────────────────────────────────────────────────────┘
```

## 权威与同步方向

| 方向 | 允许？ | 说明 |
|------|--------|------|
| Obsidian → Hindsight | ✅ | 主题定稿 / 改 / 删 触发 retain 或 forget |
| Hindsight → Obsidian | ❌ | 避免双写打架 |
| 原料 → 主题 | ✅ | distill propose merge（非一会话一笔记） |
| 原料 → Hindsight | 可选过渡 | 旧 retain-原文试点可并存；目标是主题 document_id |

## Topic 规则

### 1. 固定全局主题「agent使用技巧」

- `document_id`: `topic/agent-usage-tips`
- 默认 vault 路径: `00-系统/agent使用技巧.md`
- 兼容别名: `Agent使用技巧.md`（vault 根）
- **每个会话、每个项目**提炼时都可往此主题贡献片段（通用技巧、提示词习惯、MCP/工具踩坑等）

### 2. 项目主题

- vault 目录 `项目/<ProjectName>/` → slug（小写、非字母数字转 `-`）
- `document_id`: `topic/project/<slug>`
- 笔记路径优先: `项目/<ProjectName>/记忆.md`，其次 `PROJECT.md`

### 3. Distill 行为（目标态）

- 输出：**合并提案**（append / section upsert），带目标 `document_id` 列表
- 至少检查是否应写入 `topic/agent-usage-tips`
- **禁止**默认创建 `会话-YYYYMMDD-xxx.md` 式一会话一笔记

## 仪表盘（第一期）

Magpie 风格深色单页，观测：

1. 收件箱积压（inbox count / 最老条目）
2. 过滤结果（quarantine 原因分布）
3. 提炼进度（jobs: pending / running / done / failed）
4. 待入库 / 主题合并历史

数据来自本地 SQLite status store（可扫 inbox 目录做轻量统计）；空库用 demo 数据。

## 组件边界

| 模块 | 职责 | 本期 |
|------|------|------|
| `topics.py` | document_id ↔ vault 路径 | ✅ |
| `store.py` | 管线状态 SQLite | ✅ |
| `api.py` | FastAPI 只读观测 + health | ✅ |
| `web/` | 深色仪表盘 | ✅ |
| `distill_hooks.py` | 如何 upsert 主题 | stub |
| `sync_hindsight.py` | retain/forget | stub |
| 真实 worker / OTLP | 仍在 session-distill | 外挂，后续迁入 |

## 落地顺序（建议）

1. ✅ 本仓库骨架 + 仪表盘
2. 接 inbox 真实扫描 + filter 原因从日志/quarantine 读
3. 改 distill：主题 upsert + 固定写入 agent使用技巧
4. Obsidian→Hindsight sync worker
5. （可选）网页内编辑 = 改 vault 文件的 UI
