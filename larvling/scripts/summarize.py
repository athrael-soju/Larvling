"""
Larvling Summarize - manage session summaries.

Usage:
    python summarize.py --list                       # list sessions
    python summarize.py <session_id> --get           # get existing session summary
    python summarize.py <session_id> --store "text"  # store/replace session summary
"""

import sys
import time

from db import (
    get_summary,
    open_db,
    record_summary,
    require_db,
    resolve_session,
    print_sessions,
    reconfigure_stdout,
)


def get_existing_summary(session_id):
    """Get the existing session summary for a session, if any."""
    with open_db() as conn:
        session_id = resolve_session(conn, session_id)
        if not session_id:
            return None

        ref = get_summary(conn, session_id)
        return ref["agent_summary"] if ref else None


def store_summary(session_id, summary_text):
    """Store a session summary in the sessions table. Returns session_id or None."""
    with open_db() as conn:
        original = session_id
        session_id = resolve_session(conn, original)
        if not session_id:
            return None

        msg_count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ? AND role IN ('user', 'assistant')",
            (session_id,),
        ).fetchone()[0]

        record_summary(
            conn,
            session_id,
            agent_summary=summary_text,
            summary_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            summary_msg_count=msg_count,
        )
        conn.commit()
    print(f"Session summary stored for session {session_id[:8]} ({msg_count} messages)")
    return session_id


def main():
    reconfigure_stdout()
    require_db()

    if len(sys.argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(1)

    if sys.argv[1] == "--list":
        print_sessions(show_summary_status=True)
        return

    session_id = sys.argv[1]

    if "--get" in sys.argv:
        summary = get_existing_summary(session_id)
        if summary:
            print(summary)
        else:
            print(f"No session summary found for session matching '{session_id}'")

    elif "--store" in sys.argv:
        idx = sys.argv.index("--store")
        if idx + 1 < len(sys.argv):
            result = store_summary(session_id, sys.argv[idx + 1])
            if result is None:
                print(f"No session found matching '{session_id}'", file=sys.stderr)
                sys.exit(1)
        else:
            print("Missing summary text after --store", file=sys.stderr)
            sys.exit(1)

    else:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
