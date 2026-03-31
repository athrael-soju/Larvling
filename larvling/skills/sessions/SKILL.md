---
name: sessions
description: Browse and search past sessions
argument-hint: "[date, keyword, or topic]"
---

**Schema:**
- `sessions (id TEXT PK, started_at TEXT, ended_at TEXT, duration_min REAL, title TEXT, agent_summary TEXT, exchange_count INT, summary_at TEXT, summary_msg_count INT, tags TEXT)`
- `messages (id INT PK AUTO, session_id TEXT FK, timestamp TEXT, role TEXT, content TEXT, metadata TEXT)`

Search sessions by date, keyword, topic, or any available context. Search across session titles, summaries, tags, and message content as needed. Present results readably.

Run SQL via:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/query.py" "<SQL>"
```
