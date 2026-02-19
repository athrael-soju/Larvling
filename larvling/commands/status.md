---
name: status
description: Show a quick overview of Larvling's state
arguments: []
---

**Tables:** `sessions`, `messages`, `facts`

Gather and present a brief overview: session count, message count, fact count, DB file size, and plugin version (from `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json`).

Run SQL via:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/query.py" "<SQL>"
```
