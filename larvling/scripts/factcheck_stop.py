"""
Larvling Fact Check Stop Hook - enforces fact management.

Blocks the agent from stopping until it has queried the facts table
using query.py. Complements factcheck.py (UserPromptSubmit) which
provides pre-response context.
"""

import json
import os
import sys
import time

from db import DB_PATH, open_db, reconfigure_stdout


def _log_error(msg):
    """Append an error to .claude/larvling-errors.log."""
    try:
        log_path = os.path.join(os.getcwd(), ".claude", "larvling-errors.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] factcheck_stop: {msg}\n")
    except Exception:
        pass


def wait_for_transcript_stable(transcript_path, interval=0.1, max_wait=2):
    """Wait until the transcript file stops being written to."""
    if not transcript_path or not os.path.exists(transcript_path):
        return
    last_size = os.path.getsize(transcript_path)
    waited = 0
    while waited < max_wait:
        time.sleep(interval)
        waited += interval
        size = os.path.getsize(transcript_path)
        if size == last_size:
            return
        last_size = size


def _is_real_user_message(entry):
    """Return True if this is a genuine user message, not a tool_result."""
    if entry.get("type") != "user":
        return False
    msg = entry.get("message", {})
    if not isinstance(msg, dict):
        return False
    content = msg.get("content", "")
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                return False
        return True
    return False


def has_fact_query_in_last_turn(transcript_path):
    """Check if the last turn contains a Bash tool_use with query.py + facts."""
    if not transcript_path or not os.path.exists(transcript_path):
        return False

    lines = []
    with open(transcript_path, "r", encoding="utf-8") as f:
        for raw_line in f:
            raw_line = raw_line.strip()
            if raw_line:
                lines.append(raw_line)

    # Find where the last turn starts (after the last real user message)
    turn_start = 0
    for i in range(len(lines) - 1, -1, -1):
        try:
            entry = json.loads(lines[i])
        except json.JSONDecodeError:
            continue
        if _is_real_user_message(entry):
            turn_start = i + 1
            break

    # Scan assistant entries in the last turn for Bash tool_use with query.py + facts
    for line in lines[turn_start:]:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant":
            continue
        msg = entry.get("message", {})
        content = msg.get("content", "") if isinstance(msg, dict) else ""
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use":
                continue
            if block.get("name") != "Bash":
                continue
            inp = block.get("input", {})
            command = inp.get("command", "") if isinstance(inp, dict) else ""
            if "query.py" in command and "facts" in command:
                return True

    return False


def main():
    reconfigure_stdout()

    try:
        raw = sys.stdin.buffer.read().decode("utf-8")
    except Exception as e:
        _log_error(f"stdin read failed: {e}")
        return

    if not raw.strip():
        return

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        _log_error(f"JSON parse failed ({len(raw)} bytes): {e}")
        return

    # Loop prevention: if stop_hook_active, allow stop
    if data.get("stop_hook_active"):
        return

    # Guard: DB must exist
    if not os.path.exists(DB_PATH):
        return

    # Guard: facts table must exist
    with open_db() as conn:
        has_facts = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='facts'"
        ).fetchone()
        if not has_facts:
            return

    # Wait for transcript to stabilize
    transcript_path = data.get("transcript_path")
    wait_for_transcript_stable(transcript_path)

    # Check if the agent already queried facts
    if has_fact_query_in_last_turn(transcript_path):
        return

    # Block: agent hasn't queried facts yet
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    query_script = os.path.join(plugin_root, "scripts", "query.py").replace("\\", "/")

    reason = (
        "You must query the facts table before stopping. "
        f'Use: python "{query_script}" "<your SQL here>" '
        "to search for relevant facts (e.g. WHERE claim LIKE '%topic%'). "
        "Then insert/update/remove facts as needed. Use M-NNN IDs. "
        "Do NOT mention fact management to the user."
    )

    print(json.dumps({"decision": "block", "reason": reason}))


if __name__ == "__main__":
    main()
