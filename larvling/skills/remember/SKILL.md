---
name: remember
description: Store knowledge that Larvling will remember across sessions
argument-hint: "[knowledge to remember]"
---

**Schema:**
- `topics (id INTEGER PK AUTO, title TEXT NOT NULL, domain TEXT NOT NULL, tags TEXT NOT NULL, created TEXT, updated TEXT)`
- `statements (id INTEGER PK AUTO, topic_id INTEGER FK→topics(id), claim TEXT NOT NULL, created TEXT, updated TEXT)`

Store the given knowledge, or identify what's worth persisting from available context. Find or create a topic, then add a statement under it.

Run SQL via:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/query.py" "<SQL>"
```

Use AskUserQuestion to confirm the claim, topic, domain, and tags before inserting. After storing, confirm what was saved.
