---
name: search
description: Search across all Larvling session content
arguments:
  - name: query
    description: "Text to search for across all sessions"
    required: true
---

Search across all Larvling session conversations for matching content.

## Instructions

Run the search script with the user's query:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/search.py" "QUERY"
```

Present the grouped results showing:
- Session ID and title
- Number of matches per session
- Context snippets around each match

If there are many results, the user can refine with `--limit`:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/search.py" "QUERY" --limit 10
```

For wider context around matches:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/search.py" "QUERY" --context 150
```

For structured output:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/search.py" "QUERY" --json
```
