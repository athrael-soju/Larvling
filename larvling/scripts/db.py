"""Shared database helpers for Larvling hook scripts.

Schema: sessions, messages, facts
"""

import json
import os
import sqlite3
import sys
import time
from contextlib import contextmanager

PROJECT_ROOT = os.getcwd()
DB_PATH = os.path.join(PROJECT_ROOT, ".claude", "larvling.db")


def get_plugin_version():
    """Read the plugin version from plugin.json. Returns '?' on failure."""
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    plugin_json = os.path.join(plugin_root, ".claude-plugin", "plugin.json")
    try:
        with open(plugin_json, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("version", "?") if isinstance(data, dict) else "?"
    except Exception:
        return "?"


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


def has_table(conn, name):
    """Check if a table exists in the database."""
    return conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


# ---------------------------------------------------------------------------
# Schema creation and versioning
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 8


def get_schema_version(conn):
    """Read the current schema version from the database."""
    return conn.execute("PRAGMA user_version").fetchone()[0]


def set_schema_version(conn, version=SCHEMA_VERSION):
    """Set the schema version in the database."""
    conn.execute(f"PRAGMA user_version = {int(version)}")


def get_current_schema(conn):
    """Read the live schema from sqlite_master."""
    rows = conn.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type IN ('table', 'index') AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return "\n".join(row[0] + ";" for row in rows if row[0])


def get_desired_schema():
    """Get the desired schema by creating it in an in-memory database."""
    mem = sqlite3.connect(":memory:")
    mem.row_factory = sqlite3.Row
    create_schema(mem)
    schema = get_current_schema(mem)
    mem.close()
    return schema


def create_schema(conn):
    """Create all tables and indexes (idempotent)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            duration_min REAL,
            title TEXT,
            agent_summary TEXT,
            exchange_count INTEGER,
            summary_at TEXT,
            summary_msg_count INTEGER,
            topics TEXT,
            quality_signals TEXT
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
        CREATE TABLE IF NOT EXISTS facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim TEXT NOT NULL,
            domain TEXT NOT NULL,
            tags TEXT NOT NULL,
            created TEXT NOT NULL DEFAULT (date('now')),
            updated TEXT
        )
    """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)"
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Session / Message / Summary CRUD
# ---------------------------------------------------------------------------


