"""
Larvling Delete — remove a session's imprints from the database.

Usage:
    python delete.py <session_id>    # delete all imprints for a session
    python delete.py --list          # list available sessions
    python delete.py --all           # delete all sessions
"""

import sys

from db import get_db, resolve_session, print_sessions, reconfigure_stdout


def delete_session(session_id):
    """Delete all imprints for a session."""
    conn = get_db()
    original = session_id
    session_id = resolve_session(conn, original)
    if not session_id:
        conn.close()
        print(f"No session found matching '{original}'", file=sys.stderr)
        sys.exit(1)

    count = conn.execute(
        "SELECT COUNT(*) FROM imprints WHERE session_id = ?",
        (session_id,),
    ).fetchone()[0]

    conn.execute("DELETE FROM imprints WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()
    print(f"Deleted {count} imprints for session {session_id[:8]}")


def delete_all():
    """Delete all imprints from the database."""
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM imprints").fetchone()[0]
    sessions = conn.execute(
        "SELECT COUNT(DISTINCT session_id) FROM imprints"
    ).fetchone()[0]

    if count == 0:
        conn.close()
        print("No sessions to delete.")
        return

    conn.execute("DELETE FROM imprints")
    conn.commit()
    conn.close()
    print(f"Deleted {sessions} sessions ({count} imprints)")


def main():
    reconfigure_stdout()

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
