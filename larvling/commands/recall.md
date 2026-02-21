---
name: recall
description: Search or list facts stored in Larvling's memory
arguments:
  - name: search
    description: "Keyword or topic to search for"
    required: false
---

**Schema:** `facts (id TEXT PK, claim TEXT NOT NULL, domain TEXT, tags TEXT, confidence TEXT DEFAULT 'observed', source TEXT, established TEXT NOT NULL DEFAULT date('now'), confirmed TEXT, expires TEXT, notes TEXT)`

**Searchable columns:** `claim`, `domain`, `tags`, `notes`

Search for relevant facts by keyword, topic, or any available context. Present results readably.

**Example SQL:**
```sql
-- List all facts
SELECT id, claim, domain, tags FROM facts ORDER BY established DESC;

-- Keyword search across text columns
SELECT id, claim, domain, tags, notes FROM facts
WHERE claim LIKE '%keyword%' OR tags LIKE '%keyword%'
   OR domain LIKE '%keyword%' OR notes LIKE '%keyword%';

-- Filter by domain
SELECT id, claim, tags FROM facts WHERE domain = 'technical';
```

Run SQL via:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/query.py" "<SQL>"
```
