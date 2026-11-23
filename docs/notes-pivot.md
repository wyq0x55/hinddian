# hinddian 人读笔记转型

目标是让人回看一段工作时能说清发生了什么、为什么这么做、哪些问题还悬着。Agent 在有需要时把依据和结果说进当前会话，Obsidian / Markdown 是阅读和编辑入口。

## 现有链路（基线 `448eaf7`）

| 环节 | 调用关系 |
| --- | --- |
| 采集 | Claude Code / Codex 的 `Stop` 与 Magpie 的 `turn-end` 最终运行 [`hooks/turn_end.py`](../hooks/turn_end.py)。[`extract.py`](../hooks/extract.py) 留下用户话与最终助手回复，过滤系统、工具和旧注入内容，再由 [`session_buf.py`](../hooks/session_buf.py) 脱敏、按 `session_id` 写本机缓冲。 |
| 定稿及批处理 | `SessionStart` 和 `turn-end` 启动后台 [`finalize.py`](../hooks/finalize.py)，POST `/api/memory/finalize`。服务端 [`session_finalize.py`](../src/hinddian/session_finalize.py) 调用 Jev，`keep` 通过后经 vault 本地或 SSH 写会话草稿。Vault 主机的 timer/审批驱动 [`hinddian_batch.py`](../classify/hinddian_batch.py)，合并草稿到原子笔记。 |
| 自动注入 | `SessionStart` 拉全局路由和最近项目标题，读本机上一会话结语，向宿主输出记忆规则和历史；Claude Code / Codex 的 `UserPromptSubmit` 调 `/api/memory/recall` 并追加匹配标题。插件 `memory` skill 在任务涉及旧决定等场景时主动建议跨会话检索。Magpie 内嵌 `SessionStart` / `turn-end` 命令。 |
| 查询与同步 | 插件的 stdio 桥转发 HTTP `/mcp`，Magpie 可直连 HTTP。 [`memory_mcp.py`](../src/hinddian/memory_mcp.py) 的 `recall` 走 Hindsight、经 Obsidian 文件校验，故障时走 vault 本地搜索。Dashboard 也使用检索。API 主机的 [`同步服务`](../deploy/api-host/obsidian_hindsight_sync.py) 经 SSH 导出笔记，按内容变化同步 active 索引；timer 定期运行，MCP 写入后也可异步触发。 |

现有 extract、finalize、batch 各有截断。定稿生成的 `OPEN QUESTIONS` 到 batch 就被跳过，batch 提示词还明确丢弃一次性排障。`timeline` 依 active 笔记的 `updated` 查相邻条目，无法还原会话中发生的失败和转折。

## 目标链路

`hook 白名单采集 → 脱敏原始记录落盘 → 独立后台整理 → Obsidian / Markdown`

- Hook 只做有界的本地采集和落盘，网络、模型、重试放进后台。原始记录保存用户可见的关键工作过程，允许分段处理长会话。保留排障中段、已排除假设和未决项；过滤私密块、系统提示、模型私有推理和工具噪声。后台按会话和来源位置去重，失败后可重跑。
- 首份笔记按工作发生顺序写目标、关键尝试、取舍、验证结果和未决问题，引用可定位的会话片段或代码证据。已发生、推测和待验证各写清楚。先试读项目中的几个构建章节，再决定项目入口和现行知识如何链接。

## 保留、改造与退出

- **保留** Obsidian 原文、现有草稿和索引数据、采集与定稿接口、配置和鉴权。原子笔记、显式 MCP 查询/写入和 Dashboard 继续兼容已有部署。保留对旧 transcript 中三个 `<hinddian_…>` 注入块的过滤，避免迁移时把旧内容写进笔记。
- **本切片删除** 启动时的记忆规则、项目/笔记标题、过往结语和设置提示；移除 `UserPromptSubmit` 注册、逐条 recall 脚本及自动触发的 `memory` skill。项目归属继续由服务端按仓库、工作目录和 Jev 等既有规则判断。`SessionStart` 只负责调度后台定稿。
- **后续改造** 把 collector 的完整白名单记录与模型输入分开落盘，给人读章节独立的后台产出，保留现有 batch 供兼容。确认显式调用方后，再退出 Agent 的 `recall`、`get_note` / `list_notes`、`routing_*`、`timeline` 和旧 Jev `should_recall` 契约；Dashboard 查询独立验收。Hindsight 同步留到调用方迁移完成后再决定用途。

升级前已注入的上下文仍在旧会话中。旧客户端仍会使用自己的旧 hook，需逐台更新后在新会话验收。新客户端可先连现有 API；已有缓冲和召回旁文件走原有清理周期。

## 按需指导

参考 pstack 的 `/how` 和 `/why`（本地研究资料 `01-PRIMARY-FULLTEXT.md` 的 PT2）。先试一段可粘贴的提示，等使用方式清楚再做 skill。用户可显式请求，Agent 也可在排障出现转折或需要解释关键取舍时调用。把回答的几句话放进正常进展或结语即可。

> 说清当前机制或复现步骤（how）、当时的依据和取舍（why）、已经做了什么及如何验证（do）。如果仍有未决问题，单独列出。依据不足时标明未知。

## 阶段、验收与回退

| 阶段 | 验收 | 回退 |
| --- | --- | --- |
| 1. 关闭自动历史注入（本次） | 用带旧笔记与缓冲的样例执行真实 hook，检查启动输出为空、无路由/笔记/recall 请求，同时旧会话能后台定稿、新回合能继续落盘。优先做这一刀，直接落实现阶段的共识，并避开改变草稿格式和已有 vault 数据的风险。 | Claude Code / Codex 更新插件后新开会话；Magpie 同步新 skill 后在每台机器重跑安装器，替换内嵌脚本；手工注册过的旧召回 hook 随升级移除。仍可用上一版插件和旧 Magpie hook 配置回到原行为。 |
| 2. 用一个排障会话试产人读笔记 | 长样例须保留中段失败、改路依据及 `OPEN QUESTIONS`，从笔记能定位原文。用短任务对照，检查采集延迟和后台失败重试。 | 试写独立目录，关闭整理任务即可回到旧 batch；保留原始记录和样例。 |
| 3. 试读、退出旧记忆接口 | Wanwan 能从少量样例复述目标、取舍和未决项；验证 Obsidian 搜索、Dashboard 和旧客户端迁移。 | 按接口逐项回退，保留旧服务配置和索引备份至验证结束。 |

## 待用户决定

- 默认入口按项目构建章节还是按专题解释。建议先用章节试读，再看是否需要专题页。
- `do` 暂指已执行及验证结果，待办进未决区。是否把未决项同步成独立待办另议。
- 脱敏原始记录的保留期、是否跨机器同步，以及旧 Hindsight 索引是否保留给 Dashboard。
