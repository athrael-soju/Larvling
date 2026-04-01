---
name: maintain
description: Audit and consolidate Larvling's knowledge base
---

**Schema:**
- `topics (id INTEGER PK AUTO, title TEXT NOT NULL, domain TEXT NOT NULL, tags TEXT NOT NULL, created TEXT, updated TEXT)`
- `statements (id INTEGER PK AUTO, topic_id INTEGER FK→topics(id), claim TEXT NOT NULL, created TEXT, updated TEXT)`

Run SQL via:
```
$PY "${CLAUDE_PLUGIN_ROOT}/scripts/query.py" "<SQL>"
```

Create tasks to track the audit phases so the user sees progress:
1. **Audit knowledge base** (activeForm: "Auditing knowledge base") — delegate to the `knowledge-maintenance` agent
2. **Apply approved changes** (activeForm: "Applying changes") — mark complete after agent finishes

The agent will audit all topics and statements, identify issues (duplicates, stale entries, misclassifications, contradictions), propose changes, and apply only what the user approves.

Once the agent completes, present a brief before/after summary. Do not send follow-up messages to the agent after it finishes.

## Output Format

```
**Maintenance Complete**
- Merged 2 duplicate topics
- Updated 3 statement classifications
- Before: 12 topics, 45 statements
- After: 10 topics, 45 statements
```

## Final Step

**REQUIRED:** You MUST call AskUserQuestion (type: Decision) with these options after presenting the maintenance summary. Do not end your response without this menu:
- **View knowledge** — recall the updated knowledge base
- **Run again** — re-audit after changes were applied
- **Done** — no further action needed
