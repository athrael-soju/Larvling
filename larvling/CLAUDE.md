# Larvling

> Your friendly memory companion. Every conversation is remembered.

Everything lives in `.claude/larvling.db` (SQLite, WAL mode).

## First Run

When the SessionStart context contains "Larvling - First Run", this is the very first time Larvling has been installed. You MUST welcome the user before doing anything else. Keep it warm, brief, and conversational - something like a friendly companion introducing itself. Include:
- That Larvling is now installed and will quietly remember their sessions
- That everything is automatic - no setup or extra effort needed
- Mention the available skills naturally: `/remember` to store knowledge, `/recall` to search it, `/forget` to remove it, `/sessions` to browse past sessions, `/summarize` for session summaries, `/export` to save a conversation as markdown, `/status` for a quick overview, `/maintain` to audit and consolidate knowledge, `/query` for direct SQL access
- Do NOT list technical details, hook names, or internal architecture. Keep the magic behind the curtain.

## Update Notice

When the SessionStart context contains "Larvling update available", mention it once to the user at the start of the conversation. Keep it brief - one sentence is enough. Don't repeat it later in the session.

## During a Session

Review the context Larvling injects at session start - it's your memory of what came before. Recording is automatic - just focus on the work.

### Schema Migration

- When the SessionStart context contains "Schema Migration Required", the database schema needs updating.
- Read the current and desired schemas provided, write and run the SQL to migrate (preserving all data), then bump the version in `larvling/db.py` with the provided command.
- A backup of the database has already been created.

**SQLite migration rules (MUST follow):**

1. **Simple additions** (new column, new table, new index) — use `ALTER TABLE ADD COLUMN` or `CREATE TABLE/INDEX IF NOT EXISTS` directly. No table rebuild needed.
2. **Column rename/type change/FK change** — SQLite requires the 12-step rebuild pattern:
   - `PRAGMA foreign_keys = OFF`
   - `BEGIN TRANSACTION`
   - `CREATE TABLE <new_table> (...)` with the correct schema
   - `INSERT INTO <new_table> SELECT ... FROM <old_table>`
   - `DROP TABLE <old_table>`
   - `ALTER TABLE <new_table> RENAME TO <old_table>`
   - Rebuild **every table** that has a FK referencing the rebuilt table (same pattern)
   - Rebuild any indexes/triggers on affected tables
   - `PRAGMA foreign_key_check` — must return zero rows
   - `COMMIT`
   - `PRAGMA foreign_keys = ON`
3. **Never leave temp tables behind** — no `_old`, `_backup`, `_temp` tables should exist after migration. `DROP TABLE` the originals, rename the new ones.
4. **Always verify FKs after migration** — run `PRAGMA foreign_key_check` and confirm empty result. If it returns rows, the migration is broken.
5. **Verify with `get_current_schema()`** — after migration, compare the live schema against `get_desired_schema()`. They must match (ignoring whitespace).

### `/query` - Direct SQL Access

Use `/query` to run any SQL against larvling.db. Claude writes the SQL based on conversation context. Supports `--read-only` flag to restrict to SELECT/PRAGMA/EXPLAIN only (used by the extraction agent).

**Schema:**
- `sessions (id TEXT PK, started_at TEXT, ended_at TEXT, duration_min REAL, title TEXT, agent_summary TEXT, exchange_count INT, summary_at TEXT, summary_msg_count INT, tags TEXT, summary_offered INT DEFAULT 0)`
- `messages (id INT PK AUTO, session_id TEXT FK, timestamp TEXT, role TEXT [user|assistant|system], content TEXT, metadata TEXT)`
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

**Quick Column Reference:**

| Table | Key columns |
|-------|-------------|
| topics | id, title, domain, tags |
| statements | id, topic_id, claim |
| tasks | id, title, status, priority, horizon, metadata |
| sessions | id, started_at, title, agent_summary |
| messages | id, session_id, role, content |
| updates | id, task_id, content, timestamp |

### Knowledge, Tasks & Unified Analysis

Larvling stores persistent knowledge in the `topics` + `statements` tables, and action items in the `tasks` + `updates` tables. Multiple mechanisms handle data extraction:

**UserPromptSubmit → Knowledge Context (read):** The `## Knowledge Context` directive prints on every exchange with the `query.py` path and topic/statement counts. Search for relevant knowledge and weave it into your response naturally.

