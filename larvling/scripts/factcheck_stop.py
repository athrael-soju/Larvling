"""
Larvling Fact Check Stop Hook - enforces fact management.

Blocks the agent from stopping until it has queried the facts table
using query.py. Uses a marker file written by query.py to detect
that a facts query occurred.
"""

import json
import os
import sys
import time

from db import DB_PATH, open_db, reconfigure_stdout

MARKER_PATH = os.path.join(os.getcwd(), ".claude", "factcheck-marker")
MAX_MARKER_AGE = 120  # seconds


def _log_error(msg):
    """Append an error to .claude/larvling-errors.log."""
    try:
        log_path = os.path.join(os.getcwd(), ".claude", "larvling-errors.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] factcheck_stop: {msg}\n")
    except Exception:
        pass


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

    # Check for marker file written by query.py
    if os.path.exists(MARKER_PATH):
        try:
            with open(MARKER_PATH, "r", encoding="utf-8") as f:
                written_at = float(f.read().strip())
            if time.time() - written_at <= MAX_MARKER_AGE:
                os.remove(MARKER_PATH)
                return
        except Exception as e:
            _log_error(f"marker read failed: {e}")

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
