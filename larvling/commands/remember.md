---
name: remember
description: Store a fact that Larvling will remember across sessions
arguments:
  - name: fact
    description: "The fact, preference, or decision to remember"
    required: false
---
Run: python "${CLAUDE_PLUGIN_ROOT}/scripts/facts.py" remember $ARGUMENTS
Report the results to the user.
