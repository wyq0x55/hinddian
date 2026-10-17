---
name: topic-merge
description: 把一份「待入库」会话提炼草稿归类并合并进 Obsidian 主题笔记（agent使用技巧 或 项目三件套），默认 ignore，输出严格 JSON 合并方案。处理 hinddian 待入库条目时使用。
---

# topic-merge · 待入库 → 主题笔记

## 判断顺序

1. **先问：这条内容半年后对另一个 agent 还有用吗？** 没用 → `ignore`。大多数草稿都应 ignore。
2. **再问：目标笔记或「待确认队列」里是不是已经有同义条目？** 有 → `ignore`（reason 写「已记于 xxx」）。拿不准就 `mcp__hindsight__recall`。
3. 剩下的才选目标：
   - 决策 → `项目/<名>/DECISIONS.md`（`append`；与旧条冲突时 `merge` 重写那一节）
   - 经验 / 避坑 → `项目/<名>/LESSONS.md`（只 `append`）
   - 现状 → `项目/<名>/PROJECT_STATE.md`（`merge` 某个 `##` 节；旧会话的进度不要写）
   - 通用 agent 技巧 → `00-系统/agent使用技巧.md`（同类已有一节 → `merge` 该节；否则 `append`）
   - frontmatter 的 `project` 常不准（大量都标「笔记系统」），按正文判断真实项目；可以用新项目名（会成为待确认建议）。
4. 一份草稿最多保留 **1 条项目结论 + 1 条通用技巧**，其它丢掉。
5. confidence 校准：0.8+ 只给「明确决策或可复现的坑 + 没记过 + 以后一定会再用」。项目类 <0.8、技巧类 <0.75 会被 runner 丢弃。

## patch 写法

- `append`：一个完整小节，以 `## ` 开头。DECISIONS 写 `## D-xxx · 标题（YYYY-MM-DD）`，LESSONS 写 `## L-xxx · 标题`（编号随便写，runner 会按目标文件重新编号），技巧写 `## 标题`。正文 3–6 行。
- `merge`：`section` 填目标里已存在的 `##` 标题原文（不带 `## `）；`patch_markdown` 是该节完整替换后的内容（含标题行），保留旧内容中仍成立的部分。
- `ignore`：`patch_markdown` 空串，`reason` 写原因。

## 示例

**例 1 · ignore（过程流水）**
草稿：「已加载 tdd-workflow skill，正在定位 corpus.py，下一步写 RED 测试并提交 checkpoint。」
→ `{"summary":"缺陷修复的启动过程","operations":[{"target_document_id":"topic/project/ut-agent/state","target_path":"项目/ut-agent/PROJECT_STATE.md","action":"ignore","section":"","patch_markdown":"","reason":"纯过程进度，无可复用结论","confidence":0.9}]}`

**例 2 · ignore（一次性排障）**
草稿：「这台机器 ChatGPT 桌面端无法更新，删掉缓存目录后好了。」
→ ignore，reason「单机一次性故障，无推广价值」。

**例 3 · ignore（已记过）**
草稿：「Magpie Observability 只推开关之后的新回合，历史会话要导出再 POST。」目标笔记 `会话提炼说明` / 待确认队列里已有同义条目。
→ ignore，reason「已记于 待确认队列 / 会话提炼说明」。

**例 4 · 保留（通用技巧 → 自动写入）**
草稿：「派只读子 agent 时 fork_context=false + 单次长超时 wait，主会话不轮询，token 降一半。」agent使用技巧里没有。
→ `{"summary":"子 agent 委派省 token","operations":[{"target_document_id":"topic/agent-usage-tips","target_path":"00-系统/agent使用技巧.md","action":"append","section":"","patch_markdown":"## 子 Agent 委派省 token\n- **场景：** …\n- **做法：** …\n- **理由：** …","reason":"跨项目通用，未记过","confidence":0.85}]}`

**例 5 · 保留（项目决策 → 待确认）**
草稿：「WinAMS Golden 识别改为校验表头 target identity，遇歧义 fail-closed，不再按文件名猜。」ut-agent 的 DECISIONS 里没有。
→ append 到 `项目/ut-agent/DECISIONS.md`，confidence 0.8。

## 输出（只输出这一个 JSON，不要其它文字，不要代码围栏）

{"summary":"一句话","operations":[{"target_document_id":"…","target_path":"…","action":"append|merge|ignore","section":"","patch_markdown":"","reason":"…","confidence":0.0}]}

- `operations` 0–2 条；全无价值就给一条 `ignore`。
- 低置信度条目会被 runner 丢弃，不必勉强凑。
