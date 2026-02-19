---
name: forget
description: Remove a stored fact from Larvling's memory
arguments:
  - name: fact
    description: "Fact ID (e.g. M-001) or keyword to search for"
    required: false
---

**Schema:** `facts (id TEXT PK, claim TEXT NOT NULL, domain TEXT, tags TEXT, confidence TEXT DEFAULT 'observed', source TEXT, established TEXT DEFAULT date('now'), confirmed TEXT, expires TEXT, notes TEXT)`

Find the fact to remove - by ID, keyword, or by asking the user to clarify. Show matching fact(s) and use AskUserQuestion to confirm before deleting.

Run SQL via:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/query.py" "<SQL>"
```
