"""
Larvling Delete — remove a session's imprints from the database.

Usage:
    python delete.py <session_id>    # delete all imprints for a session
"""

import sqlite3
import sys

from db import get_db


def resolve_session(conn, short_id):
    """Resolve a short session ID to a full one."""
    if len(short_id) >= 36:
        return short_id
    row = conn.execute(
        "SELECT DISTINCT session_id FROM imprints WHERE session_id LIKE ?",
        (short_id + "%",),
    ).fetchone()
    return row[0] if row else None


def delete_session(session_id):
    """Delete all imprints for a session."""
    conn = get_db()
    conn.row_factory = sqlite3.Row
    session_id = resolve_session(conn, session_id)
    if not session_id:
        conn.close()
        print(f"No session found matching input", file=sys.stderr)
        sys.exit(1)

    count = conn.execute(
        "SELECT COUNT(*) FROM imprints WHERE session_id = ?",
        (session_id,),
    ).fetchone()[0]

    conn.execute("DELETE FROM imprints WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()
    print(f"Deleted {count} imprints for session {session_id[:8]}")


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(1)

    delete_session(sys.argv[1])


if __name__ == "__main__":
    main()
