# Larvling

<p align="center">
  <img src="larvling.png" alt="Larvling logo" width="200" />
</p>

Your friendly memory companion for Claude Code. Larvling quietly imprints every conversation - prompts, responses, tool usage - and keeps it all in a searchable dashboard. No config needed, just install and go.

## Why Larvling?

- **Tiny** - under 38 KB total. Smaller than most READMEs out there
- **Zero dependencies** - no pip install, no node_modules, no build step. Just Python 3.8+ and the standard library
- **Portable** - works on any device that supports Claude Code plugins: macOS, Linux, Windows
- **Private** - all data stays local in a single SQLite file. Nothing leaves your machine
- **Instant** - no setup, no config, no onboarding. Install the plugin and it starts imprinting from message one
- **Lightweight** - SQLite WAL mode means near-zero overhead. Your agent won't even notice it's there

## Install

Requires Python 3.8+ and Claude Code 1.0.33+.

**From the terminal (CLI):**

```bash
# Add the marketplace source
claude plugin marketplace add https://github.com/athrael-soju/Larvling

# Install the plugin (local scope - this repo only)
claude plugin install larvling@athrael-soju --scope local
```

**From within Claude Code:**

```
/plugin marketplace add https://github.com/athrael-soju/Larvling
/plugin install larvling@athrael-soju --scope local
```

**For local development / testing:**

```bash
claude --plugin-dir ./larvling
```

## How It Works

Larvling hooks into the Claude Code lifecycle and remembers everything:

- **Imprints** every user prompt and agent response to a local SQLite database
- **Recalls** past session context on startup so the agent picks up where it left off
- **Generates** a two-panel HTML dashboard with search, sort, and filter

## Files

| File | What it does |
|------|-------------|
| `larvling/.claude-plugin/plugin.json` | Plugin manifest - name and description |
| `larvling/hooks/hooks.json` | Hook definitions - tells Claude Code when to call Larvling |
| `larvling/scripts/preflight.py` | Wakes up on session start, creates the DB or recalls context |
| `larvling/scripts/hooks.py` | Handles prompt logging, response capture, and session end |
| `larvling/scripts/dashboard.py` | Builds the HTML dashboard from the imprints |
| `larvling/scripts/db.py` | Shared database helpers |
| `larvling/CLAUDE.md` | Instructions for the agent |

## Uninstall

**From the terminal (CLI):**

```bash
claude plugin uninstall larvling@larvling

# Optionally remove the marketplace source
claude plugin marketplace remove athrael-soju
```

**From within Claude Code:**

```
/plugin uninstall larvling@larvling

# Optionally remove the marketplace source
/plugin marketplace remove larvling
```

To also remove stored data, delete the Larvling files from your project's `.claude/` directory:

```bash
rm .claude/larvling.db .claude/larvling.db-wal .claude/larvling.db-shm .claude/dashboard.html
```

## Data

All data stays local in the project's `.claude/` directory:

- `larvling.db` - SQLite database (WAL mode) with all imprints
- `dashboard.html` - static HTML dashboard, refreshed automatically
