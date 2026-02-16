# Larvling

> Your friendly memory companion. Every conversation leaves an imprint.

Larvling quietly watches the conversation lifecycle and remembers everything so you don't have to. Each session starts with context from past conversations, and a searchable dashboard keeps it all browsable.

## What Happens Behind the Scenes

- **SessionStart** — wakes up, creates the DB on first run, or recalls past session context
- **UserPromptSubmit** — imprints each user prompt
- **Stop** — reads the transcript and imprints the agent's last response
- **SessionEnd** — notes how long the session lasted

Everything lives in `.claude/larvling.db` (SQLite, WAL mode). The dashboard at `.claude/dashboard.html` is refreshed on every hook.

## For the Agent

- **First init:** When the SessionStart context contains "Larvling — First Run", this is the very first time Larvling has been installed. You MUST greet the user with a short welcome message letting them know Larvling is now active and tracking conversations. Mention the dashboard at `.claude/dashboard.html`. This takes priority over other startup behavior.
- On session start, review the context Larvling injects — it's your memory of what came before
- Imprinting is automatic — just focus on the work
- The user can open `.claude/dashboard.html` to browse past sessions
