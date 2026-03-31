---
name: recall
description: Search or list knowledge stored in Larvling's memory
argument-hint: "[search term]"
---

**Schema:**
- `topics (id INTEGER PK AUTO, title TEXT NOT NULL, domain TEXT NOT NULL, tags TEXT NOT NULL, created TEXT, updated TEXT)`
- `statements (id INTEGER PK AUTO, topic_id INTEGER FK→topics(id), claim TEXT NOT NULL, created TEXT, updated TEXT)`

Search for relevant knowledge by keyword, topic, or any available context. Use JOINs to show topic context with statements. Present results readably.

Run SQL via:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/query.py" "<SQL>"
```
