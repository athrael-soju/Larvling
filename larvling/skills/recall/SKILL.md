---
name: recall
description: Search or list facts stored in Larvling's memory
argument-hint: "[search term]"
---

**Schema:** `facts (id INTEGER PK AUTO, claim TEXT NOT NULL, domain TEXT NOT NULL, tags TEXT NOT NULL, created TEXT NOT NULL DEFAULT date('now'), updated TEXT)`

Search for relevant facts by keyword, topic, or any available context. Present results readably.

Run SQL via:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/query.py" "<SQL>"
```
