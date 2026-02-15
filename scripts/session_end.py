"""
Larvling Session End — captures session summary and duration.

Hook event: SessionEnd
Logs a session_end audit event with metadata:
  - duration_min: session length in minutes
"""

import json
import sys

from db import get_db, log_audit


def get_session_duration(conn, session_id):
    """Calculate session duration from first to last audit entry."""
    cur = conn.execute(
        """
        SELECT
            MIN(timestamp) as first_msg,
            MAX(timestamp) as last_msg,
            ROUND((julianday(MAX(timestamp)) - julianday(MIN(timestamp))) * 1440, 1) as duration_min
        FROM audit
        WHERE session_id = ?
        """,
        (session_id,),
    )
    row = cur.fetchone()
    if row and row[2] is not None:
        return {"started_at": row[0], "ended_at": row[1], "duration_min": row[2]}
    return {}


def main():
    raw = sys.stdin.read()
    if not raw.strip():
        return

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print("Failed to parse hook input", file=sys.stderr)
        return

    session_id = data.get("session_id")
    if not session_id:
        return

    conn = get_db()

    meta = {}
    meta.update(get_session_duration(conn, session_id))

    log_audit(conn, session_id, "session_end", "Session ended", meta)
    conn.close()


if __name__ == "__main__":
    main()
