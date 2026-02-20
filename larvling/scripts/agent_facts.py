"""Larvling Fact Extraction Agent.

Spawned as a background subprocess on Stop. Reads the current exchange,
evaluates for fact-worthy content, stores/updates/deletes facts via query.py.
"""

import json
import os
import subprocess
import sys

from db import open_db
from transcript import parse_last_turn


def main():
    raw = sys.stdin.buffer.read().decode("utf-8")
    data = json.loads(raw) if raw.strip() else {}

    session_id = data.get("session_id", "")
    if not session_id:
        return
    short_id = session_id[:8]
    cwd = data.get("cwd", os.getcwd())
    transcript_path = data.get("transcript_path", "")
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")

    # Get the current exchange: last user message from DB + last agent response from transcript
    with open_db() as conn:
        user_row = conn.execute(
            "SELECT content FROM messages WHERE session_id = ? AND role = 'user' ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
    user_prompt = user_row["content"] if user_row else ""
    agent_response, _ = parse_last_turn(transcript_path)

    if not user_prompt and not agent_response:
        return

    prompt = f"""You are Larvling's fact agent. Review this exchange and manage the fact store.

## Exchange
**User:** {user_prompt[:2000]}
**Agent:** {(agent_response or '')[:2000]}

## Tasks
1. Query existing facts for anything relevant: python "{plugin_root}/scripts/query.py" "SELECT id, claim FROM facts LIMIT 20"
2. If the exchange reveals new facts worth storing (user preferences, decisions, patterns, conventions), INSERT them
3. If existing facts need updating based on this exchange, UPDATE them
4. If existing facts are contradicted by this exchange, DELETE them
5. If nothing noteworthy, do nothing — most exchanges have no fact-worthy content

Use python "{plugin_root}/scripts/query.py" for all SQL.
Fact ID convention: M-NNN (get next: SELECT id FROM facts WHERE id LIKE 'M-%' ORDER BY CAST(SUBSTR(id, 3) AS INTEGER) DESC LIMIT 1)
"""

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
