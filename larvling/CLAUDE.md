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

- **First init:** When the SessionStart context contains "# Larvling Ready", this is the very first time Larvling has been installed. Greet the user with a short message letting them know Larvling has been initialized and is now tracking conversations. Mention the dashboard at `.claude/dashboard.html`.
- On session start, review the context Larvling injects — it's your memory of what came before
- Imprinting is automatic — just focus on the work
- The user can open `.claude/dashboard.html` to browse past sessions
