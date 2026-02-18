"""Shared database helpers for Larvling hook scripts.

v2 schema: encounters, imprints, reflections, memories
Migration from v1 (single imprints table) is handled transparently.
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
# Schema detection & creation
# ---------------------------------------------------------------------------


def detect_schema_version(conn):
    """Detect which schema version is present.

    Returns: 'v2' if encounters table exists,
             'v1' if imprints exists without encounters,
             'fresh' if neither exists.
    """
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "encounters" in tables:
        return "v2"
    if "imprints" in tables:
        return "v1"
    return "fresh"


def create_v2_schema(conn):
    """Create all v2 tables and indexes (idempotent)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS encounters (
            id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            duration_min REAL
        )
    """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS imprints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            encounter_id TEXT NOT NULL REFERENCES encounters(id),
            timestamp TEXT NOT NULL DEFAULT (datetime('now')),
            role TEXT NOT NULL,
            content TEXT,
            metadata TEXT
        )
    """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reflections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            encounter_id TEXT NOT NULL UNIQUE REFERENCES encounters(id),
            timestamp TEXT NOT NULL DEFAULT (datetime('now')),
            title TEXT,
            agent_summary TEXT,
            exchange_count INTEGER
        )
    """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memories (
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
    # Indexes may fail if a v1 imprints table already exists (no encounter_id column).
    # This is safe — indexes only matter for v2 tables.
    for idx_sql in (
        "CREATE INDEX IF NOT EXISTS idx_imprints_encounter ON imprints(encounter_id)",
        "CREATE INDEX IF NOT EXISTS idx_reflections_encounter ON reflections(encounter_id)",
    ):
        try:
            conn.execute(idx_sql)
        except sqlite3.OperationalError:
            pass

    conn.commit()


def migrate_v1_to_v2(conn):
    """Migrate from v1 (single imprints table) to v2 (normalized schema).

    1. Rename imprints -> imprints_v1_backup
    2. Create v2 tables
    3. Migrate data
    4. Verify counts

    On failure, restores the original imprints table.
    """
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "imprints_v1_backup" in tables and "encounters" in tables:
        return  # Already migrated

    print("Larvling: migrating database from v1 to v2...", file=sys.stderr)

    try:
        # 1. Rename
        conn.execute("ALTER TABLE imprints RENAME TO imprints_v1_backup")

        # 2. Create v2 tables
        create_v2_schema(conn)

        # 3. Migrate data
        sessions = conn.execute(
            "SELECT DISTINCT session_id FROM imprints_v1_backup "
            "WHERE session_id IS NOT NULL"
        ).fetchall()

        for row in sessions:
            sid = row[0]

            # Timestamps for encounter
            ts = conn.execute(
                "SELECT MIN(timestamp) AS first_ts, MAX(timestamp) AS last_ts "
                "FROM imprints_v1_backup WHERE session_id = ?",
                (sid,),
            ).fetchone()

            # session_end metadata for better timestamps
            end_row = conn.execute(
                "SELECT metadata FROM imprints_v1_backup "
                "WHERE session_id = ? AND event_type = 'session_end' "
                "AND metadata IS NOT NULL ORDER BY id DESC LIMIT 1",
                (sid,),
            ).fetchone()

            started_at = ts["first_ts"]
            ended_at = ts["last_ts"]
            duration_min = None

            end_meta = {}
            if end_row:
                end_meta = parse_meta(end_row["metadata"])
                if end_meta.get("started_at"):
                    started_at = end_meta["started_at"]
                if end_meta.get("ended_at"):
                    ended_at = end_meta["ended_at"]
                if end_meta.get("duration_min") is not None:
                    duration_min = end_meta["duration_min"]

            # Insert encounter
            conn.execute(
                "INSERT INTO encounters (id, started_at, ended_at, duration_min) "
                "VALUES (?, ?, ?, ?)",
                (sid, started_at, ended_at, duration_min),
            )

            # Migrate messages
            messages = conn.execute(
                "SELECT timestamp, event_type, content, metadata "
                "FROM imprints_v1_backup "
                "WHERE session_id = ? AND event_type IN ('user_message', 'agent_message') "
                "ORDER BY id",
                (sid,),
            ).fetchall()

            for msg in messages:
                role = "user" if msg["event_type"] == "user_message" else "assistant"
                conn.execute(
                    "INSERT INTO imprints (encounter_id, timestamp, role, content, metadata) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (sid, msg["timestamp"], role, msg["content"], msg["metadata"]),
                )

            # Migrate session_end -> reflection
            if end_meta:
                title = end_meta.get("summary")
                agent_summary = end_meta.get("llm_summary")
                user_count = sum(
                    1 for m in messages if m["event_type"] == "user_message"
                )
                conn.execute(
                    "INSERT INTO reflections "
                    "(encounter_id, title, agent_summary, exchange_count) "
                    "VALUES (?, ?, ?, ?)",
                    (sid, title, agent_summary, user_count or None),
                )

        conn.commit()

        # 4. Verify
        v1_msg_count = conn.execute(
            "SELECT COUNT(*) FROM imprints_v1_backup "
            "WHERE event_type IN ('user_message', 'agent_message') "
            "AND session_id IS NOT NULL"
        ).fetchone()[0]
        v2_msg_count = conn.execute("SELECT COUNT(*) FROM imprints").fetchone()[0]
        enc_count = conn.execute("SELECT COUNT(*) FROM encounters").fetchone()[0]
        ref_count = conn.execute("SELECT COUNT(*) FROM reflections").fetchone()[0]

        print(
            f"Larvling: migration complete. "
            f"{enc_count} encounters, {v2_msg_count} imprints, {ref_count} reflections. "
            f"Backup preserved in imprints_v1_backup.",
            file=sys.stderr,
        )

    except Exception as e:
        conn.rollback()
        try:
            for table in ("reflections", "imprints", "encounters", "memories"):
                conn.execute(f"DROP TABLE IF EXISTS {table}")
            tables_now = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "imprints_v1_backup" in tables_now and "imprints" not in tables_now:
                conn.execute("ALTER TABLE imprints_v1_backup RENAME TO imprints")
            conn.commit()
        except Exception:
            pass
        print(
            f"Larvling: migration failed: {e}. Continuing with v1 schema.",
            file=sys.stderr,
        )
        raise


# ---------------------------------------------------------------------------
# Encounter / Imprint / Reflection CRUD
# ---------------------------------------------------------------------------


def ensure_encounter(conn, encounter_id):
    """Create an encounter row if it doesn't exist yet."""
    conn.execute(
        "INSERT OR IGNORE INTO encounters (id, started_at) "
        "VALUES (?, datetime('now'))",
        (encounter_id,),
    )


