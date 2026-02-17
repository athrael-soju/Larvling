"""Shared database helpers for Larvling hook scripts."""

import json
import os
import sqlite3
import sys

PROJECT_ROOT = os.getcwd()
DB_PATH = os.path.join(PROJECT_ROOT, ".claude", "larvling.db")


def get_db():
    """Open a connection to larvling.db with WAL mode and Row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def parse_meta(metadata_str):
    """Parse a metadata JSON string. Returns dict (empty on failure)."""
    if not metadata_str:
        return {}
    try:
        return json.loads(metadata_str)
    except (json.JSONDecodeError, TypeError):
        return {}


def reconfigure_stdout():
    """Reconfigure stdout for UTF-8 on Windows."""
    fn = getattr(sys.stdout, "reconfigure", None)
    if fn:
        fn(encoding="utf-8")


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


def get_session_duration(conn, session_id):
    """Calculate session duration from first to last imprint."""
    cur = conn.execute(
        """
        SELECT
            MIN(timestamp) as first_msg,
            MAX(timestamp) as last_msg,
            ROUND((julianday(MAX(timestamp)) - julianday(MIN(timestamp))) * 1440, 1) as duration_min
        FROM imprints
        WHERE session_id = ?
        """,
        (session_id,),
    )
    row = cur.fetchone()
    if row and row[2] is not None:
        return {"started_at": row[0], "ended_at": row[1], "duration_min": row[2]}
    return {}


def get_session_summary(conn, session_id):
    """Get the first user prompt as the session title."""
    row = conn.execute(
        "SELECT content FROM imprints WHERE session_id = ? AND event_type = 'user_message' ORDER BY id LIMIT 1",
        (session_id,),
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
        meta = parse_meta(row["metadata"])
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
