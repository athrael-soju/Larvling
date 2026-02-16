"""
Larvling Export — export a session's conversation to markdown.

Usage:
    python export.py <session_id>            # prints markdown to stdout
    python export.py <session_id> <outfile>  # writes to file
    python export.py --list                  # list available sessions
"""

import json
import os
import sqlite3
import sys

from db import DB_PATH, get_db


def list_sessions():
    """Print available sessions with summaries."""
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
        # Fall back to distinct session IDs if no session_end events yet
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
            print(f"{row['session_id'][:8]}  {row['timestamp'] or '?'}")
        conn.close()
        return

    for row in rows:
        meta = {}
        try:
            meta = json.loads(row["metadata"])
        except (json.JSONDecodeError, TypeError):
            pass
        date = row["timestamp"][:16] if row["timestamp"] else "?"
        summary = meta.get("summary", "")
        if summary:
            summary = summary.split("\n")[0][:100]
        duration = meta.get("duration_min")
        duration_str = f" ({duration}m)" if duration else ""
        print(f"{row['session_id'][:8]}  {date}{duration_str}  {summary}")

    conn.close()


def export_session(session_id):
    """Export a session to markdown. Returns the markdown string."""
    conn = get_db()
    conn.row_factory = sqlite3.Row

    # Resolve short IDs
    if len(session_id) < 36:
        row = conn.execute(
            "SELECT DISTINCT session_id FROM imprints WHERE session_id LIKE ?",
            (session_id + "%",),
        ).fetchone()
        if row:
            session_id = row["session_id"]
        else:
            conn.close()
            return None

    messages = conn.execute(
        """
        SELECT timestamp, event_type, content, metadata
        FROM imprints
        WHERE session_id = ?
        ORDER BY id
        """,
        (session_id,),
    ).fetchall()

    if not messages:
        conn.close()
        return None

    lines = [f"# Session {session_id[:8]}", ""]

    # Session metadata from session_end
    for msg in messages:
        if msg["event_type"] == "session_end" and msg["metadata"]:
            try:
                meta = json.loads(msg["metadata"])
            except (json.JSONDecodeError, TypeError):
                continue
            if meta.get("started_at"):
                lines.append(f"**Started:** {meta['started_at']}")
            if meta.get("ended_at"):
                lines.append(f"**Ended:** {meta['ended_at']}")
            if meta.get("duration_min"):
                lines.append(f"**Duration:** {meta['duration_min']} minutes")
            if meta.get("summary"):
                lines.append(f"**Summary:** {meta['summary']}")
            lines.append("")
            break

    lines.append("---")
    lines.append("")

    for msg in messages:
        ts = msg["timestamp"] or ""
        if msg["event_type"] == "user_message":
            lines.append(f"### You  `{ts}`")
            lines.append("")
            lines.append(msg["content"] or "")
            lines.append("")
        elif msg["event_type"] == "agent_message":
            tools_str = ""
            if msg["metadata"]:
                try:
                    meta = json.loads(msg["metadata"])
                    tools = meta.get("tool_calls", {})
                    if tools:
                        parts = [f"{name} ({count}x)" for name, count in tools.items()]
                        tools_str = f"  *Tools: {', '.join(parts)}*"
                except (json.JSONDecodeError, TypeError):
                    pass
            lines.append(f"### Agent  `{ts}`")
            if tools_str:
                lines.append(tools_str)
            lines.append("")
            lines.append(msg["content"] or "")
            lines.append("")

    conn.close()
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(1)

    if sys.argv[1] == "--list":
        list_sessions()
        return

    session_id = sys.argv[1]
    md = export_session(session_id)

    if md is None:
        print(f"No session found matching '{session_id}'", file=sys.stderr)
        sys.exit(1)

    if len(sys.argv) >= 3:
        outfile = sys.argv[2]
        os.makedirs(os.path.dirname(outfile) or ".", exist_ok=True)
        with open(outfile, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"Exported to {outfile}")
    else:
        print(md)


if __name__ == "__main__":
    main()