def record_imprint(conn, encounter_id, role, content, metadata=None):
    """Record a conversation turn in the imprints table."""
    conn.execute(
        "INSERT INTO imprints (encounter_id, role, content, metadata) "
        "VALUES (?, ?, ?, ?)",
        (encounter_id, role, content, json.dumps(metadata) if metadata else None),
    )


def record_reflection(
    conn, encounter_id, title=None, agent_summary=None, exchange_count=None
):
    """Insert or update a reflection for an encounter.

    Only non-None values overwrite existing data (uses COALESCE).
    """
    conn.execute(
        """
        INSERT INTO reflections (encounter_id, title, agent_summary, exchange_count)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(encounter_id) DO UPDATE SET
            title = COALESCE(excluded.title, reflections.title),
            agent_summary = COALESCE(excluded.agent_summary, reflections.agent_summary),
            exchange_count = COALESCE(excluded.exchange_count, reflections.exchange_count)
        """,
        (encounter_id, title, agent_summary, exchange_count),
    )


def finalize_encounter(conn, encounter_id):
    """Set ended_at and duration_min on an encounter."""
    conn.execute(
        """
        UPDATE encounters SET
            ended_at = datetime('now'),
            duration_min = ROUND(
                (julianday(datetime('now')) - julianday(started_at)) * 1440, 1
            )
        WHERE id = ?
        """,
        (encounter_id,),
    )


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def get_reflection(conn, encounter_id):
    """Get the reflection for an encounter. Returns Row or None."""
    return conn.execute(
        "SELECT * FROM reflections WHERE encounter_id = ?",
        (encounter_id,),
    ).fetchone()


def resolve_session(conn, short_id):
    """Resolve a short session/encounter ID to a full one."""
    if len(short_id) >= 36:
        return short_id
    row = conn.execute(
        "SELECT id FROM encounters WHERE id LIKE ?",
        (short_id + "%",),
    ).fetchone()
    return row[0] if row else None


def list_sessions(conn, show_summary_status=False):
    """List sessions with metadata. Prints formatted lines."""
    rows = conn.execute(
        """
        SELECT e.id, e.started_at, e.duration_min,
               r.title, r.agent_summary
        FROM encounters e
        LEFT JOIN reflections r ON r.encounter_id = e.id
        ORDER BY e.started_at DESC
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
