"""Larvling Fact Extraction Agent.

Spawned as a background process on Stop. Reads the conversation,
evaluates for fact-worthy content, stores facts via query.py.
Uses claude-code-sdk with CLI auth (no API key needed).
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
    transcript = data.get("transcript_path", "")
    cwd = data.get("cwd", os.getcwd())
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")

    prompt = f"""You are Larvling's fact-extraction agent. Review this conversation and store any facts worth remembering. Be selective — only store genuinely useful information.

## Step 1: Gate check
Run: python "{plugin_root}/scripts/query.py" "SELECT COUNT(*) FROM messages WHERE session_id LIKE '{short_id}%' AND role = 'user'"
If fewer than 6 user messages, exit immediately (not enough conversation to review).

Run: python "{plugin_root}/scripts/query.py" "SELECT COUNT(*) FROM facts WHERE source = 'session-{short_id}'"
If count > 0, exit immediately (already reviewed this session).

## Step 2: Read transcript
Read the file at: {transcript}
Look for: user preferences, technical decisions, project patterns, conventions, important context.

## Step 3: Store facts
Get next ID: python "{plugin_root}/scripts/query.py" "SELECT id FROM facts WHERE id LIKE 'M-%' ORDER BY CAST(SUBSTR(id, 3) AS INTEGER) DESC LIMIT 1"
Store each fact: python "{plugin_root}/scripts/query.py" "INSERT INTO facts (id, claim, domain, tags, source) VALUES ('M-NNN', 'the claim', 'domain', 'tags', 'session-{short_id}')"

If nothing is worth storing, that's fine.

## Step 4: Report
After completing (whether you stored facts, skipped, or exited early), record a brief status message:
python "{plugin_root}/scripts/query.py" "INSERT INTO messages (session_id, role, content, metadata) VALUES ((SELECT id FROM sessions WHERE id LIKE '{short_id}%'), 'system', '<status>', '{{\\"source\\": \\"agent_facts\\"}}')"

Where <status> is a SHORT summary like:
- "Fact agent: stored 2 facts (user prefers bun, project uses WAL mode)"
- "Fact agent: session too short, skipped"
- "Fact agent: already reviewed, skipped"
- "Fact agent: reviewed, nothing worth storing"

Then output that same status as your final message."""

    # Suppress Larvling hooks in the sub-agent's Claude Code process
    os.environ["LARVLING_AGENT"] = "1"

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
