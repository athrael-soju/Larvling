---
name: stats
description: View aggregate statistics for Larvling sessions
---

Display aggregate statistics about your Larvling session history.

## Instructions

Run the stats script:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/stats.py"
```

Present the results to the user in a readable format. The output includes:
- Session/message counts and averages
- Top tools used across all sessions
- 14-day activity chart

If the user wants raw data, run with `--json`:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/stats.py" --json
```
