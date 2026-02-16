"""
Larvling Preflight — SessionStart hook.
Creates imprints table on first run, then injects session context.
"""

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


def summarize_row(row, columns):
    """Pick the most descriptive columns from a row to summarize it."""
    display_prefs = [
        "title",
        "name",
        "content",
        "description",
        "summary",
        "event_type",
        "key",
        "status",
        "severity",
        "priority",
    ]
    parts = []
    for col in display_prefs:
        if col in columns and row[col] is not None:
            val = str(row[col])[:80]
            parts.append(f"**{col}:** {val}")
            if len(parts) >= 3:
                break
    if not parts:
        skip = {"id", "created_at", "updated_at", "timestamp", "metadata"}
        for col in columns:
            if col not in skip and row[col] is not None:
                parts.append(f"**{col}:** {str(row[col])[:80]}")
                if len(parts) >= 3:
                    break
    return " | ".join(parts) if parts else "(empty row)"


def get_session_context():
    """Introspect the DB and build session context dynamically."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
    """
    )
    tables = [r[0] for r in cur.fetchall()]

    lines = ["# Larvling Session Context", ""]

    for table in tables:
        cur.execute(f"SELECT COUNT(*) FROM [{table}]")
        count = cur.fetchone()[0]

        cur.execute(f"PRAGMA table_info([{table}])")
        columns = [col["name"] for col in cur.fetchall()]

        order_col = "id"
        for candidate in ["timestamp", "created_at", "updated_at", "start_time"]:
            if candidate in columns:
                order_col = candidate
                break

        cur.execute(f"SELECT * FROM [{table}] ORDER BY [{order_col}] DESC LIMIT 5")
        recent = cur.fetchall()

        lines.append(f"## {table} ({count})")
        for row in recent:
            lines.append(f"- {summarize_row(row, columns)}")
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
        print("Tell the user that Larvling is now active and tracking conversations.")
        print("Mention the dashboard at `.claude/dashboard.html`.")
    else:
        print(get_session_context())


if __name__ == "__main__":
    main()
