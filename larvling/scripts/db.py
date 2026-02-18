"""Shared database helpers for Larvling hook scripts.

Schema: sessions, messages, summaries, facts
"""

import json
import os
import sqlite3
import sys
from contextlib import contextmanager

PROJECT_ROOT = os.getcwd()
DB_PATH = os.path.join(PROJECT_ROOT, ".claude", "larvling.db")


def get_db():
    """Open a connection to larvling.db with WAL mode and Row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def open_db():
    """Context manager for database connections."""
    conn = get_db()
    try:
        yield conn
    finally:
        conn.close()


def parse_meta(metadata_str):
    """Parse a metadata JSON string. Returns dict (empty on failure)."""
    if not metadata_str:
        return {}
    try:
        return json.loads(metadata_str)
    except (json.JSONDecodeError, TypeError):
        return {}


def escape_like(query):
    """Escape special characters for SQL LIKE queries."""
    return query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def reconfigure_stdout():
    """Reconfigure stdout for UTF-8 on Windows."""
    fn = getattr(sys.stdout, "reconfigure", None)
    if fn:
        fn(encoding="utf-8")


def require_db():
    """Exit with an error if the database doesn't exist."""
    if not os.path.exists(DB_PATH):
        print("No database found at", DB_PATH, file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------


def create_schema(conn):
    """Create all tables and indexes (idempotent)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            duration_min REAL
        )
    """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            timestamp TEXT NOT NULL DEFAULT (datetime('now')),
            role TEXT NOT NULL,
            content TEXT,
            metadata TEXT
        )
    """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL UNIQUE REFERENCES sessions(id),
            timestamp TEXT NOT NULL DEFAULT (datetime('now')),
            title TEXT,
            agent_summary TEXT,
            exchange_count INTEGER
        )
    """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS facts (
            id TEXT PRIMARY KEY,
            claim TEXT NOT NULL,
            domain TEXT,
            tags TEXT,
            confidence TEXT DEFAULT 'observed',
            source TEXT,
            established TEXT NOT NULL DEFAULT (date('now')),
            confirmed TEXT,
            expires TEXT,
            notes TEXT
        )
    """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_summaries_session ON summaries(session_id)"
    )

    conn.commit()


# ---------------------------------------------------------------------------
# Schema detection and migration
# ---------------------------------------------------------------------------


def detect_schema_version(conn):
    """Detect which schema version is present.

    Returns:
        'current' - sessions table exists (current schema)
        'v2'      - encounters table exists (themed names)
        'v1'      - flat imprints table only (legacy)
        'fresh'   - no tables at all
    """
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "sessions" in tables:
        return "current"
    if "encounters" in tables:
        return "v2"
    if "imprints" in tables:
        return "v1"
    return "fresh"


def migrate_legacy(conn):
    """Migrate from v1 or v2 schema to current.

    v1 (flat imprints table): backup old table, create new schema, copy data.
    v2 (encounters/imprints/reflections/memories): rename tables and columns.
    """
    version = detect_schema_version(conn)

    if version == "current":
        return

    if version == "v1":
        conn.execute("ALTER TABLE imprints RENAME TO imprints_v1_backup")
        create_schema(conn)

        rows = conn.execute(
            "SELECT DISTINCT session_id FROM imprints_v1_backup"
        ).fetchall()
        for row in rows:
            sid = row[0]
            first_ts = conn.execute(
                "SELECT MIN(timestamp) FROM imprints_v1_backup WHERE session_id = ?",
                (sid,),
            ).fetchone()[0]
            conn.execute(
                "INSERT OR IGNORE INTO sessions (id, started_at) VALUES (?, ?)",
                (sid, first_ts or "unknown"),
            )
            conn.execute(
                "INSERT INTO messages (session_id, timestamp, role, content, metadata) "
                "SELECT session_id, timestamp, role, content, metadata "
                "FROM imprints_v1_backup WHERE session_id = ?",
                (sid,),
            )
            first_user = conn.execute(
                "SELECT content FROM imprints_v1_backup "
                "WHERE session_id = ? AND role = 'user' "
                "ORDER BY id ASC LIMIT 1",
                (sid,),
            ).fetchone()
            if first_user:
                conn.execute(
                    "INSERT OR IGNORE INTO summaries (session_id, title) VALUES (?, ?)",
                    (sid, first_user[0]),
                )
        conn.commit()
        return

    if version == "v2":
        conn.execute("ALTER TABLE encounters RENAME TO sessions")
        conn.execute("ALTER TABLE imprints RENAME TO messages")
        conn.execute("ALTER TABLE reflections RENAME TO summaries")
        conn.execute("ALTER TABLE memories RENAME TO facts")
        conn.execute("ALTER TABLE messages RENAME COLUMN encounter_id TO session_id")
        conn.execute("ALTER TABLE summaries RENAME COLUMN encounter_id TO session_id")

        conn.execute("DROP INDEX IF EXISTS idx_imprints_encounter")
        conn.execute("DROP INDEX IF EXISTS idx_reflections_encounter")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_summaries_session ON summaries(session_id)"
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Session / Message / Summary CRUD
# ---------------------------------------------------------------------------


def ensure_session(conn, session_id):
    """Create a session row if it doesn't exist yet."""
    conn.execute(
        "INSERT OR IGNORE INTO sessions (id, started_at) "
        "VALUES (?, datetime('now'))",
        (session_id,),
    )


