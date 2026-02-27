# Larvling

> Your friendly memory companion. Every conversation is remembered.

Larvling is a [Claude Code plugin](https://docs.anthropic.com/en/docs/claude-code/plugins) that adds persistent memory to your Claude Code sessions. It automatically tracks conversations, extracts knowledge, manages tasks, and provides rich session context.

## Features

- **Automatic session tracking** — every conversation logged with timing and exchange counts
- **Knowledge extraction** — preferences, decisions, and domain knowledge automatically identified and stored
- **Task management** — TODOs and commitments extracted, tracked, and updated across sessions with progress notes
- **Session context** — previous sessions, relevant knowledge, and open tasks injected at startup
- **Git-aware relevance** — surfaces past sessions related to your current working files

## Installation

```bash
claude plugin install athrael-soju/Larvling
```

Or for development:

```bash
claude --plugin-dir ./larvling
```

### Dependencies

```bash
pip install -r larvling/requirements.txt
```

## Skills

| Skill | Description |
|-------|-------------|
| `/recall` | Search stored knowledge |
| `/remember` | Store knowledge explicitly |
| `/forget` | Remove stored knowledge |
| `/sessions` | Browse past sessions |
| `/summarize` | Generate session summaries |
| `/export` | Export conversations to markdown |
| `/status` | Quick overview of Larvling's state |
| `/maintain` | Audit and consolidate the knowledge base |
| `/query` | Direct SQL access to larvling.db |

## Architecture

- **Database**: SQLite (`.claude/larvling.db`) with WAL mode
- **Tables**: `sessions`, `messages`, `topics`, `statements`, `tasks`, `updates`
- **Hooks**: SessionStart, UserPromptSubmit, Stop, SessionEnd
- **Agents**: `knowledge-manager` (proactive knowledge dedup), `summary-manager` (session summaries), `knowledge-maintenance` (periodic knowledge audit)
- **Analysis**: Unified Sonnet SDK call at Stop extracts knowledge, tags, and tasks — agent queries the DB dynamically for dedup

## License

MIT
