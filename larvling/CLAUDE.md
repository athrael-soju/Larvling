# Larvling

> Your friendly memory companion. Every conversation leaves an imprint.

Larvling quietly watches the conversation lifecycle and remembers everything so you don't have to. Each session starts with context from past conversations, and a searchable dashboard keeps it all browsable.

## What Happens Behind the Scenes

- **SessionStart** — wakes up, creates the DB on first run, or recalls past session context
- **UserPromptSubmit** — imprints each user prompt and regenerates the dashboard
- **Stop** — reads the transcript and imprints the agent's last response
- **SessionEnd** — notes how long the session lasted and captures the session title (first user prompt)

Everything lives in `.claude/larvling.db` (SQLite, WAL mode). The dashboard at `.claude/dashboard.html` is refreshed on every hook.

## Commands

- `/summarize` — generate an LLM-written summary of a session (stored in DB for context injection, downloadable from the dashboard)
- `/export` — export a session's full conversation to a markdown file
- `/delete` — permanently delete a session and all its imprints from the database
- `/stats` — view aggregate statistics (sessions, messages, tools, activity charts)
- `/search <query>` — search across all session content with grouped results and context snippets

## For the Agent

- **First init:** When the SessionStart context contains "Larvling — First Run", this is the very first time Larvling has been installed. You MUST welcome the user before doing anything else. Keep it warm, brief, and conversational — something like a friendly companion introducing itself. Include:
  - That Larvling is now installed and will quietly remember their sessions
  - A mention of the dashboard at `.claude/dashboard.html` for browsing past conversations
  - That everything is automatic — no setup or extra effort needed
  - Do NOT list technical details, hook names, or internal architecture. Keep the magic behind the curtain.
- On session start, review the context Larvling injects — it's your memory of what came before
- Imprinting is automatic — just focus on the work
- The user can open `.claude/dashboard.html` to browse past sessions
