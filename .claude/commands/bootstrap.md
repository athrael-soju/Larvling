---
description: Customize project tracking — interview and generate tables, hooks, commands
allowed-tools: Bash, Read, Write, Edit, Grep, Glob
---

Log `bootstrap_start` to the audit table:

```sql
INSERT INTO audit (event_type, content) VALUES ('bootstrap_start', 'Bootstrap initiated by user');
```

Then read `DNA.md` and execute the bootstrap protocol starting from Phase 1 (Interview).

Log every action to the audit table from this point forward.
