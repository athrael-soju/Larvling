---
name: summarize
description: Generate a session summary for a Larvling session
arguments:
  - name: session
    description: "Session ID (short or full). Use 'list' to see available sessions, or 'all' to summarize all unsummarized sessions."
    required: false
---

List sessions with summary status:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/summarize.py" --list
```

Check for existing summary:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/summarize.py" <session_id> --get
```

Fetch conversation pairs:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/summarize.py" <session_id> --pairs
```

## Summarization approach

Do NOT summarize everything at once. Use incremental passes:

1. **Pair summaries**: For each user/agent pair, write 1-2 sentences capturing what was discussed and accomplished.
2. **Group summaries**: Combine pairs into groups of 3-5 and summarize each group into a paragraph.
3. **Final summary**: Combine group summaries into one cohesive session summary covering what was accomplished, key decisions, and any unresolved items.

For small sessions (5 or fewer pairs), skip straight to the final summary.

Prepend an exchange count header: `[N exchanges]`

Store the summary:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/summarize.py" <session_id> --store "SUMMARY"
```

For `all`: process each unsummarized session (marked `[not summarized]`) using the steps above.

After storing, regenerate the dashboard:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/dashboard.py"
```

**Important:** After storing a summary, always display it to the user immediately. Don't wait to be asked.
