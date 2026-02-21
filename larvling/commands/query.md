---
name: query
description: Run arbitrary SQL against larvling.db
arguments:
  - name: sql
    description: "SQL query to execute"
    required: true
---

**Schema:**
- `sessions (id TEXT PK, started_at TEXT, ended_at TEXT, duration_min REAL, title TEXT, agent_summary TEXT, exchange_count INT, summary_at TEXT, summary_msg_count INT, topics TEXT, quality_signals TEXT)`
- `messages (id INT PK AUTO, session_id TEXT FK, timestamp TEXT, role TEXT, content TEXT, metadata TEXT)`
- `facts (id TEXT PK, claim TEXT NOT NULL, domain TEXT, tags TEXT, confidence TEXT DEFAULT 'observed', source TEXT, established TEXT NOT NULL DEFAULT date('now'), confirmed TEXT, expires TEXT, notes TEXT)`

Execute the SQL directly. Append `--json` for JSON output.

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/query.py" "$ARGUMENTS"
```
