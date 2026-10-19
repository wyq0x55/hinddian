---
name: memory
description: |
  How to use hinddian long-term memory (hinddian-memory MCP). Use when the task touches past
  decisions, project conventions, known pitfalls or user preferences; when a <hinddian_recall>
  block is attached to a message; or when the user says "remember this", "记住", "上次怎么定的",
  "之前的决定", "纠正一下记忆".
---

# hinddian memory

Obsidian notes are the source of truth; the agent reaches them only through the
`hinddian-memory` MCP tools. Never call Hindsight `retain` directly.

## Reading

```
User message arrives
│
├── A <hinddian_recall> block is attached?
│   └── Use what is relevant, ignore the rest. Don't recite it to the user.
│       Need the full note → get_note(id)
│
├── Task depends on earlier decisions / conventions / pitfalls of a project, and nothing was attached?
│   └── recall(query, project)   — short, specific query
│       Need the project's state and decision list → routing_project(project)
│
└── Otherwise → don't call memory tools
```

Tools may be deferred: if a hinddian tool "doesn't exist", load it with ToolSearch
("hinddian") first — never conclude there is no memory.

## Writing

Sessions are turned into drafts automatically (Stop hook → nightly batch); normal work needs
no writes. Write only when the user explicitly asks to remember or correct something:

| Kind | Tool |
|------|------|
| tip / preference / lesson | `upsert_note` (add or update; `auto_verdict: true` lets Jev pick add/update/supersede) |
| anything that creates, changes, supersedes or retires a **decision** | `suggest_correction` — the user approves it in the dashboard; no flag bypasses this |

Never hard-delete (use `supersede` / `obsolete`). Never write secrets.
