# Larvling

> Your friendly memory companion. Every conversation is remembered.

Everything lives in `.claude/larvling.db` (SQLite, WAL mode). The dashboard at `.claude/dashboard.html` is refreshed on every hook.

## First Run

When the SessionStart context contains "Larvling - First Run", this is the very first time Larvling has been installed. You MUST welcome the user before doing anything else. Keep it warm, brief, and conversational - something like a friendly companion introducing itself. Include:
- That Larvling is now installed and will quietly remember their sessions
- A mention of the dashboard at `.claude/dashboard.html` for browsing past conversations
- That everything is automatic - no setup or extra effort needed
- Do NOT list technical details, hook names, or internal architecture. Keep the magic behind the curtain.

## During Run

- Review the context Larvling injects at session start - it's your memory of what came before
- Recording is automatic - just focus on the work

### Schema Migration

When the SessionStart context contains "Schema Migration Required", the database schema needs updating. Read the current and desired schemas provided, write and run the SQL to migrate (preserving all data), then bump the version with the provided command. A backup of the database has already been created.

### Facts

Larvling stores persistent facts via `/memorize`. Facts are not auto-injected — query them on demand. Whenever the conversation touches a topic that might have stored facts, proactively use `/memorize` to search. When the user shares facts, preferences, or decisions worth persisting, store them without being asked. Consider whether existing facts need updating based on what the user is saying now.

## Run End

- Session timing and exchange count are recorded automatically
- No action needed from the agent
