---
name: remember
description: Store a fact that Larvling will remember across sessions
argument-hint: "[fact to remember]"
---

**Schema:** `facts (id INTEGER PK AUTO, claim TEXT NOT NULL, domain TEXT NOT NULL, tags TEXT NOT NULL, created TEXT NOT NULL DEFAULT date('now'), updated TEXT)`

Store the given fact, or identify what's worth persisting from available context.

Run SQL via:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/query.py" "<SQL>"
```

Use AskUserQuestion to confirm the claim, domain, and tags before inserting. After storing, confirm what was saved.
