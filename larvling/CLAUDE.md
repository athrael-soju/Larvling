# Larvling

> Your friendly memory companion. Every conversation is remembered.

Everything lives in `.claude/larvling.db` (SQLite, WAL mode). The dashboard at `.claude/dashboard.html` is generated on-demand via `/generate-dashboard`.

## First Run

When the SessionStart context contains "Larvling - First Run", this is the very first time Larvling has been installed. You MUST welcome the user before doing anything else. Keep it warm, brief, and conversational - something like a friendly companion introducing itself. Include:
- That Larvling is now installed and will quietly remember their sessions
- A mention of the dashboard at `.claude/dashboard.html` for browsing past conversations
- That everything is automatic - no setup or extra effort needed
- Mention the available skills naturally: `/remember` to store knowledge, `/recall` to search it, `/forget` to remove it, `/sessions` to browse past sessions, `/summarize` for session summaries, `/export` to save a conversation as markdown, `/status` for a quick overview, `/query` for direct SQL access, `/generate-dashboard` to build the visual dashboard
- Do NOT list technical details, hook names, or internal architecture. Keep the magic behind the curtain.

## Update Notice

When the SessionStart context contains "Larvling update available", mention it once to the user at the start of the conversation. Keep it brief - one sentence is enough. Don't repeat it later in the session.

## During a Session

Review the context Larvling injects at session start - it's your memory of what came before. Recording is automatic - just focus on the work.

### Schema Migration

- When the SessionStart context contains "Schema Migration Required", the database schema needs updating.
- Read the current and desired schemas provided, write and run the SQL to migrate (preserving all data), then bump the version in `larvling/db.py` with the provided command.
- A backup of the database has already been created.

### `/query` - Direct SQL Access

Use `/query` to run any SQL against larvling.db. Claude writes the SQL based on conversation context.

**Schema:**
- `sessions (id TEXT PK, started_at TEXT, ended_at TEXT, duration_min REAL, title TEXT, agent_summary TEXT, exchange_count INT, summary_at TEXT, summary_msg_count INT, tags TEXT, quality_signals TEXT)`
- `messages (id INT PK AUTO, session_id TEXT FK, timestamp TEXT, role TEXT, content TEXT, metadata TEXT)`
- `topics (id INTEGER PK AUTO, title TEXT NOT NULL, domain TEXT NOT NULL, tags TEXT NOT NULL, created TEXT, updated TEXT)`
- `statements (id INTEGER PK AUTO, topic_id INTEGER FK→topics(id), claim TEXT NOT NULL, created TEXT, updated TEXT)`
- `tasks (id INTEGER PK AUTO, title TEXT NOT NULL, domain TEXT NOT NULL, status TEXT DEFAULT 'open', priority TEXT DEFAULT 'medium', horizon TEXT DEFAULT 'later', metadata TEXT, created TEXT)`
- `updates (id INTEGER PK AUTO, task_id INTEGER FK→tasks(id), content TEXT NOT NULL, timestamp TEXT)`

**Examples:**

```
/query "SELECT t.id, t.title, s.claim FROM topics t JOIN statements s ON s.topic_id = t.id"
/query "SELECT t.id, t.title, s.claim FROM topics t JOIN statements s ON s.topic_id = t.id WHERE s.claim LIKE '%deploy%' OR t.tags LIKE '%ci%'"
/query "SELECT id, title, agent_summary FROM sessions WHERE agent_summary IS NOT NULL ORDER BY started_at DESC LIMIT 5"
/query "SELECT * FROM tasks WHERE status = 'open' ORDER BY priority"
/query "SELECT * FROM messages WHERE content LIKE '%auth%' LIMIT 10" --json
```

### Knowledge, Tasks & Unified Analysis

Larvling stores persistent knowledge in the `topics` + `statements` tables, and action items in the `tasks` + `updates` tables. Multiple mechanisms handle data extraction:

**UserPromptSubmit → Knowledge Context (read):** The `## Knowledge Context` directive prints on every exchange with the `query.py` path and topic/statement counts. Search for relevant knowledge and weave it into your response naturally.

