"""
Larvling Preflight — SessionStart hook.
Creates imprints table on first run, then injects session context.
"""

import json
import os
import subprocess
import sys

from db import DB_PATH, get_db, get_session_end_meta, parse_meta, reconfigure_stdout


def ensure_audit_table():
    """Create the imprints table if the DB doesn't exist yet. Returns True if this was a fresh creation."""
    fresh = not os.path.exists(DB_PATH)
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
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


def get_recent_summaries(conn, limit=3):
    """Get summaries from the most recent sessions."""
    rows = conn.execute(
        """
        SELECT
            session_id,
            metadata,
            timestamp
        FROM imprints
        WHERE event_type = 'session_end' AND metadata IS NOT NULL
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    summaries = []
    for row in rows:
        meta = parse_meta(row["metadata"])
        # Prefer session summary (LLM-generated) over session title (first prompt)
        summary = meta.get("llm_summary") or meta.get("summary")
        if not summary:
            continue
        date = row["timestamp"][:10] if row["timestamp"] else "?"
        duration = meta.get("duration_min")
        duration_str = f" ({duration}m)" if duration else ""
        summaries.append(f"- **{date}**{duration_str}: {summary}")
    return summaries



def get_git_context():
    """Get file paths from recent git activity. Returns list of file names."""
    files = []

    # Uncommitted changes (unstaged + staged)
    for cmd in [["git", "diff", "--name-only"], ["git", "diff", "--name-only", "--cached"]]:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                files.extend(result.stdout.strip().splitlines())
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return []

    # Recent commits
    try:
        result = subprocess.run(
            ["git", "log", "--pretty=format:", "-5", "--name-only"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                line = line.strip()
                if line:
                    files.append(line)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    # Deduplicate, cap at 20 (diff files prioritized over log files)
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
        rows = conn.execute(
            "SELECT DISTINCT session_id FROM imprints "
            "WHERE content LIKE ? AND session_id IS NOT NULL "
            "AND event_type IN ('user_message', 'agent_message')",
            (f"%{basename}%",),
        ).fetchall()
        for row in rows:
            sid = row["session_id"]
            if sid not in exclude_sids:
                session_hits[sid] = session_hits.get(sid, 0) + 1

    if not session_hits:
        return []

    top_sids = sorted(session_hits, key=lambda sid: session_hits[sid], reverse=True)[:limit]

    results = []
    for sid in top_sids:
        meta = get_session_end_meta(conn, sid)
        summary = meta.get("llm_summary") or meta.get("summary")
        if not summary:
            continue
        date = (meta.get("started_at") or "?")[:10]
        duration = meta.get("duration_min")
        duration_str = f" ({duration}m)" if duration else ""
        results.append(f"- **{date}**{duration_str}: {summary}")

    return results


def get_session_context():
    """Build curated session context from summaries, relevant sessions, and unfinished work."""
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
            "SELECT session_id FROM imprints "
            "WHERE event_type = 'session_end' AND metadata IS NOT NULL "
            "ORDER BY id DESC LIMIT 3"
        ).fetchall()
        recent_sids = {row["session_id"] for row in rows}

    # Git-aware relevant sessions
    git_files = get_git_context()
    if git_files:
        relevant = find_relevant_sessions(conn, git_files, recent_sids)
        if relevant:
            lines.append("## Relevant Sessions")
            lines.extend(relevant)
            lines.append("")

    # Fallback: if no summaries yet, show recent imprints so context isn't empty
    if not summaries:
        rows = conn.execute(
            "SELECT event_type, content FROM imprints ORDER BY id DESC LIMIT 5"
        ).fetchall()
        if rows:
            lines.append("## imprints ({})".format(
                conn.execute("SELECT COUNT(*) FROM imprints").fetchone()[0]
            ))
            for row in rows:
                content = (row["content"] or "")[:80]
                lines.append(f"- **{row['event_type']}:** {content}")
            lines.append("")

    conn.close()
    return "\n".join(lines)


def main():
    reconfigure_stdout()

    fresh = ensure_audit_table()

    if fresh:
        print("# Larvling — First Run\n")
        print("Database created at `.claude/larvling.db`.")
        print("Dashboard at `.claude/dashboard.html`.")
    else:
        print(get_session_context())


if __name__ == "__main__":
    main()
