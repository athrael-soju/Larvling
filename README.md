# Larvling

Your friendly memory companion for Claude Code. Larvling quietly imprints every conversation — prompts, responses, tool usage — and keeps it all in a searchable dashboard. No config needed, just install and go.

## Why Larvling?

- **Tiny** — under 38 KB total. Smaller than most READMEs out there
- **Zero dependencies** — no pip install, no node_modules, no build step. Just Python 3.8+ and the standard library
- **Portable** — works on any device that supports Claude Code plugins: macOS, Linux, Windows
- **Private** — all data stays local in a single SQLite file. Nothing leaves your machine
- **Instant** — no setup, no config, no onboarding. Install the plugin and it starts imprinting from message one
- **Lightweight** — SQLite WAL mode means near-zero overhead. Your agent won't even notice it's there

## Install

Requires Python 3.8+ and Claude Code 1.0.33+.

```bash
# Add the repo as a marketplace
/plugin marketplace add https://github.com/athrael-soju/Larvling

# Install the plugin
/plugin install larvling@larvling
```

**For local development / testing:**

```bash
claude --plugin-dir /path/to/Larvling/larvling
```

## How It Works

Larvling hooks into the Claude Code lifecycle and remembers everything:

- **Imprints** every user prompt and agent response to a local SQLite database
- **Recalls** past session context on startup so the agent picks up where it left off
- **Generates** a two-panel HTML dashboard with search, sort, and filter

## Files

| File | What it does |
|------|-------------|
| `larvling/plugin.json` | Plugin manifest — tells Claude Code when to call Larvling |
| `larvling/scripts/preflight.py` | Wakes up on session start, creates the DB or recalls context |
| `larvling/scripts/hooks.py` | Handles prompt logging, response capture, and session end |
| `larvling/scripts/dashboard.py` | Builds the HTML dashboard from the imprints |
| `larvling/scripts/db.py` | Shared database helpers |
| `larvling/CLAUDE.md` | Instructions for the agent |

## Data

All data stays local in the project's `.claude/` directory:

- `larvling.db` — SQLite database (WAL mode) with all imprints
- `dashboard.html` — static HTML dashboard, refreshed automatically
