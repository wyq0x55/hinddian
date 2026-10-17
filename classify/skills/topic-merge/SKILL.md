---
name: topic-merge
description: 把一份「待入库」会话提炼草稿归类并合并进 Obsidian 原子笔记（技巧/ 或 项目/<名>/决策|经验/），默认 ignore，输出严格 JSON（create|update|supersede|ignore）。处理 hinddian 待入库条目时使用。
---

# topic-merge · 待入库 → 原子笔记

## 判断顺序

1. **先问：这条内容半年后对另一个 agent 还有用吗？** 没用 → `ignore`。大多数草稿都应 ignore。
2. **再问：已有原子笔记里是不是已经有同义条目？** 用 MCP `recall` / `list_notes` 查。有 → `update`（合并）或 `ignore`（完全重复）。拿不准就 recall。
3. 剩下的才选目标：
   - 决策 → `项目/<名>/决策/<标题>.md`，id `proj/<名>/decision/<english-slug>`
   - 经验 / 避坑 → `项目/<名>/经验/<标题>.md`，id `proj/<名>/lesson/<english-slug>`
   - 通用 agent 技巧 → `技巧/<标题>.md`，id `tip/<english-slug>`
   - 现状 → 只改 `项目/<名>/README.md` 的「当前状态」（`action: merge_state`）；旧会话进度不要写。
   - frontmatter 的 `project` 常不准，按正文判断真实项目。
4. 一份草稿最多保留 **1 条项目结论 + 1 条通用技巧**，其它丢掉。
5. confidence 校准：0.8+ 只给「明确决策或可复现的坑 + 没记过/需更新 + 以后一定会再用」。项目类 <0.8、技巧类 <0.75 会被 runner 丢弃。

## 四态

| action | 含义 |
|--------|------|
| `create` | 新建原子笔记（slug 英文描述性） |
| `update` | 合并进已有 `id`（给出合并后完整场景/做法/理由） |
| `supersede` | 新建并取代旧 `id`（旧笔记标 superseded，链到新 id） |
| `ignore` | 什么都不做 |

## patch 写法

- `create` / `supersede`：`patch_markdown` 为完整正文（含 `# 标题` 与 `## 场景` / `## 做法` / `## 理由`）；frontmatter 由 runner 根据 JSON 字段生成。
- `update`：`target_id` 必填；`patch_markdown` 为合并后完整三节。
- `ignore`：`patch_markdown` 空串，`reason` 写原因。

## 示例

**例 1 · ignore（过程流水）**
→ `{"summary":"缺陷修复的启动过程","operations":[{"action":"ignore","target_id":"","target_path":"","type":"","project":"","slug":"","title":"","section":"","patch_markdown":"","supersedes":[],"reason":"纯过程进度，无可复用结论","confidence":0.9}]}`

**例 2 · create（通用技巧）**
→ tip，action create，target_path `技巧/子 Agent 委派省 token.md`，id 由 runner 写成 `tip/subagent-fork-context-false`。

**例 3 · update（已有决策需补充）**
→ action update，target_id 填已有 `proj/ut-agent/decision/...`。

**例 4 · supersede（新结论取代旧）**
→ action supersede，supersedes 填旧 id 列表。

## 输出（只输出这一个 JSON，不要其它文字，不要代码围栏）

{"summary":"一句话","operations":[{"action":"create|update|supersede|ignore","target_id":"已有id或空","target_path":"相对vault路径或空","type":"decision|lesson|tip|","project":"项目名或空","slug":"english-slug","title":"中文短标题","section":"","patch_markdown":"","supersedes":[],"reason":"…","confidence":0.0}]}

- `operations` 0–2 条；全无价值就给一条 `ignore`。
- 低置信度条目会被 runner 丢弃，不必勉强凑。
