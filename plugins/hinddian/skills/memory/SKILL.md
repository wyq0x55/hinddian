---
name: memory
description: How to use hinddian-memory MCP (recall, gated upsert_note, suggest_correction, routing). Prefer MCP over inventing facts.
---

# hinddian memory usage

- **Read**: `routing_global` / `routing_project` at session start when relevant; `recall` for questions about past decisions.
- **Write (hooks first)**: Stop / turn buffer → session draft → distill. Prefer hooks over chat-time writes.
- **Gated upsert** (explicit corrections only):
  - `tip` / `preference` (or `face_correction=true` when the user just corrected a wrong memory): may call `upsert_note` with `update` / `supersede` / `add`; `auto_verdict` OK.
  - `decision` / architecture conclusions: **do not silent-write**. Either get a one-line user confirm then `upsert_note` with `user_confirmed=true`, or call `suggest_correction` (dashboard queue).
  - Never hard-delete. Use `supersede` or `obsolete` only.
- Never call raw Hindsight `retain`; only hinddian-memory tools. Obsidian is SoT; sync follows notes.
- Drafts are session-scoped; new projects need dashboard approve after ~20 session drafts.
