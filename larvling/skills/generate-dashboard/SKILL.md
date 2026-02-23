---
name: generate-dashboard
description: Generate the Larvling dashboard with session history
---

Generate the Larvling dashboard:

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/dashboard.py"
```

This generates `.claude/dashboard.html` — browse past conversations, messages, topics, and sentiment.

After running, confirm the output path to the user so they can open it in VS Code Live Preview or a browser.
