---
name: query
description: "Query, insert, update, or inspect tables in the larvling SQLite database (larvling.db). Use when the user asks to search sessions, messages, topics, statements, tasks, or updates, run reports, or interact with the larvling database."
argument-hint: "[SQL query]"
disable-model-invocation: true
---

**Schema:**
- `sessions (id TEXT PK, started_at TEXT, ended_at TEXT, duration_min REAL, title TEXT, agent_summary TEXT, exchange_count INT, summary_at TEXT, summary_msg_count INT, tags TEXT, summary_offered INT DEFAULT 0)`
- `messages (id INT PK AUTO, session_id TEXT FK, timestamp TEXT, role TEXT, content TEXT, metadata TEXT)`
- `topics (id INTEGER PK AUTO, title TEXT NOT NULL, domain TEXT NOT NULL, tags TEXT NOT NULL, created TEXT, updated TEXT)`
- `statements (id INTEGER PK AUTO, topic_id INTEGER FK→topics(id), claim TEXT NOT NULL, created TEXT, updated TEXT)`
- `tasks (id INTEGER PK AUTO, title TEXT NOT NULL, domain TEXT NOT NULL, status TEXT DEFAULT 'open', priority TEXT DEFAULT 'medium', horizon TEXT DEFAULT 'later', metadata TEXT, created TEXT, updated TEXT)`
- `updates (id INTEGER PK AUTO, task_id INTEGER FK→tasks(id), content TEXT NOT NULL, timestamp TEXT)`

**JSON metadata columns** (query with `json_extract(metadata, '$.field')`):
- `tasks.metadata` — optional; `{"source_session_id": "<sid>"}` from `add_task` when a session id is known, else NULL
- `messages.metadata` — user: `{"cwd", "permission_mode", "usage": {...}}`; assistant: `{"tool_calls": {<tool>: <count>}, "usage": {...}}`; system: analysis telemetry

Execute the SQL directly. Append `--json` for JSON output.

```
$PY "${CLAUDE_PLUGIN_ROOT}/scripts/query.py" "$ARGUMENTS"
```
