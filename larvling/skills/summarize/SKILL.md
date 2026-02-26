---
name: summarize
description: Generate or view a session summary
argument-hint: "[session-id or --list or all]"
---

**Schema:** `sessions (id TEXT PK, started_at TEXT, ended_at TEXT, duration_min REAL, title TEXT, agent_summary TEXT, exchange_count INT, summary_at TEXT, summary_msg_count INT, tags TEXT)`

Run via:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/summarize.py" --list
python "${CLAUDE_PLUGIN_ROOT}/scripts/summarize.py" <session_id> --pairs
python "${CLAUDE_PLUGIN_ROOT}/scripts/summarize.py" <session_id> --get
python "${CLAUDE_PLUGIN_ROOT}/scripts/summarize.py" <session_id> --store "SUMMARY"
```

## Approach

Check for an existing summary first (`--get`). If one exists, display it and use AskUserQuestion to confirm before regenerating.

If no summary exists, or the user confirms regeneration: read the conversation pairs (`--pairs`), write a summary that covers accomplishments, key decisions, and unresolved items. Scale detail to conversation length. Store with `--store` and display the result.
