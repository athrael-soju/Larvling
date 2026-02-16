"""Shared database helpers for Larvling hook scripts."""

import json
import os
import sqlite3

PROJECT_ROOT = os.getcwd()
DB_PATH = os.path.join(PROJECT_ROOT, ".claude", "larvling.db")


def get_db():
    """Open a connection to larvling.db with WAL mode."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def imprint(conn, session_id, event_type, content, metadata=None):
    """Record an imprint and commit."""
    conn.execute(
        "INSERT INTO imprints (session_id, event_type, content, metadata) VALUES (?, ?, ?, ?)",
        (session_id, event_type, content, json.dumps(metadata) if metadata else None),
    )
    conn.commit()


def resolve_session(conn, short_id):
    """Resolve a short session ID to a full one."""
    if len(short_id) >= 36:
        return short_id
    row = conn.execute(
        "SELECT DISTINCT session_id FROM imprints WHERE session_id LIKE ?",
        (short_id + "%",),
    ).fetchone()
    return row[0] if row else None


def list_sessions(conn, show_summary_status=False):
    """List sessions with metadata. Returns formatted lines.

    If show_summary_status is True, includes [summarized]/[not summarized] tags.
    """
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
            tag = "  [no summary]" if show_summary_status else ""
            print(f"{row['session_id'][:8]}  {row['timestamp'] or '?'}{tag}")
        return

    for row in rows:
        meta = {}
        try:
            meta = json.loads(row["metadata"])
        except (json.JSONDecodeError, TypeError):
            pass
        date = row["timestamp"][:16] if row["timestamp"] else "?"
        duration = meta.get("duration_min")
        dur = f" ({duration}m)" if duration else ""
        first_prompt = meta.get("summary", "")
        if first_prompt:
            first_prompt = first_prompt.split("\n")[0][:100]

        if show_summary_status:
            tag = "  [summarized]" if meta.get("llm_summary") else "  [not summarized]"
            print(f"{row['session_id'][:8]}  {date}{dur}{tag}  {first_prompt}")
        else:
            print(f"{row['session_id'][:8]}  {date}{dur}  {first_prompt}")
