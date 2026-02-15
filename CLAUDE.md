# Zergling

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

You can spawn **agent teams** — multiple Claude Code sessions working in parallel, coordinating through a shared task list and direct messaging. Use this when a task benefits from parallel exploration or independent workstreams:

- **Research & review**: multiple teammates investigate different aspects simultaneously
- **Parallel implementation**: teammates each own separate modules/files without conflicts
- **Competing hypotheses**: teammates test different theories and challenge each other
- **Cross-layer work**: frontend, backend, tests each owned by a different teammate

Use `TeamCreate` to start a team, `Task` to spawn teammates, `SendMessage` to coordinate. Each teammate is a full Claude Code session with its own context. Prefer subagents for focused tasks where only the result matters; prefer teams when teammates need to discuss, coordinate, or challenge each other.

---

## Project Rules

*This section will be replaced during bootstrap with project-specific rules.*

---
