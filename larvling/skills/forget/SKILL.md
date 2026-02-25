---
name: forget
description: Remove stored knowledge from Larvling's memory
argument-hint: "[topic/statement ID or keyword]"
disable-model-invocation: true
---

**Schema:**
- `topics (id INTEGER PK AUTO, title TEXT NOT NULL, domain TEXT NOT NULL, tags TEXT NOT NULL, created TEXT, updated TEXT)`
- `statements (id INTEGER PK AUTO, topic_id INTEGER FK→topics(id), claim TEXT NOT NULL, created TEXT, updated TEXT)`

Find the knowledge to remove — by ID, keyword, or by asking the user to clarify. Show matching item(s) and use AskUserQuestion to confirm before deleting. When deleting the last statement under a topic, delete the topic too.

Run SQL via:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/query.py" "<SQL>"
```
