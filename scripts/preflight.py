"""
Zergling Preflight — SessionStart hook.
Detects first run, creates audit DB, and injects session context.
"""

import sqlite3
import os
import sys
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, ".claude", "zergling.db")


def create_audit_db():
    """Create the seed audit database with minimal schema."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT NOT NULL DEFAULT (datetime('now')),
            session_id  TEXT,
            event_type  TEXT NOT NULL,
            content     TEXT,
            metadata    TEXT
        )
    """)

    cur.execute("""
        INSERT INTO audit (event_type, content)
        VALUES ('bootstrap_start', 'Zergling seed activated — first run')
    """)

    conn.commit()
    conn.close()


def get_session_context():
    """Query existing DB and return session context for normal runs."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Recent activity
    cur.execute("""
        SELECT timestamp, event_type, content
        FROM audit ORDER BY id DESC LIMIT 10
    """)
    recent = cur.fetchall()

    # Stats
    cur.execute("SELECT COUNT(DISTINCT session_id) FROM audit WHERE session_id IS NOT NULL")
    session_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM audit")
    total_events = cur.fetchone()[0]

    # Check what tables exist beyond audit (indicates bootstrap completed)
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'audit'")
    extra_tables = [r[0] for r in cur.fetchall()]

    conn.close()

    lines = [
        "# Zergling Session Context",
        "",
        f"**Sessions:** {session_count} | **Events logged:** {total_events}",
        f"**Project tables:** audit, {', '.join(extra_tables) if extra_tables else '(none — bootstrap may be incomplete)'}",
        "",
        "## Recent Activity",
    ]
    for row in recent:
        lines.append(f"- `{row['timestamp']}` **{row['event_type']}** — {row['content']}")

    return "\n".join(lines)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    bootstrap = not os.path.exists(DB_PATH)

    if bootstrap:
        create_audit_db()
        print("# BOOTSTRAP MODE")
        print()
        print("Fresh Zergling instance detected. Audit database created at `.claude/zergling.db`.")
        print()
        print("**Your directive:** Read `CLAUDE.md` — it contains your genome.")
        print("Follow the bootstrap protocol: interview the user, then generate the project.")
    else:
        print(get_session_context())


if __name__ == "__main__":
    main()
