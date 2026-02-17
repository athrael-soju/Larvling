---
name: export
description: Export a Larvling session conversation to markdown
arguments:
  - name: session
    description: "Session ID (short or full) to export. Use 'list' to see available sessions, or 'all' to export everything."
    required: false
---

List sessions:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/export.py" --list
```

Export a single session:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/export.py" <session_id> .claude/exports/<session_id>.md
```

Export all sessions:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/export.py" --all .claude/exports
```
