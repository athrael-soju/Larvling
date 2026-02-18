"""
Larvling Delete - remove a session from the database.

Usage:
    python delete.py <session_id>    # delete a session (encounter + imprints + reflection)
    python delete.py --list          # list available sessions
    python delete.py --all           # delete all sessions (preserves memories)
"""

import sys

from db import get_db, resolve_session, print_sessions, reconfigure_stdout, require_db


def delete_session(session_id):
    """Delete all data for a session (encounter, imprints, reflection)."""
    conn = get_db()
    original = session_id
    session_id = resolve_session(conn, original)
    if not session_id:
        conn.close()
        print(f"No session found matching '{original}'", file=sys.stderr)
        sys.exit(1)

    imp_count = conn.execute(
        "SELECT COUNT(*) FROM imprints WHERE encounter_id = ?",
        (session_id,),
    ).fetchone()[0]

    # Delete in FK-safe order
    conn.execute("DELETE FROM reflections WHERE encounter_id = ?", (session_id,))
    conn.execute("DELETE FROM imprints WHERE encounter_id = ?", (session_id,))
    conn.execute("DELETE FROM encounters WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()
    print(f"Deleted session {session_id[:8]} ({imp_count} imprints)")


def delete_all():
    """Delete all sessions from the database. Preserves memories."""
    conn = get_db()
    enc_count = conn.execute("SELECT COUNT(*) FROM encounters").fetchone()[0]
    imp_count = conn.execute("SELECT COUNT(*) FROM imprints").fetchone()[0]

    if enc_count == 0:
        conn.close()
        print("No sessions to delete.")
        return

    # Delete in FK-safe order (NOT memories)
    conn.execute("DELETE FROM reflections")
    conn.execute("DELETE FROM imprints")
    conn.execute("DELETE FROM encounters")
    conn.commit()
    conn.close()
    print(f"Deleted {enc_count} sessions ({imp_count} imprints)")


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
