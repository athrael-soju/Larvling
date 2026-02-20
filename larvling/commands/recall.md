---
name: recall
description: Search or list facts stored in Larvling's memory
arguments:
  - name: search
    description: "Keyword or topic to search for"
    required: false
---

Search or list facts using `/query`.

If a search term is provided:
```
/query "SELECT id, claim, domain, tags FROM facts WHERE claim LIKE '%<search>%' OR tags LIKE '%<search>%' ORDER BY established DESC"
```

If no search term, list all facts:
```
/query "SELECT id, claim, domain, tags FROM facts ORDER BY established DESC"
```

Present results readably to the user.
