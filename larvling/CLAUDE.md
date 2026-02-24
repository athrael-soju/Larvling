# Larvling

> Your friendly memory companion. Every conversation is remembered.

Everything lives in `.claude/larvling.db` (SQLite, WAL mode). The dashboard at `.claude/dashboard.html` is generated on-demand via `/generate-dashboard`.

## First Run

When the SessionStart context contains "Larvling - First Run", this is the very first time Larvling has been installed. You MUST welcome the user before doing anything else. Keep it warm, brief, and conversational - something like a friendly companion introducing itself. Include:
- That Larvling is now installed and will quietly remember their sessions
- A mention of the dashboard at `.claude/dashboard.html` for browsing past conversations
- That everything is automatic - no setup or extra effort needed
- Mention the available skills naturally: `/remember` to store a fact, `/recall` to search them, `/forget` to remove one, `/sessions` to browse past sessions, `/summarize` for session summaries, `/export` to save a conversation as markdown, `/status` for a quick overview, `/query` for direct SQL access, `/generate-dashboard` to build the visual dashboard
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
- `sessions (id TEXT PK, started_at TEXT, ended_at TEXT, duration_min REAL, title TEXT, agent_summary TEXT, exchange_count INT, summary_at TEXT, summary_msg_count INT, topics TEXT, quality_signals TEXT)`
- `messages (id INT PK AUTO, session_id TEXT FK, timestamp TEXT, role TEXT, content TEXT, metadata TEXT)`
- `facts (id INTEGER PK AUTO, claim TEXT NOT NULL, domain TEXT NOT NULL, tags TEXT NOT NULL, created TEXT NOT NULL DEFAULT date('now'), updated TEXT)`

**Examples:**

```
/query "SELECT * FROM facts"
/query "SELECT * FROM facts WHERE claim LIKE '%deploy%' OR tags LIKE '%ci%'"
/query "SELECT id, title, agent_summary FROM sessions WHERE agent_summary IS NOT NULL ORDER BY started_at DESC LIMIT 5"
/query "INSERT INTO facts (claim, domain, tags) VALUES ('test fact', 'technical', 'testing')"
/query "DELETE FROM facts WHERE id = 1"
/query "SELECT * FROM messages WHERE content LIKE '%auth%' LIMIT 10" --json
```

### Facts & Unified Extraction

Larvling stores persistent facts in the `facts` table. Multiple mechanisms handle data extraction:

**UserPromptSubmit → Fact Context (read):** The `## Fact Context` directive prints on every exchange with the `query.py` path and fact count. Search for relevant facts and weave them into your response naturally.

**Stop → Unified extraction (write):** `extract.py` runs as a command hook after every response. It contains `call_model()` (Agent SDK integration) and uses `transcript.py` for parsing. A single Agent SDK call extracts multiple data types from the last exchange:
- **Facts** → `facts` table (unchanged)
- **Sentiment** (focused/curious/frustrated/satisfied/neutral) → `messages.metadata` JSON on the last assistant message
- **Topics** → `sessions.topics` column, comma-separated, dynamically consolidated each exchange (merges similar, drops irrelevant, adds new)
- **Action items** → `messages.metadata` JSON on the last assistant message

**Stop → Quality signals (no SDK call):** `hooks/stop.py` computes quality signals from the response text (error counts, retry patterns, tool call totals) and stores them in `sessions.quality_signals` as JSON. Pure Python, no latency cost.

**PostToolUseFailure → Tool failure tracking:** `hooks/failure.py` records Bash tool failures as quality signals (`tool_failures` count and `failures_by_tool` breakdown) in `sessions.quality_signals`.

**PreCompact → Context preservation:** `precompact.py` injects critical session context (current topics, recent facts, skill reminders) before compaction so it survives context summarization.

**Manual skills** (`/remember`, `/recall`, `/forget`) still work for explicit user-initiated fact management.

### Session Summaries

`inject_context()` automatically prints a `## Summary` hint when a summary is needed. Thresholds:
- **No summary yet:** shown when the session reaches 10+ messages
- **Stale summary:** shown when 5+ new messages have been added since the last summary

When you see the hint, offer `/summarize` via AskUserQuestion. Keep the offer brief and non-intrusive - a single sentence is enough. Don't ask repeatedly if the user declines.

### Fact Manager Agent

The `fact-manager` is a subagent for autonomous fact management. Claude can delegate to it proactively when the conversation reveals a preference, convention, decision, or knowledge worth persisting. It handles deduplication, consolidation, and domain classification autonomously — searching existing facts before deciding whether to insert, update, or skip.

## Interaction Protocol

Use **AskUserQuestion** tool for structured input gathering:

| Type          | When to use                             |
| ------------- | --------------------------------------- |
| Clarification | Inputs missing or ambiguous             |
| Decision      | Multiple valid approaches exist         |
| Approval      | Stage work complete, need sign-off      |
| Summary       | Session summary is stale, offer update  |
| Fact mgmt     | About to save, update, or delete a fact |

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
