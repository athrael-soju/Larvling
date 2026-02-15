"""
Larvling Preflight — SessionStart hook.
Creates audit table on first run so auditing begins from message 1.
Detects bootstrap vs incomplete-bootstrap vs normal mode.
"""

import sqlite3
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, ".claude", "larvling.db")


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
    if fresh:
        conn.execute("""
            INSERT INTO audit (event_type, content)
            VALUES ('bootstrap_start', 'Larvling seed activated')
        """)
    conn.commit()
    conn.close()
    return fresh


def is_bootstrap_complete():
    """Check if bootstrap has been fully completed."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("SELECT 1 FROM audit WHERE event_type = 'bootstrap_complete' LIMIT 1")
    done = cur.fetchone() is not None
    conn.close()
    return done


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

    if fresh:
        print("# BOOTSTRAP MODE")
        print()
        print("Fresh Larvling instance. Audit table created — logging starts now.")
        print()
        print("**Your directive:** Read `CLAUDE.md` for mode detection, then `DNA.md` for the protocol.")
        print("Follow the bootstrap protocol: interview the user, then generate the project.")
        print("Log every action to the audit table from this point forward.")
    elif not is_bootstrap_complete():
        print("# BOOTSTRAP INCOMPLETE")
        print()
        print("Audit table exists but bootstrap never finished.")
        print("Read `CLAUDE.md` and resume the bootstrap protocol where it left off.")
        print("Check the audit table for what was already completed.")
    else:
        print(get_session_context())


if __name__ == "__main__":
    main()
