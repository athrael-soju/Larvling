---
name: forget
description: Remove a stored fact from Larvling's memory
arguments:
  - name: fact
    description: "Fact ID or keyword to search for"
    required: false
---

**Schema:** `facts (id INTEGER PK AUTO, claim TEXT NOT NULL, domain TEXT NOT NULL, tags TEXT NOT NULL, created TEXT NOT NULL DEFAULT date('now'), updated TEXT)`

Find the fact to remove — by ID, keyword, or by asking the user to clarify. Show matching fact(s) and use AskUserQuestion to confirm before deleting.

Run SQL via:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/query.py" "<SQL>"
```
