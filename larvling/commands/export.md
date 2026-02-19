---
name: export
description: Export a session conversation to markdown
arguments:
  - name: session
    description: "Session ID (short or full), 'list' to see sessions, or 'all' to export everything"
    required: false
---

**Schema:** `sessions (id TEXT PK, started_at TEXT, ended_at TEXT, duration_min REAL, title TEXT, agent_summary TEXT, exchange_count INT, summary_at TEXT, summary_msg_count INT)`

Run via:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/export.py" <args>
```

Exports to `.claude/exports/`. Use `--list` to browse sessions, `--all <outdir>` for batch export.
