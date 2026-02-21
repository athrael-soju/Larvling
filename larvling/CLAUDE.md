# Larvling

> Your friendly memory companion. Every conversation is remembered.

Everything lives in `.claude/larvling.db` (SQLite, WAL mode). The dashboard at `.claude/dashboard.html` is refreshed on every hook.

## First Run

When the SessionStart context contains "Larvling - First Run", this is the very first time Larvling has been installed. You MUST welcome the user before doing anything else. Keep it warm, brief, and conversational - something like a friendly companion introducing itself. Include:
- That Larvling is now installed and will quietly remember their sessions
- A mention of the dashboard at `.claude/dashboard.html` for browsing past conversations
- That everything is automatic - no setup or extra effort needed
- Mention the available commands naturally: `/remember` to store a fact, `/recall` to search them, `/forget` to remove one, `/sessions` to browse past sessions, `/summarize` for session summaries, `/export` to save a conversation as markdown, `/status` for a quick overview, `/query` for direct SQL access
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
- `sessions (id TEXT PK, started_at TEXT, ended_at TEXT, duration_min REAL, title TEXT, agent_summary TEXT, exchange_count INT, summary_at TEXT, summary_msg_count INT)`
- `messages (id INT PK AUTO, session_id TEXT FK, timestamp TEXT, role TEXT, content TEXT, metadata TEXT)`
- `facts (id TEXT PK, claim TEXT NOT NULL, domain TEXT, tags TEXT, confidence TEXT DEFAULT 'observed', source TEXT, established TEXT NOT NULL DEFAULT date('now'), confirmed TEXT, expires TEXT, notes TEXT)`

**Examples:**

```
/query "SELECT * FROM facts"
/query "SELECT * FROM facts WHERE claim LIKE '%deploy%' OR tags LIKE '%ci%'"
/query "SELECT id, title, agent_summary FROM sessions WHERE agent_summary IS NOT NULL ORDER BY started_at DESC LIMIT 5"
/query "INSERT INTO facts (id, claim, domain) VALUES ('M-099', 'test fact', 'technical')"
/query "DELETE FROM facts WHERE id = 'M-099'"
/query "SELECT * FROM messages WHERE content LIKE '%auth%' LIMIT 10" --json
```

### Facts

Larvling stores persistent facts in the `facts` table. The `inject_context()` hook prints on every exchange:
- **Fact count** and the `query.py` path for running SQL
- **Column list:** id, claim, domain, tags, confidence, source, established, confirmed, expires, notes
- **Directive:** silently query/insert/update/remove facts after responding; use `M-NNN` IDs; never mention fact management to the user

**Automatic fact management:** After responding to the user, silently review the exchange and manage facts as needed:
- **Query** relevant facts using the `query.py` path from the Fact Check context (e.g. `WHERE claim LIKE '%topic%'`).
- **Insert** new facts when the user shares preferences, decisions, or knowledge worth persisting.
- **Update** existing facts when the user contradicts or refines a stored fact.
- **Remove** facts that are outdated or wrong.
- Use `M-NNN` format for fact IDs. Never mention fact management to the user — it should be invisible.

**Manual commands** (`/remember`, `/recall`, `/forget`) still work for explicit user-initiated fact management.

### Session Summaries

`inject_context()` automatically prints a `## Summary` hint when a summary is needed. Thresholds:
- **No summary yet:** shown when the session reaches 10+ messages
- **Stale summary:** shown when 6+ new messages have been added since the last summary

When you see the hint, offer `/summarize` via AskUserQuestion. Keep the offer brief and non-intrusive - a single sentence is enough. Don't ask repeatedly if the user declines.

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
