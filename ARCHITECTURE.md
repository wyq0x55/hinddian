# Architecture — hinddian (v0.6+)

## 一句话

**会话是原料，原子笔记才是记忆；权威在 Obsidian，Hindsight 只做最后一层索引；Agent 只走 hinddian-memory MCP。宿主无关（Claude / Codex / 其它）；Magpie 仅为可选适配器。**

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
| finalize | 下次 session-start、空闲默认 1800s（`HINDDIAN_SESSION_IDLE_SEC`）、或换项目；在**后台进程**里跑，宿主的 hook 立即返回 |
| 失败 | Jev / 服务器暂时不可用 → 缓冲保留，指数退避重试（5min 起，最多 8 次或 7 天后放弃） |
| 长会话 | 送 Jev 时保留开头 4k + 结尾 8k 字符（结论通常在结尾） |
| 清理 | 已定稿缓冲（含对话原文）3 天后删除；目录 `~/.config/hinddian/hooks/sessions`（旧 magpie 目录自动迁移） |
| 传输 | 只走 https（本机 loopback 例外）；未配置 `HINDDIAN_MEMORY_URL` 时 hooks 不缓冲任何内容 |
| 白名单 | **用户消息 + 最终助手回复**（截断） |
| 剥掉 | 系统/人设、路由表、MCP/工具 schema、skills 目录、recall 旧记忆正文、工具日志、hook 噪声 |
| 结构化字段 | 定稿后倾向 `decision` / `lesson` / `preference`（Jev 分类） |

阈值 20 = **会话草稿数**，不是回合碎片数。

## Jev（System One，可选）

**写路径（keep / 是否入库）严格：**

1. 本机 / 隧道：`POST {JEV_BASE_URL}`（默认 `http://127.0.0.1:3425/v1/systemone`）
2. 可选云端 TypeSafe（`TYPESAFE_API_KEY`）
3. 都失败 → **本轮暂不写**（无松弛 LLM auto-keep），缓冲留着退避重试

**读/UX 路径（should-recall 等）**：本机失败时可用 chat completions soft fallback，只影响是否提示 recall，不自动写草稿。

- 任意暴露 System One 的本机网关均可；与 Magpie 产品身份无关
- API 主机 API 可选经 SSH LocalForward 使用远端 `:3425`（infra，非产品品牌）
- 仪表盘 / 日志：`source=jev:local|cloud|none`（`jev:magpie` 旧标签归一为 `jev:local`）

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

任何宿主 **只挂**本 MCP，不挂原生 Hindsight MCP 给 Agent。

### 两个通道，两把钥匙

| 通道 | 路由 | 凭据 | 能做什么 |
|------|------|------|----------|
| Agent | `/mcp`、`/api/memory/*` | `HINDDIAN_MCP_TOKEN` | 读、门控写、推草稿、提修正建议 |
| 仪表盘 | `/`、`/api/*` | `AUTH_TOKEN`（≠ MCP token；:8443 mTLS 后由 Caddy 注入） | 批准 / 拒绝修正、批准项目批处理 |

两把钥匙缺一或相同 → 503（fail closed）。批准接口只在仪表盘通道。

`recall`：Hindsight 原样查询，项目 / 类型作 tag 过滤（不拼进查询文本）；Hindsight 不可用时退回 vault 本地 bigram 检索（中文可用）。

### 门控 upsert 政策

| 类型 | 策略 |
|------|------|
| `tip` / `preference` / `lesson` | 可直写 `upsert_note` |
| 新增 / 修改 / 取代 / 作废 `decision` | **一律**入队 → 仪表盘批准；`user_confirmed` / `face_correction` 只是给审批人的说明，服务端不信任 |
| 删除 | **禁止硬删**；用 `supersede` / `obsolete` |
| Hindsight | **禁止** Agent `retain` |

修正队列落盘：vault 主机 `/var/lib/hinddian/agent_corrections/`（`HB_CORRECTIONS`）。

并发：MCP 门控写与 vault 主机 batch 共用 `$HB_BASE/vault.lock`（`HINDDIAN_VAULT_LOCK` 可改）。batch 的 LLM 调用在锁外，落盘前在锁内重读 vault 再应用；batch 互斥锁被占时以退出码 75 报 busy，不再静默成功。

格式：重渲染只改受管字段与段落；人在 Obsidian 里加的 frontmatter 键、段落、引用行、悬空链接原样保留。

## OTLP

记忆主路径是 host hooks + MCP，不是 OTLP。各宿主自行关闭无关遥测即可。

## 组件

| 模块 | 职责 |
|------|------|
| `src/hinddian/memory_mcp.py` | Agent 通道：MCP + hook REST |
| `src/hinddian/api.py` | 仪表盘通道 + 挂载 Agent 通道 |
| `src/hinddian/notes.py` | 原子笔记 / 路由 / 四态门控 / 修正队列 / 草稿 |
| `src/hinddian/note_format.py` | 笔记文件格式（frontmatter / 段落往返保真）、路径安全、vault 锁、解析缓存；notes.py 与 batch 共用 |
| `hooks/` | hook 运行时源码；`tools/sync_hooks.py` 生成 plugin / skill 副本 |
| `src/hinddian/jev.py` | System One 闸门（核心，宿主无关） |
| `plugins/hinddian/` | Claude / Codex 插件包（**首选安装**） |
| `classify/hinddian_batch.py` | 草稿批量/增量（vault 主机） |
| `deploy/api-host/obsidian_hindsight_sync.py` | Obsidian → Hindsight；timer `hinddian-hindsight-sync` |
| `adapters/magpie/` | **可选** Magpie skill / install / vault 主机 apply_library |
| `web/` | 仪表盘（图谱、批准、Agent 修正） |

## Agent plugins (Claude / Codex)

- 包：`plugins/hinddian/` — plugin.json、mcp、hooks（SessionStart + Stop）、skills
- 市场清单：`.claude-plugin/marketplace.json`、`.agents/plugins/marketplace.json`
- Codex 公开目录不接受带 lifecycle hooks 的插件；用 CLI/桌面 + trust hooks

## Magpie adapter（可选）

见 [`adapters/magpie/README.md`](adapters/magpie/README.md)。hook 脚本源码在 `hooks/`，安装器在 `adapters/magpie/skills/hinddian-hooks/`；改完跑 `python tools/sync_hooks.py` 生成各副本；仅 vault 主机 跑 `apply_library.py`。
