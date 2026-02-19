"""
Larvling Preflight - SessionStart hook.
Ensures current schema exists, then injects session context.
"""

import os
import shutil
import subprocess
import sys

from db import (
    DB_PATH,
    SCHEMA_VERSION,
    escape_like,
    get_db,
    get_summary,
    reconfigure_stdout,
    create_schema,
    get_schema_version,
    set_schema_version,
    get_current_schema,
    get_desired_schema,
)


def ensure_schema():
    """Ensure current schema exists.

    Returns:
        'fresh'    - first install, schema created
        'current'  - schema up to date
        'migrate'  - version mismatch, migration context printed for Claude
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()

    has_tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
    ).fetchone()

    if not has_tables:
        create_schema(conn)
        set_schema_version(conn)
        conn.close()
        return "fresh"

    db_version = get_schema_version(conn)
    if db_version == SCHEMA_VERSION:
        conn.close()
        return "current"

    # Version mismatch — backup DB, then dump both schemas for Claude to handle
    old_schema = get_current_schema(conn)
    new_schema = get_desired_schema()
    conn.close()

    backup_path = DB_PATH + f".v{db_version}.bak"
    shutil.copy2(DB_PATH, backup_path)

    print("# Larvling - Schema Migration Required\n")
    print(f"Database schema is version **{db_version}**, expected **{SCHEMA_VERSION}**.")
    print(f"A backup has been saved to `{backup_path}`.\n")
    print("## Current Schema (in database)")
    print(f"```sql\n{old_schema}\n```\n")
    print("## Desired Schema")
    print(f"```sql\n{new_schema}\n```\n")
    safe_path = DB_PATH.replace("\\", "/")
    print("Please migrate the database at `" + safe_path + "` from the current schema to the desired schema.")
    print("Preserve all existing data. After migrating, run:")
    print(f"```python\npython -c \"import sqlite3; c=sqlite3.connect('{safe_path}'); c.execute('PRAGMA user_version={SCHEMA_VERSION}'); c.close()\"\n```")

    return "migrate"


def get_recent_summaries(conn, limit=3):
    """Get summaries from the most recent sessions."""
    rows = conn.execute(
        """
        SELECT id, started_at, duration_min, agent_summary, title
        FROM sessions
        WHERE agent_summary IS NOT NULL OR title IS NOT NULL
        ORDER BY started_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    summaries = []
    for row in rows:
        summary = row["agent_summary"] or row["title"]
        if not summary:
            continue
        date = (row["started_at"] or "?")[:10]
        duration = row["duration_min"]
        duration_str = f" ({duration}m)" if duration else ""
        summaries.append(f"- **{date}**{duration_str}: {summary}")
    return summaries


def get_git_context():
    """Get file paths from recent git activity. Returns list of file names."""
    files = []

    for cmd in [
        ["git", "diff", "--name-only"],
        ["git", "diff", "--name-only", "--cached"],
    ]:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                files.extend(result.stdout.strip().splitlines())
        except (FileNotFoundError, OSError):
            return []  # git not available
        except subprocess.TimeoutExpired:
            continue

    try:
        result = subprocess.run(
            ["git", "log", "--pretty=format:", "-5", "--name-only"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                line = line.strip()
                if line:
                    files.append(line)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    seen = set()
    unique = []
    for f in files:
        f = f.strip()
        if f and f not in seen:
            seen.add(f)
            unique.append(f)
    return unique[:20]


def find_relevant_sessions(conn, file_names, exclude_sids, limit=2):
    """Find sessions that reference any of the given file names."""
    if not file_names:
        return []

    session_hits = {}
    for fname in file_names:
        basename = os.path.basename(fname)
        if not basename or len(basename) < 3:
            continue
        safe_name = escape_like(basename)
        rows = conn.execute(
            "SELECT DISTINCT session_id FROM messages "
            "WHERE content LIKE ? ESCAPE '\\' "
            "AND role IN ('user', 'assistant')",
            (f"%{safe_name}%",),
        ).fetchall()
        for row in rows:
            sid = row["session_id"]
            if sid not in exclude_sids:
                session_hits[sid] = session_hits.get(sid, 0) + 1

    if not session_hits:
        return []

    top_sids = sorted(
        session_hits, key=lambda sid: session_hits[sid], reverse=True
    )[:limit]

    results = []
    for sid in top_sids:
        ref = get_summary(conn, sid)
        if not ref:
            continue
        summary = ref["agent_summary"] or ref["title"]
        if not summary:
            continue
        sess = conn.execute(
            "SELECT started_at, duration_min FROM sessions WHERE id = ?",
            (sid,),
        ).fetchone()
        date = (sess["started_at"] or "?")[:10] if sess else "?"
        duration = sess["duration_min"] if sess else None
        duration_str = f" ({duration}m)" if duration else ""
        results.append(f"- **{date}**{duration_str}: {summary}")

    return results


def get_session_context():
    """Build curated session context from summaries and relevant sessions."""
    conn = get_db()

    lines = ["# Larvling Session Context", ""]

    # Recent session summaries
    summaries = get_recent_summaries(conn)
    recent_sids = set()
    if summaries:
        lines.append("## Recent Sessions")
        lines.extend(summaries)
        lines.append("")
        rows = conn.execute(
            """
            SELECT id FROM sessions
            WHERE agent_summary IS NOT NULL OR title IS NOT NULL
            ORDER BY started_at DESC LIMIT 3
            """
        ).fetchall()
        recent_sids = {row["id"] for row in rows}

    # Git-aware relevant sessions
    git_files = get_git_context()
    if git_files:
        relevant = find_relevant_sessions(conn, git_files, recent_sids)
        if relevant:
            lines.append("## Relevant Sessions")
            lines.extend(relevant)
            lines.append("")

    # Fallback: if no summaries, show recent data
    if not summaries:
        try:
            rows = conn.execute(
                "SELECT role, content FROM messages ORDER BY id DESC LIMIT 5"
            ).fetchall()
            if rows:
                total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
                lines.append(f"## Recent Activity ({total} messages)")
                for row in rows:
                    content = (row["content"] or "")[:80]
                    lines.append(f"- **{row['role']}:** {content}")
                lines.append("")
        except Exception:
            pass

    conn.close()
    return "\n".join(lines)


def main():
    reconfigure_stdout()

    result = ensure_schema()

    if result == "fresh":
        print("# Larvling - First Run\n")
        print("Database created at `.claude/larvling.db`.")
        print("Dashboard at `.claude/dashboard.html`.")
    elif result == "migrate":
        pass  # Migration context already printed by ensure_schema
    else:
        print(get_session_context())


if __name__ == "__main__":
    main()
