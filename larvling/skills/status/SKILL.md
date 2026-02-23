---
name: status
description: Show a quick overview of Larvling's state
---

**Schema:**
- `sessions (id TEXT PK, started_at TEXT, ended_at TEXT, duration_min REAL, title TEXT, agent_summary TEXT, exchange_count INT, summary_at TEXT, summary_msg_count INT, topics TEXT, quality_signals TEXT)`
- `messages (id INT PK AUTO, session_id TEXT FK, timestamp TEXT, role TEXT, content TEXT, metadata TEXT)`
- `facts (id INTEGER PK AUTO, claim TEXT NOT NULL, domain TEXT NOT NULL, tags TEXT NOT NULL, created TEXT NOT NULL DEFAULT date('now'), updated TEXT)`

Gather and present a brief overview: session count, message count, fact count, DB file size, and plugin version (from `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json`).

Run SQL via:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/query.py" "<SQL>"
```
