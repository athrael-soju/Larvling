"""
Larvling Preflight - SessionStart hook.
Ensures v2 schema exists (migrating from v1 if needed), then injects session context.
"""

import os
import subprocess
import sys

from db import (
    DB_PATH,
    escape_like,
    get_db,
    get_reflection,
    reconfigure_stdout,
    detect_schema_version,
    create_v2_schema,
    migrate_v1_to_v2,
)


def ensure_schema():
    """Ensure v2 schema exists, migrating from v1 if needed.

    Returns True if this was a fresh install (no prior Larvling data).
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    version = detect_schema_version(conn)

    if version == "fresh":
        create_v2_schema(conn)
        conn.close()
        return True
    elif version == "v1":
        try:
            migrate_v1_to_v2(conn)
        except Exception:
            pass  # Error already logged, continue with whatever schema exists
        conn.close()
        return False
    else:
        # v2 — run create to ensure new tables (e.g. memories) exist
        create_v2_schema(conn)
        conn.close()
        return False


def get_recent_summaries(conn, limit=3):
    """Get summaries from the most recent sessions."""
    rows = conn.execute(
        """
        SELECT e.id, e.started_at, e.duration_min,
               r.agent_summary, r.title
        FROM encounters e
        JOIN reflections r ON r.encounter_id = e.id
        WHERE r.agent_summary IS NOT NULL OR r.title IS NOT NULL
        ORDER BY e.started_at DESC
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


def find_relevant_sessions(conn, file_names, exclude_eids, limit=2):
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
            "SELECT DISTINCT encounter_id FROM imprints "
            "WHERE content LIKE ? ESCAPE '\\' "
            "AND role IN ('user', 'assistant')",
            (f"%{safe_name}%",),
        ).fetchall()
        for row in rows:
            eid = row["encounter_id"]
            if eid not in exclude_eids:
                session_hits[eid] = session_hits.get(eid, 0) + 1

    if not session_hits:
        return []

    top_eids = sorted(
        session_hits, key=lambda eid: session_hits[eid], reverse=True
    )[:limit]

    results = []
    for eid in top_eids:
        ref = get_reflection(conn, eid)
        if not ref:
            continue
        summary = ref["agent_summary"] or ref["title"]
        if not summary:
            continue
        enc = conn.execute(
            "SELECT started_at, duration_min FROM encounters WHERE id = ?",
            (eid,),
        ).fetchone()
        date = (enc["started_at"] or "?")[:10] if enc else "?"
        duration = enc["duration_min"] if enc else None
        duration_str = f" ({duration}m)" if duration else ""
        results.append(f"- **{date}**{duration_str}: {summary}")

    return results


def get_session_context():
    """Build curated session context from summaries and relevant sessions."""
    conn = get_db()

    lines = ["# Larvling Session Context", ""]

    # Recent session summaries
    summaries = get_recent_summaries(conn)
    recent_eids = set()
    if summaries:
        lines.append("## Recent Sessions")
        lines.extend(summaries)
        lines.append("")
        rows = conn.execute(
            """
            SELECT e.id FROM encounters e
            JOIN reflections r ON r.encounter_id = e.id
            WHERE r.agent_summary IS NOT NULL OR r.title IS NOT NULL
            ORDER BY e.started_at DESC LIMIT 3
            """
        ).fetchall()
        recent_eids = {row["id"] for row in rows}

    # Git-aware relevant sessions
    git_files = get_git_context()
    if git_files:
        relevant = find_relevant_sessions(conn, git_files, recent_eids)
        if relevant:
            lines.append("## Relevant Sessions")
            lines.extend(relevant)
            lines.append("")

    # Fallback: if no summaries, show recent data
    if not summaries:
        try:
            rows = conn.execute(
                "SELECT role, content FROM imprints ORDER BY id DESC LIMIT 5"
            ).fetchall()
            if rows:
                total = conn.execute("SELECT COUNT(*) FROM imprints").fetchone()[0]
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

    fresh = ensure_schema()

    if fresh:
        print("# Larvling - First Run\n")
        print("Database created at `.claude/larvling.db`.")
        print("Dashboard at `.claude/dashboard.html`.")
    else:
        print(get_session_context())


if __name__ == "__main__":
    main()