def ensure_session(conn, session_id):
    """Create or touch a session row.

    On first call creates the session. On subsequent calls (e.g. resume)
    updates ended_at so the session sorts to the top in the dashboard.
    """
    conn.execute(
        "INSERT INTO sessions (id, started_at) "
        "VALUES (?, datetime('now')) "
        "ON CONFLICT(id) DO UPDATE SET ended_at = datetime('now')",
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
    conn,
    session_id,
    title=None,
    agent_summary=None,
    exchange_count=None,
    summary_at=None,
    summary_msg_count=None,
):
    """Update summary fields on a session row.

    Only non-None values overwrite existing data (uses COALESCE).
    """
    conn.execute(
        """
        UPDATE sessions SET
            title = COALESCE(?, title),
            agent_summary = COALESCE(?, agent_summary),
            exchange_count = COALESCE(?, exchange_count),
            summary_at = COALESCE(?, summary_at),
            summary_msg_count = COALESCE(?, summary_msg_count)
        WHERE id = ?
        """,
        (title, agent_summary, exchange_count, summary_at, summary_msg_count, session_id),
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
    """Get the session row (which includes summary fields). Returns Row or None."""
    return conn.execute(
        "SELECT * FROM sessions WHERE id = ?",
        (session_id,),
    ).fetchone()


def resolve_session(conn, short_id):
    """Resolve a short session ID to a full one."""
    if len(short_id) >= 36:
        return short_id
    row = conn.execute(
        "SELECT id FROM sessions WHERE id LIKE ? ESCAPE '\\'",
        (escape_like(short_id) + "%",),
    ).fetchone()
    return row[0] if row else None


def list_sessions(conn, show_summary_status=False):
    """List sessions with metadata. Prints formatted lines."""
    query = """
        SELECT s.id, s.started_at, s.duration_min, s.title,
               s.agent_summary, s.summary_msg_count,
               (SELECT COUNT(*) FROM messages m
                WHERE m.session_id = s.id
                AND m.role IN ('user', 'assistant')) AS current_msg_count
        FROM sessions s
        ORDER BY s.started_at DESC
    """ if show_summary_status else """
        SELECT id, started_at, duration_min, title, agent_summary
        FROM sessions
        ORDER BY started_at DESC
    """
    rows = conn.execute(query).fetchall()

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
            if row["agent_summary"]:
                summarized = row["summary_msg_count"] or 0
                current = row["current_msg_count"] or 0
                tag = f"  [summarized {summarized}/{current} msgs]"
            else:
                tag = "  [not summarized]"
            print(f"{short_id}  {date}{dur}{tag}  {title}")
        else:
            print(f"{short_id}  {date}{dur}  {title}")


def print_sessions(**kwargs):
    """Open DB, print session list, close. Passes kwargs to list_sessions."""
    with open_db() as conn:
        list_sessions(conn, **kwargs)


def build_message_pairs(rows):
    """Build user/agent pairs from ordered message rows, skipping orphans.

    Each pair: {"user": str, "agent": str, "timestamp": str or None}
    Works with rows that include or omit the timestamp column.
    """
    pairs = []
    i = 0
    while i < len(rows):
        if rows[i]["role"] == "user":
            user_msg = rows[i]["content"] or ""
            try:
                ts = rows[i]["timestamp"]
            except (IndexError, KeyError):
                ts = None
            i += 1
            agent_msg = ""
            if i < len(rows) and rows[i]["role"] == "assistant":
                agent_msg = rows[i]["content"] or ""
                i += 1
            pairs.append({"user": user_msg, "agent": agent_msg, "timestamp": ts})
        else:
            # Orphan assistant message — skip
            i += 1
    return pairs


async def call_model(prompt, allowed_tools=None, max_turns=None, output_format=None):
    """Call the LLM via Agent SDK and return the response.

    Returns structured_output (dict) when output_format is set,
    otherwise returns response text (str).
    Sets LARVLING_INTERNAL to prevent sub-agent from triggering hooks.
    """
    from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage
    from claude_agent_sdk._internal.message_parser import parse_message  # noqa: PLC2701
    from claude_agent_sdk._errors import MessageParseError  # noqa: PLC2701
    import claude_agent_sdk._internal.client as _sdk_client  # noqa: PLC2701

    # Patch parse_message to skip unknown message types instead of crashing.
    # The SDK (as of 0.1.39) doesn't handle rate_limit_event and other CLI
    # message types, which kills the async generator mid-stream and loses
    # all subsequent messages including the ResultMessage with structured_output.
    # Note: not concurrent-safe — callers use asyncio.run() (one loop at a time).
    def _tolerant_parse(data):
        try:
            return parse_message(data)
        except MessageParseError:
            return None

    opts = {"model": "claude-sonnet-4-6", "allowed_tools": allowed_tools or []}
    if max_turns is not None:
        opts["max_turns"] = max_turns
    if output_format:
        opts["output_format"] = output_format
    options = ClaudeAgentOptions(**opts)

    os.environ["LARVLING_INTERNAL"] = "1"
    setattr(_sdk_client, "parse_message", _tolerant_parse)

    response_text = ""
    structured = None
    result_subtype = None
    try:
        async for msg in query(prompt=prompt, options=options):
            if msg is None:
                continue
            if isinstance(msg, ResultMessage):
                result_subtype = getattr(msg, "subtype", None)
                if msg.structured_output:
                    structured = msg.structured_output
                continue
            content = getattr(msg, "content", None)
            if not content:
                continue
            for block in content:
                text = getattr(block, "text", None)
                if text:
                    response_text += text
    finally:
        os.environ.pop("LARVLING_INTERNAL", None)
        setattr(_sdk_client, "parse_message", parse_message)

    if structured is not None:
        return structured

    if output_format:
        raise RuntimeError(
            f"Structured output not returned (subtype={result_subtype})"
        )

    return response_text.strip()


def _log(msg):
    """Append a message to .claude/larvling-errors.log for debugging."""
    try:
        log_path = os.path.join(os.getcwd(), ".claude", "larvling-errors.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass
