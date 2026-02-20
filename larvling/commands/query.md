---
name: query
description: Run arbitrary SQL against larvling.db
arguments:
  - name: sql
    description: "SQL query to execute"
    required: true
---
Run: python "${CLAUDE_PLUGIN_ROOT}/scripts/query.py" $ARGUMENTS
Report the results to the user.
