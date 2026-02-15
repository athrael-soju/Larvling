# Larvling

> Self-bootstrapping project scaffold. Three seed files grow into a full project.

## Mode Detection

When your SessionStart hook (`scripts/preflight.py`) fires:

- **"BOOTSTRAP MODE"** → Read `DNA.md` and execute the bootstrap protocol starting from Phase 1.
- **"BOOTSTRAP INCOMPLETE"** → Read `DNA.md` and resume bootstrap. Check the audit table for what was already completed.
- Otherwise → You are in a live project. Follow the rules below.

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
