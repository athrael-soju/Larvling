---
name: recall
description: Search or list facts stored in Larvling's memory
arguments:
  - name: search
    description: "Keyword or topic to search for"
    required: false
---

**Schema:** `facts (id INTEGER PK AUTO, claim TEXT NOT NULL, domain TEXT NOT NULL, tags TEXT NOT NULL, created TEXT NOT NULL DEFAULT date('now'), updated TEXT)`

Search for relevant facts by keyword, topic, or any available context. Present results readably.

Run SQL via:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/query.py" "<SQL>"
```
