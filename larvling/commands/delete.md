---
name: delete
description: Delete a Larvling session from the database
arguments:
  - name: session
    description: "Session ID (short or full). Use 'list' to see available sessions, or 'all' to delete everything."
    required: false
---

List sessions:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/delete.py" --list
```

**Always confirm with the user before deleting. This is irreversible.**

Delete a single session:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/delete.py" <session_id>
```

Delete all sessions:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/delete.py" --all
```

After deleting, regenerate the dashboard:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/dashboard.py"
```
