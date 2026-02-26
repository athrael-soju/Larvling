---
name: summarize
description: Generate or view a session summary
argument-hint: "[session-id or --list or all]"
---

**Schema:**
- `sessions (id TEXT PK, started_at TEXT, ended_at TEXT, duration_min REAL, title TEXT, agent_summary TEXT, exchange_count INT, summary_at TEXT, summary_msg_count INT, tags TEXT)`
- `messages (id INT PK AUTO, session_id TEXT FK, timestamp TEXT, role TEXT, content TEXT, metadata TEXT)`

Run SQL via:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/query.py" "<SQL>"
```

Delegate to the `summary-manager` agent. Pass along the session ID if provided, or the current session if not.
