---
name: summarize
description: Generate or view a session summary
arguments:
  - name: session
    description: "Session ID (short or full). Pass 'list' to see sessions, or omit to summarize the current session."
    required: false
---
If $ARGUMENTS is "list" or "--list":
  Run: python "${CLAUDE_PLUGIN_ROOT}/scripts/summarize.py" --list
  Report the output to the user.

Otherwise:
  1. Fetch message pairs:
     python "${CLAUDE_PLUGIN_ROOT}/scripts/summarize.py" $ARGUMENTS --pairs
     This prints the conversation pairs as JSON.

  2. Check for existing summary:
     python "${CLAUDE_PLUGIN_ROOT}/scripts/summarize.py" $ARGUMENTS --get

  3. Generate a 1-3 sentence summary from the pairs. Focus on what was discussed and accomplished.

  4. Store the summary:
     python "${CLAUDE_PLUGIN_ROOT}/scripts/summarize.py" <session_id> --store "<summary>"

  5. Report the summary to the user.
