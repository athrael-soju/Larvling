"""
Larvling Preflight — SessionStart hook.
Creates imprints table on first run, then injects session context.
"""

import json
import os
import sqlite3
import sys

from db import DB_PATH


def ensure_audit_table():
    """Create the imprints table if the DB doesn't exist yet. Returns True if this was a fresh creation."""
    fresh = not os.path.exists(DB_PATH)
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS imprints (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT NOT NULL DEFAULT (datetime('now')),
            session_id  TEXT,
            event_type  TEXT NOT NULL,
            content     TEXT,
            metadata    TEXT
        )
    """
    )
    conn.commit()
    conn.close()
    return fresh


def get_recent_summaries(conn, limit=3):
    """Get summaries from the most recent sessions."""
    rows = conn.execute(
        """
        SELECT
            session_id,
            metadata,
            timestamp
        FROM imprints
        WHERE event_type = 'session_end' AND metadata IS NOT NULL
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    summaries = []
    for row in rows:
        try:
            meta = json.loads(row["metadata"])
        except (json.JSONDecodeError, TypeError):
            continue
        # Prefer session summary (LLM-generated) over session title (first prompt)
        summary = meta.get("llm_summary") or meta.get("summary")
        if not summary:
            continue
        date = row["timestamp"][:10] if row["timestamp"] else "?"
        duration = meta.get("duration_min")
        duration_str = f" ({duration}m)" if duration else ""
        summaries.append(f"- **{date}**{duration_str}: {summary}")
    return summaries


def detect_unfinished_work(conn):
    """Scan the last session for signs of unfinished work."""
    # Find the most recent session
    row = conn.execute(
        "SELECT session_id FROM imprints WHERE event_type = 'session_end' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not row:
        return []

    last_session = row["session_id"]
    messages = conn.execute(
        """
        SELECT content FROM imprints
        WHERE session_id = ? AND event_type = 'agent_message'
        ORDER BY id DESC LIMIT 3
        """,
        (last_session,),
    ).fetchall()

    signals = []
    patterns = [
        ("TODO", "TODO items mentioned"),
        ("FIXME", "FIXME items mentioned"),
        ("error", "errors encountered"),
        ("failed", "failures encountered"),
        ("not yet", "incomplete work noted"),
        ("still need", "outstanding tasks noted"),
        ("next step", "next steps outlined"),
    ]

    seen = set()
    for msg in messages:
        content = (msg["content"] or "").lower()
        for keyword, label in patterns:
            if keyword.lower() in content and label not in seen:
                signals.append(f"- {label}")
                seen.add(label)
    return signals


def get_session_context():
    """Build curated session context from summaries and unfinished work."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    lines = ["# Larvling Session Context", ""]

    # Recent session summaries
    summaries = get_recent_summaries(conn)
    if summaries:
        lines.append("## Recent Sessions")
        lines.extend(summaries)
        lines.append("")

    # Unfinished work from last session
    signals = detect_unfinished_work(conn)
    if signals:
        lines.append("## Unfinished Work (last session)")
        lines.extend(signals)
        lines.append("")

    # Fallback: if no summaries yet, show recent imprints so context isn't empty
    if not summaries:
        rows = conn.execute(
            "SELECT event_type, content FROM imprints ORDER BY id DESC LIMIT 5"
        ).fetchall()
        if rows:
            lines.append("## imprints ({})".format(
                conn.execute("SELECT COUNT(*) FROM imprints").fetchone()[0]
            ))
            for row in rows:
                content = (row["content"] or "")[:80]
                lines.append(f"- **{row['event_type']}:** {content}")
            lines.append("")

    conn.close()
    return "\n".join(lines)


def main():
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure:
        reconfigure(encoding="utf-8")

    fresh = ensure_audit_table()

    if fresh:
        print("# Larvling — First Run")
        print()
        print("Larvling has just been initialized for the first time in this project.")
        print("The database has been created at `.claude/larvling.db`.")
        print("A browsable dashboard is available at `.claude/dashboard.html`.")
        print()
        print("## What Larvling Does")
        print("- Automatically imprints every conversation (prompts, responses, session timing)")
        print("- Injects context from past sessions at the start of each new one")
        print("- Keeps a searchable HTML dashboard up to date after every hook")
        print()
        print("## Agent Instructions")
        print("Welcome the user warmly. Let them know Larvling is now installed and will")
        print("quietly track their sessions from here on — no extra effort needed. Point")
        print("them to the dashboard at `.claude/dashboard.html` for browsing past sessions.")
        print("Keep it short, friendly, and conversational. Don't overwhelm with details.")
    else:
        print(get_session_context())


if __name__ == "__main__":
    main()
