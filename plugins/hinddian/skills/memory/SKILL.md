---
name: memory
description: How to use hinddian-memory MCP (recall, upsert_note, routing). Prefer MCP over inventing facts.
---

# hinddian memory usage

- **Read**: `routing_global` / `routing_project` at session start when relevant; `recall` for questions about past decisions.
- **Write**: prefer hooks (Stop / turn buffer → draft → distill). Explicit `upsert_note` only for high-confidence facts the user confirmed.
- Never call raw Hindsight `retain`; only hinddian-memory tools.
- Drafts are session-scoped; new projects need dashboard approve after ~20 session drafts.
