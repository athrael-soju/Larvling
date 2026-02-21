---
name: summarize
description: Generate or view a session summary
arguments:
  - name: session
    description: "Session ID (short or full). Pass --list to see sessions, or use 'all' for batch."
    required: false
---

**Schema:** `sessions (id TEXT PK, started_at TEXT, ended_at TEXT, duration_min REAL, title TEXT, agent_summary TEXT, exchange_count INT, summary_at TEXT, summary_msg_count INT, topics TEXT, quality_signals TEXT)`

Run via:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/summarize.py" <args>
```

Available flags: `--list`, `--get`, `--pairs`, `--store "SUMMARY"`

## Approach

0. **Check for existing summary** — run `--get` first. If one exists, display it and use AskUserQuestion to confirm before regenerating.

Summarize incrementally, not all at once:

1. **Pair summaries** — 1-2 sentences per user/agent exchange
2. **Group summaries** — combine pairs into groups of 3-5, one paragraph each
3. **Final summary** — combine groups into one cohesive summary covering accomplishments, decisions, and unresolved items

For small sessions (5 or fewer pairs), skip to the final summary. Prepend `[N exchanges]`.

After storing, always display the summary immediately.