**Stop → Unified analysis (write):** `analyze.py` runs as a command hook after every response, calling `sdk.py` (`call_model()`) for Agent SDK integration. The extraction agent has Bash tool access to query all 6 tables for dedup — given the full schema, it decides what queries to run. A single SDK call extracts multiple data types from the last exchange:
- **Knowledge** → `topics` + `statements` tables (hierarchical: topic groups related statements). Actions: `add_topic`, `add_statement`, `update_statement`, `update_topic`.
- **Session tags** → `sessions.tags` column, comma-separated, dynamically consolidated each exchange. The agent queries current tags itself.
- **Tasks** → `tasks` + `updates` tables. Actions: `add_task`, `add_update` (attach context/notes), `update_task` (modify status/priority/horizon with reason). Invalid fields skip the item and log to JSONL — no silent coercion.

**Log format** — JSONL (one JSON object per line) in `.claude/larvling.jsonl`:
```jsonl
{"ts":"2026-02-24T16:16:35","event":"prompt","sid":"6801adcc","n":1}
{"ts":"...","event":"context","sid":"6801adcc","injected":["5 topics, 11 statements","stale summary hint"]}
{"ts":"...","event":"response","sid":"6801adcc","chars":20,"is_dup":false}
{"ts":"...","event":"skill","sid":"6801adcc","name":"/larvling:status"}
{"ts":"...","event":"knowledge","sid":"6801adcc","topics_inserted":1,"stmts_inserted":2}
{"ts":"...","event":"tasks","sid":"6801adcc","inserted":1,"updates_inserted":2,"tasks_updated":1}
{"ts":"...","event":"extraction_skipped","sid":"6801adcc","action":"add_task","reason":"invalid domain","domain":"foobar"}
{"ts":"...","event":"analysis","sid":"6801adcc","session_tags":["greeting"]}
{"ts":"...","event":"session_end","sid":"6801adcc","exchanges":1,"duration":0.2}
```

**Manual skills** (`/remember`, `/recall`, `/forget`) still work for explicit user-initiated knowledge management.

### Session Summaries

`inject_context()` automatically prints a `## Summary` hint when a summary is needed. Thresholds:
- **No summary yet:** shown when the session reaches 10+ messages
- **Stale summary:** shown when 5+ new messages have been added since the last summary

When you see the hint, offer `/summarize` via AskUserQuestion. Keep the offer brief and non-intrusive - a single sentence is enough. Don't ask repeatedly if the user declines. The `summary-manager` agent handles the actual summarization work.

### Agents

**`knowledge-manager`** — Autonomous knowledge management. Claude can delegate to it proactively when the conversation reveals a preference, convention, decision, or knowledge worth persisting. It handles deduplication, consolidation, and domain classification autonomously — searching existing topics and statements before deciding whether to add, update, or skip.

**`summary-manager`** — Session summarization. Delegated to when the user accepts a `/summarize` offer or when the summary hint fires. Reads conversation pairs, writes a concise summary, and stores it.

**`knowledge-maintenance`** — Periodic knowledge base audit and consolidation. Delegated to when the user invokes `/maintain` or when the maintenance hint fires (50+ topics or 100+ statements). Identifies duplicate topics, redundant/stale statements, misclassified domains, and contradictions. Proposes changes via AskUserQuestion, applies only what the user approves. Never deletes — merges via statement reassignment and topic title updates.

## Interaction Protocol

Use **AskUserQuestion** tool for structured input gathering:

| Type          | When to use                                    |
| ------------- | ---------------------------------------------- |
| Clarification | Inputs missing or ambiguous                    |
| Decision      | Multiple valid approaches exist                |
| Approval      | Stage work complete, need sign-off             |
| Summary       | Session summary is stale, offer update         |
| Maintenance   | Knowledge base is large, offer /maintain       |
| Knowledge     | About to save or update knowledge               |

Menu format:
- 2-4 options per question
- Each option: short label (1-5 words) + description
- One option would be Claude's recommendation
- Tool auto-includes "Other" option

Use **plain text** for:
- Presenting completed outputs
- Explaining rationale
- Summarizing captured information

## Dependencies

- **Python 3.10+** — all scripts use standard library except `claude_agent_sdk`
- **claude-agent-sdk** (`pip install claude-agent-sdk`) — required for unified analysis (knowledge extraction, session tags, tasks)
- Install via: `pip install -r "${CLAUDE_PLUGIN_ROOT}/requirements.txt"`

## Run End

- Session timing and exchange count are recorded automatically
- No action needed from the agent
