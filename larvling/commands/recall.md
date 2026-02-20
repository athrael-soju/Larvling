---
name: recall
description: Search or list facts stored in Larvling's memory
arguments:
  - name: search
    description: "Keyword or topic to search for"
    required: false
---
Run: python "${CLAUDE_PLUGIN_ROOT}/scripts/facts.py" recall $ARGUMENTS
Report the results to the user.
