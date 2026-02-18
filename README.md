<p align="center">
  <img src="larvling.png" alt="Larvling logo" width="350" />
</p>

# Larvling

Your friendly memory companion for Claude Code. Larvling quietly imprints every conversation - prompts, responses, tool usage - and keeps it all in a searchable dashboard. No config needed, just install and go.

## The 6 Principles of Larvling

- **Tiny** - under 100 KB total
- **Zero dependencies** - no pip install, no node_modules, no build step
- **Portable** - works on any device that supports Claude Code plugins: macOS, Linux, Windows
- **Private** - all data stays local in a single SQLite file
- **Instant** - no setup, no config, no onboarding
- **Lightweight** - SQLite WAL mode means near-zero overhead

## Install

Requires Claude Code 1.0.33+.

**1. Add the marketplace source:**

```bash
# From the terminal
claude plugin marketplace add https://github.com/athrael-soju/Larvling

# Or from within Claude Code
/plugin marketplace add https://github.com/athrael-soju/Larvling
```

**2. Install the plugin with your preferred scope:**

| Scope   | Flag              | Effect                                                                 |
| ------- | ----------------- | ---------------------------------------------------------------------- |
| Local   | `--scope local`   | Active only in the current project                                     |
| Project | `--scope project` | Active for all users of the project (writes to `.claude/plugins.json`) |
| User    | `--scope user`    | Active across all your projects                                        |

```bash
# From the terminal
claude plugin install larvling@athrael-soju --scope local

# Or from within Claude Code
/plugin install larvling@athrael-soju --scope local
```

> **Which scope should I use?** `local` is recommended for most users — it keeps Larvling scoped to the project you're working in. Use `user` if you want Larvling active everywhere, or `project` to share the plugin config with your team via source control.

**For local development / testing:**

```bash
claude --plugin-dir ./larvling
```

> **Tip:** `--plugin-dir` loads the plugin directly from the repo - no caching involved. This is the simplest way to iterate on changes.

## Local Development

When Larvling is installed via `plugin install`, Claude Code copies the plugin files into a **cache directory** and runs hooks from there - not from the repo. This means editing files in the repo has no immediate effect on the running plugin.

### How to test changes

**Option A - `--plugin-dir` (recommended):**

```bash
claude --plugin-dir ./larvling
```

This bypasses the cache entirely and loads the plugin straight from the repo. Changes take effect on the next session start.

**Option B - Reinstall the plugin:**

```bash
claude plugin uninstall larvling@larvling
claude plugin install larvling@athrael-soju --scope local
```

This refreshes the cache with the latest files from the repo. Requires restarting the session.

**Option C - Copy files to the cache manually:**

```bash
# Find the cache directory
# Linux / macOS
ls ~/.claude/plugins/cache/athrael-soju/larvling/

# Windows
dir %USERPROFILE%\.claude\plugins\cache\athrael-soju\larvling\
```

Copy your changed files into the cache directory (note: the cache uses a **flat structure** - there is no `larvling/` prefix inside it). Restart the session to pick up the changes.

### Cache gotchas

- The cache path includes a hash suffix (e.g., `b378d4eab0ee`) that changes when the plugin is reinstalled
- `${CLAUDE_PLUGIN_ROOT}` in hooks and commands points to the cache, not the repo
- Committing + updating the plugin via `plugin install` also refreshes the cache

## How It Works

<p align="center">
  <img src="diagram.png" alt="Larvling capabilities diagram" width="100%" />
</p>

## Commands

| Command      | What it does                                                                                                             |
| ------------ | ------------------------------------------------------------------------------------------------------------------------ |
| `/summarize` | Generate an LLM-written summary of a session. Stored in the DB for context injection and downloadable from the dashboard |
| `/export`    | Export a session's full conversation to a markdown file                                                                  |
| `/delete`    | Permanently delete a session and all its data from the database                                                          |
| `/search`    | Search across all session content with grouped results and context snippets                                              |
| `/memorize`  | Manage persistent facts and knowledge that the agent recalls on demand                                                   |

## Dashboard

<p align="center">
  <img src="https://github.com/user-attachments/assets/63f94432-e1be-4ef8-b56b-8934bb37358d" alt="Larvling capabilities diagram" width="100%" />
</p>
The dashboard at `.claude/dashboard.html` provides a two-panel view of all sessions. Each session has a "..." menu with:

- **Download summary** - save the LLM-generated summary as a markdown file (only shown if a summary exists)
- **Export session** - download the full conversation as markdown

The dashboard polls every 3 seconds and reloads automatically when new data is available.

## Files

| File                                       | What it does                                                                             |
| ------------------------------------------ | ---------------------------------------------------------------------------------------- |
| `larvling/.claude-plugin/plugin.json`      | Plugin manifest - name and description                                                   |
| `larvling/hooks/hooks.json`                | Hook definitions - tells Claude Code when to call Larvling                               |
| `larvling/scripts/db.py`                   | Shared database helpers and schema management                                            |
| `larvling/scripts/preflight.py`            | Wakes up on session start, creates the DB or recalls context                             |
| `larvling/scripts/hooks.py`                | Handles prompt logging, response capture, and session end                                |
| `larvling/scripts/dashboard.py`            | Builds the HTML dashboard from the database                                              |
| `larvling/scripts/dashboard.html.template` | HTML/CSS/JS template for the dashboard                                                   |
| `larvling/scripts/summarize.py`            | Fetches conversation pairs and stores session summaries                                  |
| `larvling/scripts/export.py`               | Exports a session conversation to markdown                                               |
| `larvling/scripts/delete.py`               | Deletes a session and its data from the database                                         |
| `larvling/scripts/search.py`               | Searches across all session content                                                      |
| `larvling/scripts/memorize.py`             | CRUD operations for persistent memories                                                  |
| `larvling/commands/*.md`                   | Slash command definitions for `/summarize`, `/export`, `/delete`, `/search`, `/memorize` |
| `larvling/CLAUDE.md`                       | Instructions for the agent                                                               |

## Uninstall

```bash
# From the terminal (use the same scope you installed with)
claude plugin uninstall larvling@athrael-soju --scope local

# Or from within Claude Code
/plugin uninstall larvling@athrael-soju --scope local

# Optionally remove the marketplace source
claude plugin marketplace remove athrael-soju
```

To also remove stored data, delete the Larvling files from your project's `.claude/` directory:

```bash
rm .claude/larvling.db .claude/larvling.db-wal .claude/larvling.db-shm .claude/dashboard.html
```

## Data

All data stays local in the project's `.claude/` directory:

- `larvling.db` - SQLite database (WAL mode) with encounters, imprints, reflections, and memories
- `dashboard.html` - static HTML dashboard, refreshed automatically
