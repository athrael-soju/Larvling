"""
Larvling Preflight — SessionStart hook.
Creates audit table on first run so auditing begins from message 1.
Detects bootstrap vs incomplete-bootstrap vs normal mode.
"""

import os
import sqlite3
import sys

from db import DB_PATH


def ensure_audit_table():
    """Create the audit table if the DB doesn't exist yet. Returns True if this was a fresh creation."""
    fresh = not os.path.exists(DB_PATH)
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT NOT NULL DEFAULT (datetime('now')),
            session_id  TEXT,
            event_type  TEXT NOT NULL,
            content     TEXT,
            metadata    TEXT
        )
    """)
    conn.commit()
    conn.close()
    return fresh


def get_bootstrap_state():
    """Check bootstrap state: 'complete', 'incomplete', or None."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "SELECT event_type FROM audit WHERE event_type IN ('bootstrap_start', 'bootstrap_complete') ORDER BY id DESC LIMIT 1"
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return "complete" if row[0] == "bootstrap_complete" else "incomplete"


def summarize_row(row, columns):
    """Pick the most descriptive columns from a row to summarize it."""
    # Prefer these columns for display, in order
    display_prefs = ['title', 'name', 'content', 'description', 'summary',
                     'event_type', 'key', 'status', 'severity', 'priority']
    parts = []
    for col in display_prefs:
        if col in columns and row[col] is not None:
            val = str(row[col])[:80]
            parts.append(f"**{col}:** {val}")
            if len(parts) >= 3:
                break
    if not parts:
        # Fallback: show first non-id, non-timestamp columns
        skip = {'id', 'created_at', 'updated_at', 'timestamp', 'metadata'}
        for col in columns:
            if col not in skip and row[col] is not None:
                parts.append(f"**{col}:** {str(row[col])[:80]}")
                if len(parts) >= 3:
                    break
    return ' | '.join(parts) if parts else '(empty row)'


def get_session_context():
    """Introspect the DB and build session context dynamically."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Discover all tables
    cur.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
    """)
    tables = [r[0] for r in cur.fetchall()]

    lines = ["# Larvling Session Context", ""]

    for table in tables:
        cur.execute(f"SELECT COUNT(*) FROM [{table}]")
        count = cur.fetchone()[0]

        # Discover columns
        cur.execute(f"PRAGMA table_info([{table}])")
        columns = [col['name'] for col in cur.fetchall()]

        # Find best column to order by
        order_col = 'id'
        for candidate in ['timestamp', 'created_at', 'updated_at', 'start_time']:
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
    sys.stdout.reconfigure(encoding="utf-8")

    fresh = ensure_audit_table()
    state = get_bootstrap_state()

    if fresh:
        print("# Larvling Ready")
        print()
        print("Audit DB created. Hooks active. All conversations are being tracked.")
        print()
        print("Run `/bootstrap` to customize project tracking (tasks, decisions, bugs, etc).")
    elif state == "incomplete":
        print("# BOOTSTRAP INCOMPLETE")
        print()
        print("A previous `/bootstrap` was started but never finished.")
        print("Read `DNA.md` and resume the bootstrap protocol where it left off.")
        print("Check the audit table for what was already completed.")
    else:
        context = get_session_context()
        print(context)
        if state != "complete":
            print("---")
            print("Tip: run `/bootstrap` to set up project tracking.")


if __name__ == "__main__":
    main()
