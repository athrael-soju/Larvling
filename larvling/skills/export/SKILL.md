---
name: export
description: Export a session conversation to markdown
argument-hint: "[session-id or --list or --all]"
---

**Schema:** `sessions (id TEXT PK, started_at TEXT, ended_at TEXT, duration_min REAL, title TEXT, agent_summary TEXT, exchange_count INT, summary_at TEXT, summary_msg_count INT, tags TEXT)`

Run via:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/export.py" <session_id>           # prints to stdout
python "${CLAUDE_PLUGIN_ROOT}/scripts/export.py" <session_id> <outfile> # writes to file
python "${CLAUDE_PLUGIN_ROOT}/scripts/export.py" --list
python "${CLAUDE_PLUGIN_ROOT}/scripts/export.py" --all [<outdir>]       # default: .claude/exports/
```
