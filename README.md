# Larvling

Your friendly memory companion for Claude Code. Larvling quietly imprints every conversation — prompts, responses, tool usage — and keeps it all in a searchable dashboard. No config needed, just install and go.

## Install

Add Larvling as a Claude Code plugin. Requires Python 3.8+.

## How It Works

Larvling hooks into the Claude Code lifecycle and remembers everything:

- **Imprints** every user prompt and agent response to a local SQLite database
- **Recalls** past session context on startup so the agent picks up where it left off
- **Generates** a two-panel HTML dashboard with search, sort, and filter
- **Zero config** — works out of the box, no setup required

## Files

| File | What it does |
|------|-------------|
| `plugin.json` | Plugin manifest — tells Claude Code when to call Larvling |
| `scripts/preflight.py` | Wakes up on session start, creates the DB or recalls context |
| `scripts/hooks.py` | Handles prompt logging, response capture, and session end |
| `scripts/dashboard.py` | Builds the HTML dashboard from the imprints |
| `scripts/db.py` | Shared database helpers |
| `CLAUDE.md` | Instructions for the agent |

## Data

All data stays local in the project's `.claude/` directory:

- `larvling.db` — SQLite database (WAL mode) with all imprints
- `dashboard.html` — static HTML dashboard, refreshed automatically
