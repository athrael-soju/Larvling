"""Larvling Summary Agent.

Spawned as a background subprocess on SessionEnd. Reads session messages
and generates a summary. Stores via query.py.
"""

import json
import os
import subprocess
import sys

def main():
    raw = sys.stdin.buffer.read().decode("utf-8")
    data = json.loads(raw) if raw.strip() else {}

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

Output a brief status of what you did."""

    env = os.environ.copy()
    env["LARVLING_AGENT"] = "1"

    result = subprocess.run(
        ["claude", "-p", prompt, "--model", "sonnet",
         "--dangerously-skip-permissions", "--max-turns", "8"],
        capture_output=True, text=True, env=env, cwd=cwd,
    )
    if result.stdout.strip():
        print(result.stdout.strip())


if __name__ == "__main__":
    main()
