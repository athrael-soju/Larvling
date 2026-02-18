---
name: memorize
description: Manage Larvling memories (persistent facts and knowledge)
arguments:
  - name: action
    description: "Action: list, add, update, delete, or search"
    required: true
  - name: args
    description: "Arguments for the action (claim text, memory ID, search query, etc.)"
    required: false
---

## Actions

### List memories
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/memorize.py" --list
```

### Add a memory
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/memorize.py" --add "CLAIM" --domain DOMAIN --tags "TAGS" --confidence CONFIDENCE --source SOURCE --notes "NOTES"
```

Fields:
- **claim** (required): The atomic factual assertion
- **domain**: technical | people | financial | decision | benchmark | insight
- **tags**: Comma-separated tags (e.g. "model:kimi,hw:mi325x")
- **confidence**: verified | observed (default) | inferred
- **source**: Where this fact came from (encounter ID, "paper", "email", etc.)
- **notes**: Additional context

### Update a memory
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/memorize.py" --update M-NNN field=value [field=value...]
```

### Delete a memory
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/memorize.py" --delete M-NNN
```

### Search memories
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/memorize.py" --search "QUERY"
```

After making changes, regenerate the dashboard:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/dashboard.py"
```
