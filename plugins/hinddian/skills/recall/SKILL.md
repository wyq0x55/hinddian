---
name: recall
description: Search hinddian long-term memory for a question. Trigger: /hinddian:recall <question>
---

# hinddian recall

1. Call `recall` on hinddian-memory with the user's question as `query` (add `project` if the
   user names one or the session's project is known). Load the tool with ToolSearch "hinddian"
   if it is deferred.
2. Show the hits as a short list: title, one line of what it says, id.
3. If the user wants detail on one, call `get_note(id)` and summarise it.
4. No hits → say so plainly; don't invent past decisions.
