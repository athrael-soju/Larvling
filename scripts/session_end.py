"""
Larvling Session End — captures session summary, duration, and file changes.

Hook event: SessionEnd
Logs a session_end audit event with metadata:
  - duration_min: session length in minutes
  - summary: first sentence of last agent message
  - files_changed: list of modified files (from git)
  - diff_summary: e.g. "+42 -15 across 3 files"
"""

import json
import sqlite3
import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, ".claude", "larvling.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def get_session_duration(conn, session_id):
    """Calculate session duration from first to last audit entry."""
    cur = conn.execute(
        """
        SELECT
            MIN(timestamp) as first_msg,
            MAX(timestamp) as last_msg,
            ROUND((julianday(MAX(timestamp)) - julianday(MIN(timestamp))) * 1440, 1) as duration_min
        FROM audit
        WHERE session_id = ?
        """,
        (session_id,),
    )
    row = cur.fetchone()
    if row and row[2] is not None:
        return {"started_at": row[0], "ended_at": row[1], "duration_min": row[2]}
    return {}


def get_git_diff():
    """Get git diff stats for uncommitted changes."""
    try:
        result = subprocess.run(
            ["git", "diff", "--stat", "HEAD"],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            timeout=5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return {}

        lines = result.stdout.strip().split("\n")
        files = []
        for line in lines[:-1]:  # last line is the summary
            name = line.split("|")[0].strip()
            if name:
                files.append(name)

        summary_line = lines[-1].strip() if lines else ""
        return {"files_changed": files, "diff_summary": summary_line}
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {}


def get_auto_summary(conn, session_id):
    """Extract a short summary from the last agent message."""
    cur = conn.execute(
        """
        SELECT content FROM audit
        WHERE session_id = ? AND event_type = 'agent_message'
        ORDER BY id DESC LIMIT 1
        """,
        (session_id,),
    )
    row = cur.fetchone()
    if not row or not row[0]:
        return ""

    text = row[0].strip()
    # Take first sentence (up to period, exclamation, or question mark)
    for i, ch in enumerate(text):
        if ch in ".!?" and i > 10:
            return text[: i + 1]
    # No sentence end found — take first 120 chars
    return text[:120] + ("..." if len(text) > 120 else "")


def main():
    raw = sys.stdin.read()
    if not raw.strip():
        return

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print("Failed to parse hook input", file=sys.stderr)
        return

    session_id = data.get("session_id")
    if not session_id:
        return

    conn = get_db()

    meta = {}
    meta.update(get_session_duration(conn, session_id))
    meta.update(get_git_diff())
    meta["summary"] = get_auto_summary(conn, session_id)

    conn.execute(
        "INSERT INTO audit (session_id, event_type, content, metadata) VALUES (?, ?, ?, ?)",
        (session_id, "session_end", "Session ended", json.dumps(meta)),
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