**Stop → Unified extraction (write):** `extract.py` runs as a command hook after every response. It contains `call_model()` (Agent SDK integration) and uses `transcript.py` for parsing. A single Agent SDK call extracts multiple data types from the last exchange:
- **Knowledge** → `topics` + `statements` tables (hierarchical: topic groups related statements)
- **Sentiment** (focused/curious/frustrated/satisfied/neutral) → `messages.metadata` JSON on the last assistant message
- **Session tags** → `sessions.tags` column, comma-separated, dynamically consolidated each exchange (merges similar, drops irrelevant, adds new)
- **Tasks** → `tasks` table with native columns for status, priority, horizon

**Stop → Quality signals (no SDK call):** `hooks/stop.py` computes quality signals from the response text (error counts, retry patterns, tool call totals) and stores them in `sessions.quality_signals` as JSON. Pure Python, no latency cost.

**Token usage tracking:** Two hooks capture token usage:
- **Prompt** — `hooks/prompt.py` estimates user tokens (`~4 chars/token` heuristic), stored in `messages.metadata.usage` on user row
- **Response** — `hooks/stop.py` extracts API usage from transcript. Output tokens summed from `speed` entries (real API responses); falls back to `~4 chars/token` estimate for text-only turns (flagged with `output_tokens_estimated`). Stored in `messages.metadata.usage` on assistant row.
- **Analysis** — SDK call usage stored as `role='system'` message with usage in metadata.

**Log format** — JSONL (one JSON object per line) in `.claude/larvling.jsonl`:
```jsonl
{"ts":"2026-02-24T16:16:35","event":"prompt","sid":"6801adcc","n":1,"input_tokens_est":1}
{"ts":"...","event":"context","sid":"6801adcc","injected":["5 topics, 11 statements","stale summary hint"],"tokens_est":42}
{"ts":"...","event":"response","sid":"6801adcc","chars":20,"is_dup":false,"cache_read":27953,"input_new":9142,"output":5,"output_estimated":true}
{"ts":"...","event":"skill","sid":"6801adcc","name":"/larvling:status","input_tokens_est":85}
{"ts":"...","event":"knowledge","sid":"6801adcc","topics_inserted":1,"stmts_inserted":2}
{"ts":"...","event":"tasks","sid":"6801adcc","inserted":1}
{"ts":"...","event":"analysis","sid":"6801adcc","sentiment":"curious","session_tags":["greeting"],"input_tokens":1234,"output_tokens":567}
{"ts":"...","event":"tool_failure","sid":"6801adcc","tool":"Bash"}
{"ts":"...","event":"session_end","sid":"6801adcc","exchanges":1,"duration":0.2}
```

**PostToolUseFailure → Tool failure tracking:** `hooks/failure.py` records Bash tool failures as quality signals (`tool_failures` count and `failures_by_tool` breakdown) in `sessions.quality_signals`.

**Manual skills** (`/remember`, `/recall`, `/forget`) still work for explicit user-initiated knowledge management.

### Session Summaries

`inject_context()` automatically prints a `## Summary` hint when a summary is needed. Thresholds:
- **No summary yet:** shown when the session reaches 10+ messages
- **Stale summary:** shown when 5+ new messages have been added since the last summary

When you see the hint, offer `/summarize` via AskUserQuestion. Keep the offer brief and non-intrusive - a single sentence is enough. Don't ask repeatedly if the user declines.

### Knowledge Manager Agent

The `knowledge-manager` is a subagent for autonomous knowledge management. Claude can delegate to it proactively when the conversation reveals a preference, convention, decision, or knowledge worth persisting. It handles deduplication, consolidation, and domain classification autonomously — searching existing topics and statements before deciding whether to insert, update, or skip.

## Interaction Protocol

Use **AskUserQuestion** tool for structured input gathering:

| Type          | When to use                                    |
| ------------- | ---------------------------------------------- |
| Clarification | Inputs missing or ambiguous                    |
| Decision      | Multiple valid approaches exist                |
| Approval      | Stage work complete, need sign-off             |
| Summary       | Session summary is stale, offer update         |
| Knowledge     | About to save, update, or delete knowledge     |

Menu format:
- 2-4 options per question
- Each option: short label (1-5 words) + description
- One option would be Claude's recommendation
- Tool auto-includes "Other" option

Use **plain text** for:
- Presenting completed outputs
- Explaining rationale
- Summarizing captured information

## Run End

- Session timing and exchange count are recorded automatically
- No action needed from the agent
