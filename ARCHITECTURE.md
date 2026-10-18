# Architecture — hinddian (v0.5+)

## 一句话

**会话是原料，原子笔记才是记忆；权威在 Obsidian，Hindsight 只做最后一层索引；Agent 只走 hinddian-memory MCP。**

## 流水线

```
Agent 会话
  ├─ session-start：finalize 上一会话缓冲 → Jev(keep) → 一次 push_draft
  │                 注入 routing_global / routing_project；Jev should-recall → 按需 recall
  └─ turn-end：白名单抽取（用户 + 最终回复）→ 本机会话缓冲（不远程写）
                       ↓（空闲 ~30min / 换项目 也会 finalize）
              /var/lib/hinddian/drafts/<project>/session-*.md
                       ↓
         分析：新项目攒到阈值(20 会话草稿)你批准 | 已批准增量自动 | 技巧自动
              + 定时 run-force（已批准项目草稿不足阈值也分析）
                       ↓
              batch → 原子笔记（status: active|superseded|obsolete）
                       ↓
              Obsidian（人读 SoT）→ hinddian-hindsight-sync.timer → Hindsight（检索索引）
```

旁路：**门控** `upsert_note` / `suggest_correction`（仪表盘「Agent 修正」）直接动 vault；索引仍靠同步。

**禁止**：Agent 调 Hindsight `retain`；静默硬删笔记。

## 会话桶 + 白名单抽取

| 项 | 行为 |
|----|------|
| 粒度 | 同一 `session_id` 多轮合并为 **一条** 草稿 |
| turn-end | 只追加缓冲，不 `push_draft` |
| finalize | 下次 session-start、空闲默认 1800s（`HINDDIAN_SESSION_IDLE_SEC`）、或换项目 |
| 白名单 | **用户消息 + 最终助手回复**（截断） |
| 剥掉 | 系统/人设、路由表、MCP/工具 schema、skills 目录、recall 旧记忆正文、工具日志、hook 噪声 |
| 结构化字段 | 定稿后倾向 `decision` / `lesson` / `preference`（Jev 分类） |

阈值 20 = **会话草稿数**，不是回合碎片数。

## Jev（System One）

**写路径（keep / 是否入库）严格：**

1. 本机 Magpie：`POST http://127.0.0.1:3425/v1/systemone`（Bearer `magpie`，model `typesafe/jev-latest`）
2. 可选云端 TypeSafe（`TYPESAFE_API_KEY`）
3. 都失败 → **`source=none`，本轮不写**（无松弛 LLM auto-keep）

**读/UX 路径（should-recall 等）**：本机失败时仍可用 Magpie chat / soft fallback，只影响是否提示 recall，不自动写草稿。

- Magpie 各机：hooks 直连本机网关
- 华为 API / MCP：`magpie-tunnel.service` → DMIT `:3425`
- 仪表盘 / 日志可见 `source=jev:magpie|cloud|none`

用于：should-recall、项目匹配、本会话是否值得记、类型/项目分类、写入四态辅助。

## MCP：hinddian-memory

| 工具 | 作用 |
|------|------|
| `routing_global` / `routing_project` | 路由表 |
| `recall` | 检索（默认过滤非 active）；经 Hindsight，失败可本地笔记兜底 |
| `get_note` / `list_notes` | 读笔记 |
| `upsert_note` | 门控四态：add / update / supersede / noop |
| `suggest_correction` | 入仪表盘「Agent 修正」队列 |
| `push_draft` | hooks / 工具推会话草稿 |

Magpie Library **只挂**本 MCP，不挂原生 Hindsight MCP。

### 门控 upsert 政策

| 类型 | 策略 |
|------|------|
| `tip` / `preference`，或 `face_correction=true` | 可直写 `upsert_note` |
| `decision` / 架构定论 | 须 `user_confirmed=true`，或 `suggest_correction` → 仪表盘批准 |
| 删除 | **禁止硬删**；用 `supersede` / `obsolete` |
| Hindsight | **禁止** Agent `retain` |

修正队列落盘：DMIT `/var/lib/hinddian/agent_corrections/`（`HB_CORRECTIONS`）。

## OTLP

Magpie settings `otel.enabled=false`（WebDAV 同步）；`/etc/magpie.env` 保留 `MAGPIE_OTEL_ENABLED=0` 兜底。记忆主路径是 hooks，不是 OTLP。

## 组件

| 模块 | 职责 |
|------|------|
| `src/hinddian/memory_mcp.py` | MCP + REST（hooks / 仪表盘） |
| `src/hinddian/notes.py` | 原子笔记 / 路由 / 四态 / 修正队列 / 草稿 |
| `skills/hinddian-hooks/jev.py` 等 | Jev + 会话桶 + 白名单（SoT：`skills/hinddian-hooks/`） |
| `classify/hinddian_batch.py` | 草稿批量/增量（DMIT） |
| `deploy/huawei/obsidian_hindsight_sync.py` | Obsidian → Hindsight；timer `hinddian-hindsight-sync` |
| `deploy/magpie/*` | DMIT apply_library；skill 镜像；**WebDAV 不同步 Hooks** |
| `plugins/hinddian/` | Claude / Codex 插件包 |
| `web/` | 仪表盘（图谱、批准、Agent 修正） |

## Magpie 安装 / 市场

- **不能**靠 WebDAV 或单独 `magpie plugin add` 自动写入 Library Hooks。
- 产品路径：`skills/hinddian-hooks` + 本机 **`install.ps1`（Windows）** / `install.py`（Unix）/ 工具 `hinddian_install`。
- 仓库根 `package.json` 供 `magpie plugin add github:wyq0x55/hinddian`。

## Agent plugins (Claude / Codex)

- 包：`plugins/hinddian/` — plugin.json、mcp、hooks（SessionStart + Stop）、skills
- 市场清单：`.claude-plugin/marketplace.json`、`.agents/plugins/marketplace.json`
- Codex 公开目录不接受带 lifecycle hooks 的插件；用 CLI/桌面 + trust hooks

## Skill 副本 SoT

**编辑 `skills/hinddian-hooks/`**，再复制到 `deploy/magpie/skill-hinddian-hooks/` 后由 DMIT `apply_library.py` 发布。两目录应保持一致。
