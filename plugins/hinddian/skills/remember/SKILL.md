---
name: remember
description: Save something to hinddian long-term memory right now. Trigger: /hinddian:remember <what to remember>
---

# hinddian remember

1. Classify what the user wants kept:
   - **tip** — cross-project agent/tool usage tip
   - **preference** — the user's standing preference or constraint
   - **lesson** — a pitfall and how to avoid it (needs a project)
   - **decision** — a lasting choice (A over B, with reasons; needs a project)
2. Draft `title` (short), `scene`, `practice`, `reason` from the user's words only. No secrets.
3. Write it (**never** `push_draft` — that is hooks-only session distill, not remember/correct):
   - tip / preference / lesson → `upsert_note` with `action: "add"` and `auto_verdict: true`
     (Jev merges into an existing note instead of duplicating it). If it answers
     `similar_exists`, look at `candidates`: same topic → `upsert_note` with `action: "update"` and
     that `id`; genuinely new → repeat the add with `force_new: true`.
   - decision → `suggest_correction`. Tell the user it waits for their approval in the dashboard
     「Agent 修正」.
4. Report what was saved (or queued) and its id in one line.
