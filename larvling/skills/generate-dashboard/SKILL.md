---
name: generate-dashboard
description: Generate the Larvling dashboard with Sessions and Fact Graph tabs
argument-hint: "--graph"
---

Generate the Larvling dashboard. Two modes:

**Sessions only (default)** — fast refresh, preserves existing graph data from the previous run:
```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/dashboard.py"
```

**Full with graph** — also regenerates the Fact Graph via Agent SDK:
```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/dashboard.py" --graph
```

Use `--graph` when the user explicitly wants the Fact Graph refreshed. Without it, the graph tab keeps whatever was last generated.

This generates `.claude/dashboard.html` with two tabs:
- **Sessions** — browse past conversations, messages, topics, sentiment
- **Fact Graph** — D3.js force-directed graph of stored facts and their relationships

If the dashboard is already up to date (no new data since last generation), the script will skip regeneration and report "up to date".

After running, confirm the output path to the user so they can open it in VS Code Live Preview or a browser.
