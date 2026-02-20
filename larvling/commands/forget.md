---
name: forget
description: Remove a stored fact from Larvling's memory
arguments:
  - name: fact
    description: "Fact ID (e.g. M-001) or keyword to search for"
    required: false
---

Remove a fact from Larvling's memory using `/query`.

1. Find matching facts:
   ```
   /query "SELECT id, claim, domain, tags FROM facts WHERE id = '<search>' OR claim LIKE '%<search>%' OR tags LIKE '%<search>%'"
   ```

2. Present the matches to the user. Use AskUserQuestion to confirm which fact(s) to delete.

3. Delete the confirmed fact:
   ```
   /query "DELETE FROM facts WHERE id = '<confirmed_id>'"
   ```

4. Confirm deletion to the user.
