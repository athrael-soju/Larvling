---
name: query
description: Run SQL against larvling.db (search, insert, update, delete)
arguments:
  - name: sql
    description: "SQL query to execute"
    required: true
---

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/query.py" "$ARGUMENTS"
```
