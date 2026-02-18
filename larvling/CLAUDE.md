# Larvling

> Your friendly memory companion. Every conversation is remembered.

Everything lives in `.claude/larvling.db` (SQLite, WAL mode). The dashboard at `.claude/dashboard.html` is refreshed on every hook.

## For the Agent

- **First init:** When the SessionStart context contains "Larvling - First Run", this is the very first time Larvling has been installed. You MUST welcome the user before doing anything else. Keep it warm, brief, and conversational - something like a friendly companion introducing itself. Include:
  - That Larvling is now installed and will quietly remember their sessions
  - A mention of the dashboard at `.claude/dashboard.html` for browsing past conversations
  - That everything is automatic - no setup or extra effort needed
  - Do NOT list technical details, hook names, or internal architecture. Keep the magic behind the curtain.
- On session start, review the context Larvling injects - it's your memory of what came before
- Recording is automatic - just focus on the work
- **Facts**: Larvling stores persistent facts via `/memorize`. You manage your own memory — nothing is auto-injected.
  - **Recall**: At session start and whenever the conversation touches a topic that might have stored facts, proactively use `/memorize` to list or search. You decide what's relevant and how much to review.
  - **Create**: When the user shares facts, preferences, or decisions worth persisting across sessions, proactively use `/memorize` to store them — don't wait to be asked.
  - **Maintain**: Consider whether existing facts need updating or have become outdated based on what the user is saying now.
