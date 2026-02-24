"""SessionEnd hook — finalizes session timing and records exchange count."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db import (
    open_db,
    reconfigure_stdout,
    ensure_session,
    finalize_session,
    record_summary,
    log,
)


def handle(data):
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
            conn,
            session_id,
            exchange_count=exchange_count or None,
        )
        conn.commit()

        row = conn.execute(
            "SELECT duration_min FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        dur = f"{row['duration_min']:.1f}m" if row and row["duration_min"] else "?"
        log(f"SessionEnd: session={session_id[:8]}, exchanges={exchange_count}, duration={dur}")


if __name__ == "__main__":
    if os.environ.get("LARVLING_INTERNAL"):
        sys.exit(0)
    reconfigure_stdout()
    try:
        raw = sys.stdin.buffer.read().decode("utf-8")
    except Exception as e:
        log(f"stdin read failed: {e}")
        sys.exit(0)
    if not raw.strip():
        sys.exit(0)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        log(f"JSON parse failed ({len(raw)} bytes): {e}")
        sys.exit(0)
    handle(data)
