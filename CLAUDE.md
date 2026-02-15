# Larvling

> Project scaffold with built-in auditing. Seed files provide conversation tracking out of the box; run `/bootstrap` to customize.

## Mode Detection

When your SessionStart hook (`scripts/preflight.py`) fires:

- **"BOOTSTRAP INCOMPLETE"** → A previous `/bootstrap` was started but not finished. Read `DNA.md` and resume where it left off. Check the audit table for what was already completed.
- Otherwise → You are in a live project. Auditing is active. Follow the rules below.

## Session Protocol

- On session start, review the context injected by preflight
- Log decisions and progress to the audit table as you work
- On session end, hook scripts capture the summary

## Capabilities

You can spawn **agent teams** — parallel Claude Code sessions coordinating through a shared task list and direct messaging. Use `TeamCreate`, `Task`, `SendMessage`, `TeamDelete`. Prefer subagents for focused work; prefer teams when teammates need to discuss or challenge each other.

---

## Project Rules

*This section will be replaced during bootstrap with project-specific rules.*

---
