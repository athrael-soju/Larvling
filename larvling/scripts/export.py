"""
Larvling Export - export a session's conversation to markdown.

Usage:
    python export.py <session_id>            # prints markdown to stdout
    python export.py <session_id> <outfile>  # writes to file
    python export.py --list                  # list available sessions
    python export.py --all <outdir>          # export all sessions to a directory
"""

import os
import sys

from db import get_db, resolve_session, print_sessions, parse_meta, reconfigure_stdout


def export_session(session_id, conn=None):
    """Export a session to markdown. Returns the markdown string."""
    own_conn = conn is None
    if own_conn:
        conn = get_db()

    # Resolve short IDs
    session_id = resolve_session(conn, session_id)
    if not session_id:
        if own_conn:
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
        if own_conn:
            conn.close()
        return None

    lines = [f"# Session {session_id[:8]}", ""]

    # Session metadata from session_end
    for msg in messages:
        if msg["event_type"] == "session_end" and msg["metadata"]:
            meta = parse_meta(msg["metadata"])
            if not meta:
                continue
            if meta.get("started_at"):
                lines.append(f"**Started:** {meta['started_at']}")
            if meta.get("ended_at"):
                lines.append(f"**Ended:** {meta['ended_at']}")
            if meta.get("duration_min"):
                lines.append(f"**Duration:** {meta['duration_min']} minutes")
            if meta.get("summary"):
                lines.append(f"**Title:** {meta['summary']}")
            if meta.get("llm_summary"):
                lines.append(f"**Summary:** {meta['llm_summary']}")
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
            meta = parse_meta(msg["metadata"])
            tools = meta.get("tool_calls", {})
            if tools:
                parts = [f"{name} ({count}x)" for name, count in tools.items()]
                tools_str = f"  *Tools: {', '.join(parts)}*"
            lines.append(f"### Agent  `{ts}`")
            if tools_str:
                lines.append(tools_str)
            lines.append("")
            lines.append(msg["content"] or "")
            lines.append("")

    if own_conn:
        conn.close()
    return "\n".join(lines)


def export_all(outdir):
    """Export all sessions to individual markdown files in outdir."""
    conn = get_db()
    session_ids = [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT session_id FROM imprints WHERE session_id IS NOT NULL"
        ).fetchall()
    ]

    if not session_ids:
        conn.close()
        print("No sessions to export.", file=sys.stderr)
        sys.exit(1)

    os.makedirs(outdir, exist_ok=True)
    exported = 0
    for sid in session_ids:
        md = export_session(sid, conn)
        if md:
            outfile = os.path.join(outdir, f"{sid[:8]}.md")
            with open(outfile, "w", encoding="utf-8") as f:
                f.write(md)
            exported += 1

    conn.close()
    print(f"Exported {exported} sessions to {outdir}/")


def main():
    reconfigure_stdout()

    if len(sys.argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(1)

    if sys.argv[1] == "--list":
        print_sessions()
        return

    if sys.argv[1] == "--all":
        outdir = sys.argv[2] if len(sys.argv) >= 3 else ".claude/exports"
        export_all(outdir)
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
