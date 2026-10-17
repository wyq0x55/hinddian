---
name: topic-merge
description: 把一份「待入库」会话提炼草稿归类并合并进 Obsidian 主题笔记（agent使用技巧 或 项目三件套），输出严格 JSON 合并方案。处理 hinddian 待入库条目时使用。
---

# topic-merge · 待入库 → 主题笔记

## 步骤

1. 通读「待入库草稿」。抽出**可复用的结论**，按两类分：
   - **agent 使用技巧**（跨项目通用）：怎么用 agent / 提示词 / MCP / skill / 模型 / 工具链更有效，常见坑与规避。
   - **项目知识**：属于某个具体项目的决策、经验、当前状态。草稿 frontmatter 的 `project` 常常不准（大量都标成「笔记系统」），要看正文判断真实项目。真实项目不在「已有项目」列表时，可以用新项目名（会生成待确认建议，人确认后才建目录）。
2. 对每个结论选目标文件：
   - 决策（定了什么、为什么）→ `项目/<名>/DECISIONS.md`（冲突时改写旧条，不留两套说法 → 用 `merge` 重写那条所在的节）
   - 经验 / 避坑 → `项目/<名>/LESSONS.md`（只追加 → `append`）
   - 现在为真的状态 → `项目/<名>/PROJECT_STATE.md`（覆盖式 → `merge` 某个 `##` 节）
   - 通用技巧 → `00-系统/agent使用技巧.md`（同类技巧已有一节时 `merge` 重写该节，否则 `append` 新节）
3. 查重：对照附上的目标笔记全文；拿不准就调 `mcp__hindsight__recall`（query 用关键实体）。已记过 → `ignore`。
4. 写 patch：
   - `append`：`patch_markdown` 是要追加到文末的一个完整小节，以 `## ` 开头。DECISIONS 用 `## D-xxx · 标题（YYYY-MM-DD）`，LESSONS 用 `## L-xxx · 标题`（编号接着现有最大号往后排），技巧用 `## 标题`。
   - `merge`：`section` 填目标笔记里**已存在**的 `##` 标题原文（不带 `## `）；`patch_markdown` 是该节**完整替换后的内容**（含 `## ` 标题行），保留旧节仍然成立的内容。
   - `ignore`：`patch_markdown` 留空，`reason` 写为什么。
5. confidence：0–1。只有你确信归类正确、内容可复用且无重复时才 ≥0.75。

## 输出（只输出这一个 JSON，不要其它文字，不要代码围栏）

{"summary":"一句话概括这份草稿","operations":[{"target_document_id":"topic/agent-usage-tips","target_path":"00-系统/agent使用技巧.md","action":"append","section":"","patch_markdown":"## ...\n- ...","reason":"...","confidence":0.8}]}

- `operations` 可以有 0–3 条；整份都没价值就给一条 `action":"ignore"`（target 填最相关的一个即可）。
- `target_document_id`：`topic/agent-usage-tips` 或 `topic/project/<项目名>/decisions|lessons|state`。
- 每条 `patch_markdown` ≤ 1500 字。不要写密钥。
