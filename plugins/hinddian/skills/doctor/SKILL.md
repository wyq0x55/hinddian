---
name: doctor
description: Diagnose the hinddian plugin (config, server, auth, MCP tools). Trigger: /hinddian:doctor
---

# hinddian doctor

1. Call the `doctor` tool on hinddian-memory (ToolSearch "hinddian" first if it is deferred).
   It runs `setup.py --check` on this machine.
2. Show its output to the user verbatim.
3. For each `[fail]` line, relay its `→` fix. Configuration needs the user's token, so the user
   runs `setup.py --url … --token …` in their own terminal — never ask them to paste the token
   into chat.
