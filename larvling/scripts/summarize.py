"""
Larvling Summarize - fetch conversation pairs and store session summaries.

Usage:
    python summarize.py --list                       # list sessions
    python summarize.py <session_id> --pairs         # all pairs as JSON
    python summarize.py <session_id> --get           # get existing session summary
    python summarize.py <session_id> --store "text"  # store/replace session summary

Terminology:
    - Session title:   first user prompt, auto-captured at UserPromptSubmit (summaries.title)
    - Session summary:  Agent-generated summary via /summarize (summaries.agent_summary)
"""

import json
import sys

from db import (
    get_db,
    get_summary,
    record_summary,
    require_db,
    resolve_session,
    print_sessions,
    reconfigure_stdout,
)


def get_pairs(session_id):
    """Fetch user/agent message pairs as a JSON list.

    Each pair is: {"index": N, "user": "...", "agent": "...", "timestamp": "..."}
    """
    conn = get_db()
    session_id = resolve_session(conn, session_id)
    if not session_id:
        conn.close()
        return None

    rows = conn.execute(
        """
        SELECT role, content, timestamp
        FROM messages
        WHERE session_id = ? AND role IN ('user', 'assistant')
        ORDER BY id
        """,
        (session_id,),
    ).fetchall()
    conn.close()

    # Pair up user/agent messages
    pairs = []
    i = 0
    while i < len(rows):
        user_msg = None
        agent_msg = None
        ts = None

        if rows[i]["role"] == "user":
            user_msg = rows[i]["content"]
            ts = rows[i]["timestamp"]
            i += 1
            if i < len(rows) and rows[i]["role"] == "assistant":
                agent_msg = rows[i]["content"]
                i += 1
        else:
            # Orphan assistant message
            agent_msg = rows[i]["content"]
            ts = rows[i]["timestamp"]
            i += 1

        pairs.append(
            {
                "index": len(pairs) + 1,
                "user": user_msg or "",
                "agent": agent_msg or "",
                "timestamp": ts or "",
            }
        )

    return pairs


def get_existing_summary(session_id):
    """Get the existing session summary for a session, if any."""
    conn = get_db()
    session_id = resolve_session(conn, session_id)
    if not session_id:
        conn.close()
        return None

    ref = get_summary(conn, session_id)
    conn.close()
    return ref["agent_summary"] if ref else None


def store_summary(session_id, summary_text):
    """Store a session summary in the summaries table."""
    conn = get_db()
    original = session_id
    session_id = resolve_session(conn, original)
    if not session_id:
        conn.close()
        print(f"No session found matching '{original}'", file=sys.stderr)
        sys.exit(1)

    record_summary(conn, session_id, agent_summary=summary_text)
    conn.commit()
    conn.close()
    print(f"Session summary stored for session {session_id[:8]}")


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

    if "--pairs" in sys.argv:
        pairs = get_pairs(session_id)
        if pairs is None:
            print(f"No session found matching '{session_id}'", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(pairs, indent=2))

    elif "--get" in sys.argv:
        summary = get_existing_summary(session_id)
        if summary:
            print(summary)
        else:
            print(
                f"No session summary found for session matching '{session_id}'",
                file=sys.stderr,
            )
            sys.exit(1)

    elif "--store" in sys.argv:
        idx = sys.argv.index("--store")
        if idx + 1 < len(sys.argv):
            store_summary(session_id, sys.argv[idx + 1])
        else:
            print("Missing summary text after --store", file=sys.stderr)
            sys.exit(1)

    else:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
