---
name: delete
description: Delete a Larvling session from the database
arguments:
  - name: session
    description: "Session ID (short or full). Use 'list' to see available sessions."
    required: false
---

Permanently delete a Larvling session and all its imprints from the database.

## Instructions

### Step 1: Session selection

If the user passed `list` as the session argument, or no argument at all, run:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/summarize.py" --list
```
Show the results so the user can pick a session to delete.

### Step 2: Confirm with the user

Before deleting, tell the user exactly what will be removed:
- The session ID
- How many messages it contains (from the list output)

Ask for explicit confirmation before proceeding.

### Step 3: Delete

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/delete.py" <session_id>
```

### Step 4: Regenerate dashboard

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/dashboard.py"
```

Tell the user the session has been deleted and the dashboard has been updated.
