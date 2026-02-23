---
name: generate-dashboard
description: Generate the Larvling dashboard with Sessions and Fact Graph tabs
argument-hint: (no arguments)
---

Generate the Larvling dashboard by running:

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/dashboard.py"
```

This generates `.claude/dashboard.html` with two tabs:
- **Sessions** — browse past conversations, messages, topics, sentiment
- **Fact Graph** — D3.js force-directed graph of stored facts and their relationships

If the dashboard is already up to date (no new data since last generation), the script will skip regeneration and report "up to date".

After running, confirm the output path to the user so they can open it in VS Code Live Preview or a browser.
