"""
Larvling Delete - remove a session from the database.

Usage:
    python delete.py <session_id>    # delete a session (session + messages + summary)
    python delete.py --list          # list available sessions
    python delete.py --all           # delete all sessions (preserves facts)
"""

import sys

from db import get_db, resolve_session, print_sessions, reconfigure_stdout, require_db


def delete_session(session_id):
    """Delete all data for a session (session, messages, summary)."""
    conn = get_db()
    original = session_id
    session_id = resolve_session(conn, original)
    if not session_id:
        conn.close()
        print(f"No session found matching '{original}'", file=sys.stderr)
        sys.exit(1)

    msg_count = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE session_id = ?",
        (session_id,),
    ).fetchone()[0]

    # Delete in FK-safe order
    conn.execute("DELETE FROM summaries WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()
    print(f"Deleted session {session_id[:8]} ({msg_count} messages)")


def delete_all():
    """Delete all sessions from the database. Preserves facts."""
    conn = get_db()
    sess_count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    msg_count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]

    if sess_count == 0:
        conn.close()
        print("No sessions to delete.")
        return

    # Delete in FK-safe order (NOT facts)
    conn.execute("DELETE FROM summaries")
    conn.execute("DELETE FROM messages")
    conn.execute("DELETE FROM sessions")
    conn.commit()
    conn.close()
    print(f"Deleted {sess_count} sessions ({msg_count} messages)")


def main():
    reconfigure_stdout()
    require_db()

    if len(sys.argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(1)

    if sys.argv[1] == "--list":
        print_sessions()
        return

    if sys.argv[1] == "--all":
        delete_all()
        return

    delete_session(sys.argv[1])


if __name__ == "__main__":
    main()
