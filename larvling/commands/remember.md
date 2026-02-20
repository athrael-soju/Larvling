---
name: remember
description: Store a fact that Larvling will remember across sessions
arguments:
  - name: fact
    description: "The fact, preference, or decision to remember"
    required: false
---

Store a fact in Larvling's memory using `/query`.

1. Check for existing similar facts:
   ```
   /query "SELECT id, claim FROM facts WHERE LOWER(claim) LIKE '%<keywords>%'"
   ```

2. If an exact or very similar match exists, report it to the user — no need to store a duplicate.

3. If no match, get the next fact ID and insert:
   ```
   /query "SELECT id FROM facts WHERE id LIKE 'M-%' ORDER BY CAST(SUBSTR(id, 3) AS INTEGER) DESC LIMIT 1"
   /query "INSERT INTO facts (id, claim) VALUES ('M-<next>', '<fact>')"
   ```

4. Confirm storage to the user.
