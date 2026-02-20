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

Larvling stores persistent facts in the `facts` table. Proactively search for relevant facts whenever the conversation touches a topic that might have stored knowledge:
- Use `/recall` or `/query` to search facts when a topic comes up — don't wait to be asked.
- When the user shares facts, preferences, or decisions worth persisting, store them via `/remember` or `/query` INSERT without being asked.
- Use `/forget` to remove facts that are outdated or wrong.
- Use `M-NNN` format for fact IDs. To get the next ID: `SELECT id FROM facts WHERE id LIKE 'M-%' ORDER BY CAST(SUBSTR(id, 3) AS INTEGER) DESC LIMIT 1`

Consider whether existing facts need updating based on what the user is saying now.

### Session Summaries

  As the conversation grows, periodically offer to generate a summary using `/summarize`. Before offering, run `/summarize list` to check the summary status - it shows `[summarized X/Y msgs]` where X is how many messages the summary covers and Y is the current count. Only offer when:
- The session has no summary and has had ~10+ exchanges
- The summary is stale (current message count is significantly higher than the summarized count)

Keep the offer brief and non-intrusive - a single sentence is enough. Don't ask repeatedly if the user declines.

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
