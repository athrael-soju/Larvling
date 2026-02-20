"""Larvling SessionEnd hook.

Finalizes session timing and records exchange count.
"""

import json
import os
import sys
import time

from db import (
    open_db,
    ensure_session,
    finalize_session,
    record_summary,
)


def handle_session_end(data):
    """Finalize session timing and record exchange count."""
    session_id = data.get("session_id")
    if not session_id:
        return

    with open_db() as conn:
        ensure_session(conn, session_id)
        finalize_session(conn, session_id)

        exchange_count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ? AND role = 'user'",
            (session_id,),
        ).fetchone()[0]

        record_summary(
            conn, session_id,
            exchange_count=exchange_count or None,
        )
        conn.commit()


def _log_error(msg):
    """Append an error to .claude/larvling-errors.log for debugging silent failures."""
    try:
        log_path = os.path.join(os.getcwd(), ".claude", "larvling-errors.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def main():
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

    handle_session_end(data)


if __name__ == "__main__":
    main()
