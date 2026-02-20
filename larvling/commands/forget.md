---
name: forget
description: Remove a stored fact from Larvling's memory
arguments:
  - name: fact
    description: "Fact ID (e.g. M-001) or keyword to search for"
    required: false
---
1. Find matching facts:
   python "${CLAUDE_PLUGIN_ROOT}/scripts/facts.py" forget $ARGUMENTS

2. Present the matches to the user. Use AskUserQuestion to confirm which fact(s) to delete.

3. Delete the confirmed fact:
   python "${CLAUDE_PLUGIN_ROOT}/scripts/query.py" "DELETE FROM facts WHERE id = '<confirmed_id>'"

4. Confirm deletion.
