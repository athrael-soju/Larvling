"""Larvling async fact extraction hook.

Invoked by Stop hook (async, 60s timeout). Reads stdin JSON,
reviews the last exchange, and spawns a subagent for fact management.
"""

import json
import os
import subprocess
import sys

from db import open_db
from transcript import parse_last_turn


def _spawn_agent(prompt, cwd=None, model="sonnet", max_turns=8):
    """Spawn a claude -p subagent and print its output."""
    env = os.environ.copy()
    env["LARVLING_AGENT"] = "1"
    result = subprocess.run(
        ["claude", "-p", prompt, "--model", model,
         "--dangerously-skip-permissions", "--max-turns", str(max_turns)],
        capture_output=True, text=True, env=env,
        cwd=cwd or os.getcwd(),
    )
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode != 0 and result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)


def _handle_facts(data):
    """Review the last exchange and manage the fact store."""
    session_id = data.get("session_id", "")
    if not session_id:
        return
    cwd = data.get("cwd", os.getcwd())
    transcript_path = data.get("transcript_path", "")

    with open_db() as conn:
        user_row = conn.execute(
            "SELECT content FROM messages WHERE session_id = ? AND role = 'user' ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
    user_prompt = user_row["content"] if user_row else ""
    agent_response, _ = parse_last_turn(transcript_path)

    if not user_prompt and not agent_response:
        return

    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    qpy = f'python "{plugin_root}/scripts/query.py"'

    prompt = f"""You are Larvling's fact agent. Review this exchange and manage the fact store.

## Exchange
**User:** {user_prompt}
**Agent:** {agent_response or ''}

## Tasks
1. Query existing facts for anything relevant: {qpy} "SELECT id, claim FROM facts LIMIT 20"
2. If the exchange reveals new facts worth storing (user preferences, decisions, patterns, conventions), INSERT them
3. If existing facts need updating based on this exchange, UPDATE them
4. If existing facts are contradicted by this exchange, DELETE them
5. If nothing noteworthy, do nothing — most exchanges have no fact-worthy content

Use {qpy} for all SQL.
Fact ID convention: M-NNN (get next: SELECT id FROM facts WHERE id LIKE 'M-%' ORDER BY CAST(SUBSTR(id, 3) AS INTEGER) DESC LIMIT 1)
"""
    _spawn_agent(prompt, cwd=cwd)


def main():
    raw = sys.stdin.buffer.read().decode("utf-8")
    data = json.loads(raw) if raw.strip() else {}
    _handle_facts(data)


if __name__ == "__main__":
    main()
