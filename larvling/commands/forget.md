---
name: forget
description: Remove a stored fact from Larvling's memory
arguments:
  - name: fact
    description: "Fact ID (e.g. M-001) or keyword to search for"
    required: false
---

**Schema:** `facts (id TEXT PK, claim TEXT NOT NULL, domain TEXT, tags TEXT, confidence TEXT DEFAULT 'observed', source TEXT, established TEXT NOT NULL DEFAULT date('now'), confirmed TEXT, expires TEXT, notes TEXT)`

**Searchable columns:** `claim`, `domain`, `tags`, `notes`

Find the fact to remove - by ID, keyword, or by asking the user to clarify. Show matching fact(s) and use AskUserQuestion to confirm before deleting.

**Example SQL:**
```sql
-- Look up by ID
SELECT * FROM facts WHERE id = 'M-001';

-- Keyword search across text columns
SELECT id, claim, domain, tags FROM facts
WHERE claim LIKE '%keyword%' OR tags LIKE '%keyword%'
   OR domain LIKE '%keyword%' OR notes LIKE '%keyword%';

-- Delete a fact
DELETE FROM facts WHERE id = 'M-001';
```

Run SQL via:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/query.py" "<SQL>"
```
