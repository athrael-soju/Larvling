---
name: summarize
description: Generate or view a session summary
arguments:
  - name: session
    description: "Session ID (short or full). Omit to summarize the current session."
    required: false
---

Generate or view a session summary using `/query`.

Resolve the session ID (use `$ARGUMENTS` if provided, otherwise the current session from context).

1. Check current status:
   ```
   /query "SELECT agent_summary, exchange_count, summary_msg_count FROM sessions WHERE id LIKE '<short_id>%'"
   ```

2. Read messages:
   ```
   /query "SELECT role, substr(content,1,500) as content FROM messages WHERE session_id LIKE '<short_id>%' ORDER BY id" --json
   ```

3. Generate a 1-3 sentence summary from the messages. Focus on what was discussed and accomplished.

4. Store the summary:
   ```
   /query "UPDATE sessions SET agent_summary = '<summary>', summary_at = datetime('now'), summary_msg_count = (SELECT COUNT(*) FROM messages WHERE session_id LIKE '<short_id>%') WHERE id LIKE '<short_id>%'"
   ```

5. Report the summary to the user.
