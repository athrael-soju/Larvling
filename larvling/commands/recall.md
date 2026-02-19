---
name: recall
description: Search or list facts stored in Larvling's memory
arguments:
  - name: search
    description: "Keyword or topic to search for"
    required: false
---

**Schema:** `facts (id TEXT PK, claim TEXT NOT NULL, domain TEXT, tags TEXT, confidence TEXT DEFAULT 'observed', source TEXT, established TEXT NOT NULL DEFAULT date('now'), confirmed TEXT, expires TEXT, notes TEXT)`

Search for relevant facts by keyword, topic, or any available context. Present results readably.

Run SQL via:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/query.py" "<SQL>"
```
