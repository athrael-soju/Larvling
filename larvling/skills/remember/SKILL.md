---
name: remember
description: Store knowledge that Larvling will remember across sessions
argument-hint: "[knowledge to remember]"
---

**Schema:**
- `topics (id INTEGER PK AUTO, title TEXT NOT NULL, domain TEXT NOT NULL, tags TEXT NOT NULL, created TEXT, updated TEXT)`
- `statements (id INTEGER PK AUTO, topic_id INTEGER FK→topics(id), claim TEXT NOT NULL, created TEXT, updated TEXT)`

Run SQL via:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/query.py" "<SQL>"
```

Delegate to the `knowledge-manager` agent. Pass along the knowledge to store, or the conversation context if nothing specific was given.
