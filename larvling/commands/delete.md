---
name: delete
description: Delete a Larvling session from the database
arguments:
  - name: session
    description: "Session ID (short or full). Use 'list' to see available sessions, or 'all' to delete everything."
    required: false
---

Permanently delete a Larvling session and all its imprints from the database.

## Instructions

### Step 1: Session selection

If the user passed `list` as the session argument, or no argument at all, run:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/delete.py" --list
```
Show the results so the user can pick a session to delete.

### Step 2: Confirm with the user

Before deleting, tell the user exactly what will be removed:
- For a single session: the session ID and how many messages it contains
- For `all`: the total number of sessions and imprints

Ask for explicit confirmation before proceeding. This is irreversible.

### Step 3: Delete

For a single session:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/delete.py" <session_id>
```

For all sessions:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/delete.py" --all
```

### Step 4: Regenerate dashboard

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/dashboard.py"
```

Tell the user the session(s) have been deleted and the dashboard has been updated.
