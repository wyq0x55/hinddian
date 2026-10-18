---
name: memory
description: How to use hinddian-memory MCP (recall, gated upsert_note, suggest_correction, routing). Prefer MCP over inventing facts.
---

# hinddian memory usage

- **Read**: `routing_global` / `routing_project` at session start when relevant; `recall` for questions about past decisions.
- **Write (hooks first)**: Stop / turn buffer → session draft → distill. Prefer hooks over chat-time writes.
- **Gated upsert** (explicit corrections only):
  - `tip` / `preference` / `lesson`: may call `upsert_note` with `update` / `supersede` / `add`; `auto_verdict` OK.
  - Anything that adds, changes, supersedes or retires a `decision`: the server queues it for the user's dashboard approval whatever flags you send. Prefer `suggest_correction`; pass `user_confirmed` / `face_correction` only as context for the reviewer.
  - Never hard-delete. Use `supersede` or `obsolete` only.
- Never call raw Hindsight `retain`; only hinddian-memory tools. Obsidian is SoT; sync follows notes.
- Drafts are session-scoped; new projects need dashboard approve after ~20 session drafts.
