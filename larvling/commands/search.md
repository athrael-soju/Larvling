---
name: search
description: Search across all Larvling session content
arguments:
  - name: query
    description: "Text to search for across all sessions"
    required: true
---

Run the search script with the user's query:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/search.py" "QUERY"
```
