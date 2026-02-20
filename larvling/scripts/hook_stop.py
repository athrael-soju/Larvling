"""Larvling Stop hook.

Logs the agent's last response.
"""

import json
import os
import sys

from db import (
    open_db,
    log_error,
    ensure_session,
    record_message,
    record_summary,
    finalize_session,
)
from transcript import parse_last_turn, wait_for_transcript_stable


def handle_session_end(data):
    """Finalize session timing and record exchange count."""
    if os.environ.get("LARVLING_AGENT"):
        return

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


def handle_stop(data):
    """Log the agent's last response from a Stop event."""
    if os.environ.get("LARVLING_AGENT"):
        return

    session_id = data.get("session_id")
    if not session_id:
        return

    transcript_path = data.get("transcript_path")

    wait_for_transcript_stable(transcript_path)

    response, tools = parse_last_turn(transcript_path)

    with open_db() as conn:
        ensure_session(conn, session_id)

        if response:
            meta = {"tool_calls": tools} if tools else None
            record_message(conn, session_id, "assistant", response, meta)

        conn.commit()


def main():
    try:
        raw = sys.stdin.buffer.read().decode("utf-8")
    except Exception as e:
        log_error(f"hook_stop stdin read failed: {e}")
        return

    if not raw.strip():
        return

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        log_error(f"hook_stop JSON parse failed ({len(raw)} bytes): {e}")
        return

    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "end":
        handle_session_end(data)
    else:
        handle_stop(data)


if __name__ == "__main__":
    main()
