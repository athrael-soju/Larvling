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

from db import open_db, resolve_session, print_sessions, parse_meta, reconfigure_stdout, require_db


def _render_session(session_id, conn):
    """Render a session to markdown using an existing connection."""
    session_id = resolve_session(conn, session_id)
    if not session_id:
        return None

    sess = conn.execute(
        "SELECT * FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()

    messages = conn.execute(
        """
        SELECT timestamp, role, content, metadata
        FROM messages
        WHERE session_id = ?
        ORDER BY id ASC
        """,
        (session_id,),
    ).fetchall()

    if not messages:
        return None

    lines = [f"# Session {session_id[:8]}", ""]

    if sess:
        if sess["started_at"]:
            lines.append(f"**Started:** {sess['started_at']}")
        if sess["ended_at"]:
            lines.append(f"**Ended:** {sess['ended_at']}")
        if sess["duration_min"]:
            lines.append(f"**Duration:** {sess['duration_min']} minutes")
        if sess["title"]:
            lines.append(f"**Title:** {sess['title']}")
        if sess["agent_summary"]:
            lines.append(f"**Summary:** {sess['agent_summary']}")
        lines.append("")

    lines.append("---")
    lines.append("")

    for msg in messages:
        ts = msg["timestamp"] or ""
        if msg["role"] == "user":
            lines.append(f"### You  `{ts}`")
            lines.append("")
            lines.append(msg["content"] or "")
            lines.append("")
        elif msg["role"] == "assistant":
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

    return "\n".join(lines)


def export_session(session_id, conn=None):
    """Export a session to markdown. Returns the markdown string."""
    if conn is not None:
        return _render_session(session_id, conn)
    with open_db() as conn:
        return _render_session(session_id, conn)


def export_all(outdir):
    """Export all sessions to individual markdown files in outdir."""
    with open_db() as conn:
        session_ids = [
            row[0]
            for row in conn.execute("SELECT id FROM sessions").fetchall()
        ]

        if not session_ids:
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

    print(f"Exported {exported} sessions to {outdir}/")


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
