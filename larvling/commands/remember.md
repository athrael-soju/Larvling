---
name: remember
description: Store a fact that Larvling will remember across sessions
arguments:
  - name: fact
    description: "The fact, preference, or decision to remember"
    required: false
---

**Schema:** `facts (id TEXT PK, claim TEXT NOT NULL, domain TEXT, tags TEXT, confidence TEXT DEFAULT 'observed', source TEXT, established TEXT DEFAULT date('now'), confirmed TEXT, expires TEXT, notes TEXT)`

Store the given fact, or identify what's worth persisting from available context. Use `M-NNN` format for IDs (auto-increment from the highest existing).

Run SQL via:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/query.py" "<SQL>"
```

Confirm what was stored.
