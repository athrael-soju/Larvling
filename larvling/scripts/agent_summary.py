"""Larvling Summary Agent.

Spawned as a background process on SessionEnd. Reads session messages
and generates a summary. Stores via query.py.
"""

import asyncio
import json
import os
import sys


async def main():
    try:
        from claude_code_sdk import (
            query, ClaudeCodeOptions,
            AssistantMessage, ResultMessage, TextBlock,
        )
    except ImportError:
        return  # SDK not installed — graceful degradation

    try:
        raw = sys.stdin.buffer.read().decode("utf-8")
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}

    session_id = data.get("session_id", "")
    if not session_id:
        return
    short_id = session_id[:8]
    cwd = data.get("cwd", os.getcwd())
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")

    prompt = f"""You are Larvling's summary agent. Generate a concise session summary.

## Step 1: Check if needed
Run: python "{plugin_root}/scripts/query.py" "SELECT agent_summary, exchange_count FROM sessions WHERE id LIKE '{short_id}%'"
If agent_summary already exists AND exchange_count < 10, exit (already summarized, short session).

## Step 2: Read messages
Run: python "{plugin_root}/scripts/query.py" "SELECT role, substr(content,1,500) as content FROM messages WHERE session_id LIKE '{short_id}%' ORDER BY id" --json

## Step 3: Generate and store summary
Write a 1-3 sentence summary capturing what was discussed and accomplished.
Run: python "{plugin_root}/scripts/query.py" "UPDATE sessions SET agent_summary = '<summary>', summary_at = datetime('now'), summary_msg_count = (SELECT COUNT(*) FROM messages WHERE session_id LIKE '{short_id}%') WHERE id LIKE '{short_id}%'"

## Step 4: Report
After completing (whether you stored a summary, skipped, or exited early), record a brief status message:
python "{plugin_root}/scripts/query.py" "INSERT INTO messages (session_id, role, content, metadata) VALUES ((SELECT id FROM sessions WHERE id LIKE '{short_id}%'), 'system', '<status>', '{{\\"source\\": \\"agent_summary\\"}}')"

Where <status> is a SHORT summary like:
- "Summary agent: generated summary (12 messages)"
- "Summary agent: already summarized, skipped"
- "Summary agent: updated stale summary (was 5 msgs, now 15)"

Then output that same status as your final message."""

    result_text = ""
    async for message in query(
        prompt=prompt,
        options=ClaudeCodeOptions(
            model="sonnet",
            cwd=cwd,
            permission_mode="bypassPermissions",
            max_turns=8,
        ),
    ):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    result_text = block.text.strip()
        elif isinstance(message, ResultMessage) and message.result:
            result_text = message.result.strip()

    if result_text:
        print(result_text)


if __name__ == "__main__":
    asyncio.run(main())
