# Larvling

> Your friendly memory companion. Every conversation leaves an imprint.

Everything lives in `.claude/larvling.db` (SQLite, WAL mode). The dashboard at `.claude/dashboard.html` is refreshed on every hook.

## For the Agent

- **First init:** When the SessionStart context contains "Larvling - First Run", this is the very first time Larvling has been installed. You MUST welcome the user before doing anything else. Keep it warm, brief, and conversational - something like a friendly companion introducing itself. Include:
  - That Larvling is now installed and will quietly remember their sessions
  - A mention of the dashboard at `.claude/dashboard.html` for browsing past conversations
  - That everything is automatic - no setup or extra effort needed
  - Do NOT list technical details, hook names, or internal architecture. Keep the magic behind the curtain.
- On session start, review the context Larvling injects - it's your memory of what came before
- Imprinting is automatic - just focus on the work
- **Memories**: Larvling can store persistent facts via `/memorize`. These are injected into every session's context. Use them for important knowledge that should persist across sessions.
