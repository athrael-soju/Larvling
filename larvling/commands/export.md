---
name: export
description: Export a session conversation to markdown
arguments:
  - name: session
    description: "Session ID (short or full). Pass --list to see sessions, or --all to export everything."
    required: false
---
Run: python "${CLAUDE_PLUGIN_ROOT}/scripts/export.py" $ARGUMENTS
Report the results to the user.
