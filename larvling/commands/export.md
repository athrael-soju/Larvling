---
name: export
description: Export a Larvling session conversation to markdown
arguments:
  - name: session
    description: "Session ID (short or full) to export. Use 'list' to see available sessions."
    required: false
---

Export a Larvling conversation session to markdown format.

## Instructions

Run the export script from the Larvling plugin:

1. If the user passed `list` as the session argument, or no argument at all, run:
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/export.py" --list
   ```
   Show the results to the user so they can pick a session.

2. If the user provided a session ID, export directly to a file:
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/export.py" <session_id> .claude/exports/<session_id>.md
   ```
   Tell the user where the file was saved.
