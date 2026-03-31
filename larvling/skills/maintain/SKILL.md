---
name: maintain
description: Audit and consolidate Larvling's knowledge base
---

**Schema:**
- `topics (id INTEGER PK AUTO, title TEXT NOT NULL, domain TEXT NOT NULL, tags TEXT NOT NULL, created TEXT, updated TEXT)`
- `statements (id INTEGER PK AUTO, topic_id INTEGER FK→topics(id), claim TEXT NOT NULL, created TEXT, updated TEXT)`

Run SQL via:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/query.py" "<SQL>"
```

Delegate to the `knowledge-maintenance` agent. It will audit all topics and statements, identify issues (duplicates, stale entries, misclassifications, contradictions), propose changes, and apply only what the user approves.
