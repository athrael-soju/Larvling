"""
Larvling Summarize — fetch conversation pairs and store session summaries.

Usage:
    python summarize.py --list                          # list sessions
    python summarize.py <session_id> --pairs            # all pairs as JSON
    python summarize.py <session_id> --get              # get existing session summary
    python summarize.py <session_id> --store "text"     # store/replace session summary

Terminology:
    - Session title:   first user prompt, auto-captured at SessionEnd (meta["summary"])
    - Session summary:  LLM-generated summary via /summarize (meta["llm_summary"])
"""

import json
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


def list_sessions():
    """Print available sessions with session summary status."""
    conn = get_db()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT session_id, timestamp, metadata
        FROM imprints
        WHERE event_type = 'session_end' AND metadata IS NOT NULL
        ORDER BY id DESC
        """
    ).fetchall()

    if not rows:
        rows = conn.execute(
            """
            SELECT DISTINCT session_id, MIN(timestamp) as timestamp
            FROM imprints
            WHERE session_id IS NOT NULL
            GROUP BY session_id
            ORDER BY timestamp DESC
            """
        ).fetchall()
        for row in rows:
            print(f"{row['session_id'][:8]}  {row['timestamp'] or '?'}  [no summary]")
        conn.close()
        return

    for row in rows:
        meta = {}
        try:
            meta = json.loads(row["metadata"])
        except (json.JSONDecodeError, TypeError):
            pass
        date = row["timestamp"][:16] if row["timestamp"] else "?"
        has_llm = "[summarized]" if meta.get("llm_summary") else "[no summary]"
        first_prompt = meta.get("summary", "")
        if first_prompt:
            first_prompt = first_prompt.split("\n")[0][:80]
        duration = meta.get("duration_min")
        dur = f" ({duration}m)" if duration else ""
        print(f"{row['session_id'][:8]}  {date}{dur}  {has_llm}  {first_prompt}")

    conn.close()


def get_pairs(session_id):
    """Fetch user/agent message pairs as a JSON list.

    Each pair is: {"index": N, "user": "...", "agent": "...", "timestamp": "..."}
    """
    conn = get_db()
    conn.row_factory = sqlite3.Row
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
    conn.row_factory = sqlite3.Row
    session_id = resolve_session(conn, session_id)
    if not session_id:
        conn.close()
        return None

    rows = conn.execute(
        """
        SELECT metadata FROM imprints
        WHERE session_id = ? AND event_type = 'session_end' AND metadata IS NOT NULL
        ORDER BY id DESC
        """,
        (session_id,),
    ).fetchall()
    conn.close()

    for row in rows:
        try:
            meta = json.loads(row["metadata"])
        except (json.JSONDecodeError, TypeError):
            continue
        if meta.get("llm_summary"):
            return meta["llm_summary"]

    return None


def store_summary(session_id, summary_text):
    """Store a session summary in the session_end metadata.

    Updates the most recent session_end row's metadata to include llm_summary.
    If no session_end row exists, creates one.
    """
    conn = get_db()
    conn.row_factory = sqlite3.Row
    session_id = resolve_session(conn, session_id)
    if not session_id:
        conn.close()
        print(f"No session found matching input", file=sys.stderr)
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
        meta = {}
        if row["metadata"]:
            try:
                meta = json.loads(row["metadata"])
            except (json.JSONDecodeError, TypeError):
                pass
        meta["llm_summary"] = summary_text
        conn.execute(
            "UPDATE imprints SET metadata = ? WHERE id = ?",
            (json.dumps(meta), row["id"]),
        )
        conn.commit()
    else:
        # No session_end row — create one
        from db import imprint
        imprint(conn, session_id, "session_end", "Session ended", {"llm_summary": summary_text})

    conn.close()
    print(f"Session summary stored for session {session_id[:8]}")


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(1)

    if sys.argv[1] == "--list":
        list_sessions()
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
