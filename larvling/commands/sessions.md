---
name: sessions
description: Browse and search past sessions
arguments:
  - name: search
    description: "Date, keyword, or topic to filter by"
    required: false
---
Use /query to search across session titles, summaries, and message content. Craft SQL based on the user's search term.

Example: python "${CLAUDE_PLUGIN_ROOT}/scripts/query.py" "SELECT substr(id,1,8) as id, started_at, title, agent_summary FROM sessions WHERE title LIKE '%keyword%' OR agent_summary LIKE '%keyword%' ORDER BY started_at DESC LIMIT 10"

Present results readably.
