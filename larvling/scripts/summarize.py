"""
Larvling Summarize — fetch conversation pairs and store session summaries.

Usage:
    python summarize.py --list                       # list sessions
    python summarize.py <session_id> --pairs         # all pairs as JSON
    python summarize.py <session_id> --get           # get existing session summary
    python summarize.py <session_id> --store "text"  # store/replace session summary

Terminology:
    - Session title:   first user prompt, auto-captured at SessionEnd (meta["summary"])
    - Session summary:  LLM-generated summary via /summarize (meta["llm_summary"])
"""

import json
import sys

from db import (
    get_db, get_session_end_meta, imprint, parse_meta, resolve_session,
    print_sessions, reconfigure_stdout,
    get_session_duration, get_session_summary,
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
        SELECT event_type, content, timestamp
        FROM imprints
        WHERE session_id = ? AND event_type IN ('user_message', 'agent_message')
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

        if rows[i]["event_type"] == "user_message":
            user_msg = rows[i]["content"]
            ts = rows[i]["timestamp"]
            i += 1
            if i < len(rows) and rows[i]["event_type"] == "agent_message":
                agent_msg = rows[i]["content"]
                i += 1
        else:
            # Orphan agent message
            agent_msg = rows[i]["content"]
            ts = rows[i]["timestamp"]
            i += 1

        pairs.append({
            "index": len(pairs) + 1,
            "user": user_msg or "",
            "agent": agent_msg or "",
            "timestamp": ts or "",
        })

    return pairs


def get_summary(session_id):
    """Get the existing session summary for a session, if any."""
    conn = get_db()
    session_id = resolve_session(conn, session_id)
    if not session_id:
        conn.close()
        return None

    meta = get_session_end_meta(conn, session_id)
    conn.close()
    return meta.get("llm_summary")


def store_summary(session_id, summary_text):
    """Store a session summary in the session_end metadata.

    Updates the most recent session_end row's metadata to include llm_summary.
    If no session_end row exists, creates one.
    """
    conn = get_db()
    session_id = resolve_session(conn, session_id)
    if not session_id:
        conn.close()
        print(f"No session found matching '{session_id}'", file=sys.stderr)
        sys.exit(1)

    # Find the best session_end row (prefer one with existing metadata)
    rows = conn.execute(
        """
        SELECT id, metadata FROM imprints
        WHERE session_id = ? AND event_type = 'session_end'
        ORDER BY id DESC
        """,
        (session_id,),
    ).fetchall()

    if rows:
        # Update existing session_end
        row = rows[0]
        meta = parse_meta(row["metadata"])
        meta["llm_summary"] = summary_text
        conn.execute(
            "UPDATE imprints SET metadata = ? WHERE id = ?",
            (json.dumps(meta), row["id"]),
        )
        conn.commit()
    else:
        # No session_end row — build full metadata before creating one
        meta = {"llm_summary": summary_text}
        meta.update(get_session_duration(conn, session_id))
        title = get_session_summary(conn, session_id)
        if title:
            meta["summary"] = title
        imprint(conn, session_id, "session_end", "Session ended", meta)

    conn.close()
    print(f"Session summary stored for session {session_id[:8]}")


def main():
    reconfigure_stdout()

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
        summary = get_summary(session_id)
        if summary:
            print(summary)
        else:
            print(f"No session summary found for session matching '{session_id}'", file=sys.stderr)
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
