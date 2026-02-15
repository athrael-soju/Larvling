"""
Zergling Preflight — SessionStart hook.
Creates audit table on first run so auditing begins from message 1.
Detects bootstrap vs incomplete-bootstrap vs normal mode.
"""

import sqlite3
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, ".claude", "zergling.db")


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
            VALUES ('bootstrap_start', 'Zergling seed activated')
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


def get_session_context():
    """Query existing DB and return session context for normal runs."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT timestamp, event_type, content
        FROM audit ORDER BY id DESC LIMIT 10
    """)
    recent = cur.fetchall()

    cur.execute("SELECT COUNT(DISTINCT session_id) FROM audit WHERE session_id IS NOT NULL")
    session_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM audit")
    total_events = cur.fetchone()[0]

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cur.fetchall()]

    conn.close()

    lines = [
        "# Zergling Session Context",
        "",
        f"**Sessions:** {session_count} | **Events logged:** {total_events}",
        f"**Tables:** {', '.join(tables)}",
        "",
        "## Recent Activity",
    ]
    for row in recent:
        lines.append(f"- `{row['timestamp']}` **{row['event_type']}** — {row['content']}")

    return "\n".join(lines)


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    fresh = ensure_audit_table()

    if fresh:
        print("# BOOTSTRAP MODE")
        print()
        print("Fresh Zergling instance. Audit table created — logging starts now.")
        print()
        print("**Your directive:** Read `CLAUDE.md` — it contains your genome.")
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