def record_message(conn, session_id, role, content, metadata=None):
    """Record a conversation turn in the messages table."""
    conn.execute(
        "INSERT INTO messages (session_id, role, content, metadata) "
        "VALUES (?, ?, ?, ?)",
        (session_id, role, content, json.dumps(metadata) if metadata else None),
    )


def record_summary(
    conn, session_id, title=None, agent_summary=None, exchange_count=None
):
    """Insert or update a summary for a session.

    Only non-None values overwrite existing data (uses COALESCE).
    """
    conn.execute(
        """
        INSERT INTO summaries (session_id, title, agent_summary, exchange_count)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            title = COALESCE(excluded.title, summaries.title),
            agent_summary = COALESCE(excluded.agent_summary, summaries.agent_summary),
            exchange_count = COALESCE(excluded.exchange_count, summaries.exchange_count)
        """,
        (session_id, title, agent_summary, exchange_count),
    )


def finalize_session(conn, session_id):
    """Set ended_at and duration_min on a session."""
    conn.execute(
        """
        UPDATE sessions SET
            ended_at = datetime('now'),
            duration_min = ROUND(
                (julianday(datetime('now')) - julianday(started_at)) * 1440, 1
            )
        WHERE id = ?
        """,
        (session_id,),
    )


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def get_summary(conn, session_id):
    """Get the summary for a session. Returns Row or None."""
    return conn.execute(
        "SELECT * FROM summaries WHERE session_id = ?",
        (session_id,),
    ).fetchone()


def resolve_session(conn, short_id):
    """Resolve a short session ID to a full one."""
    if len(short_id) >= 36:
        return short_id
    row = conn.execute(
        "SELECT id FROM sessions WHERE id LIKE ?",
        (short_id + "%",),
    ).fetchone()
    return row[0] if row else None


def list_sessions(conn, show_summary_status=False):
    """List sessions with metadata. Prints formatted lines."""
    rows = conn.execute(
        """
        SELECT s.id, s.started_at, s.duration_min,
               u.title, u.agent_summary
        FROM sessions s
        LEFT JOIN summaries u ON u.session_id = s.id
        ORDER BY s.started_at DESC
        """
    ).fetchall()

    if not rows:
        print("No sessions found.")
        return

    for row in rows:
        short_id = row["id"][:8]
        date = (row["started_at"] or "?")[:16]
        duration = row["duration_min"]
        dur = f" ({duration}m)" if duration else ""
        title = row["title"] or ""
        if title:
            title = title.split("\n")[0][:100]

        if show_summary_status:
            tag = "  [summarized]" if row["agent_summary"] else "  [not summarized]"
            print(f"{short_id}  {date}{dur}{tag}  {title}")
        else:
            print(f"{short_id}  {date}{dur}  {title}")


def print_sessions(**kwargs):
    """Open DB, print session list, close. Passes kwargs to list_sessions."""
    conn = get_db()
    list_sessions(conn, **kwargs)
    conn.close()
