"""SessionStart hook — injects session context and checks for updates."""

import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db import (
    SCHEMA_VERSION,
    escape_like,
    get_plugin_version,
    get_summary,
    has_table,
    open_db,
    reconfigure_stdout,
    get_schema_version,
)


def format_session_line(started_at, duration_min, summary):
    """Format a session as a markdown bullet line."""
    date = (started_at or "?")[:10]
    dur = f" ({duration_min}m)" if duration_min else ""
    return f"- **{date}**{dur}: {summary}"


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
        if summary:
            summaries.append(format_session_line(row["started_at"], row["duration_min"], summary))
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
        except FileNotFoundError:
            return []  # git not installed
        except (OSError, subprocess.TimeoutExpired):
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

    return list(dict.fromkeys(f.strip() for f in files if f.strip()))[:20]


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

    top_sids = sorted(session_hits, key=lambda sid: session_hits[sid], reverse=True)[
        :limit
    ]

    results = []
    for sid in top_sids:
        ref = get_summary(conn, sid)
        if not ref:
            continue
        summary = ref["agent_summary"] or ref["title"]
        if summary:
            results.append(format_session_line(ref["started_at"], ref["duration_min"], summary))

    return results


def get_time_and_location():
    """Return a line with local datetime, UTC offset, and approximate location.

    Location comes from a free IP-geolocation API (no auth required).
    Falls back gracefully — time is always available, location is best-effort.
    """
    now = time.localtime()
    utc_offset_sec = time.timezone if now.tm_isdst == 0 else time.altzone
    utc_offset_h = -utc_offset_sec / 3600  # sign convention: west = positive timezone
    sign = "+" if utc_offset_h >= 0 else "-"
    offset_str = f"UTC{sign}{abs(utc_offset_h):g}"

    dt_str = time.strftime("%A, %B %d, %Y at %I:%M %p", now)
    parts = [f"{dt_str} ({offset_str})"]

    # Best-effort geolocation via free API
    try:
        req = urllib.request.Request(
            "https://ipinfo.io/json",
            headers={"User-Agent": "larvling", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            geo = json.loads(resp.read().decode("utf-8"))
        city = geo.get("city", "")
        region = geo.get("region", "")
        country = geo.get("country", "")
        tz = geo.get("timezone", "")
        loc_parts = [p for p in [city, region, country] if p]
        if loc_parts:
            loc_str = ", ".join(loc_parts)
            if tz:
                loc_str += f" ({tz})"
            parts.append(loc_str)
    except Exception:
        pass

    return " — ".join(parts)


def get_session_context():
    """Build curated session context from summaries and relevant sessions."""
    with open_db() as conn:
        lines = ["# Larvling Session Context", ""]

        # Time and location
        try:
            time_loc = get_time_and_location()
            lines.append(f"**Now:** {time_loc}")
            lines.append("")
        except Exception:
            pass

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

        # Knowledge awareness at session start
        if has_table(conn, "topics"):
            topic_count = conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0]
            stmt_count = conn.execute("SELECT COUNT(*) FROM statements").fetchone()[0] if has_table(conn, "statements") else 0
            if topic_count:
                domain_rows = conn.execute(
                    "SELECT COALESCE(domain, 'unset') as d, COUNT(*) as c "
                    "FROM topics GROUP BY domain ORDER BY c DESC"
                ).fetchall()
                domains = ", ".join(
                    f"{r['d']} ({r['c']})" for r in domain_rows
                )
                recent = conn.execute(
                    "SELECT t.id, t.title, s.claim "
                    "FROM topics t JOIN statements s ON s.topic_id = t.id "
                    "ORDER BY s.created DESC LIMIT 3"
                ).fetchall()
                lines.append(f"## Stored Knowledge ({topic_count} topics, {stmt_count} statements)")
                lines.append(f"Domains: {domains}")
                for r in recent:
                    lines.append(f"- {r['id']}: {r['claim']}")
                lines.append("")

        # Open tasks at session start
        if has_table(conn, "tasks"):
            open_tasks = conn.execute(
                "SELECT id, title, priority, horizon FROM tasks "
                "WHERE status = 'open' "
                "ORDER BY CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END "
                "LIMIT 3"
            ).fetchall()
            if open_tasks:
                lines.append(f"## Open Tasks ({len(open_tasks)})")
                for t in open_tasks:
                    lines.append(f"- [{t['priority']}/{t['horizon']}] {t['title']}")
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

    return "\n".join(lines)


GITHUB_REPO = "athrael-soju/Larvling"
RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def check_update():
    """Compare local plugin version against latest GitHub release.

    Returns an update notice string, or None if up to date / check fails.
    """
    local_version = get_plugin_version()
    if local_version == "?":
        return None

    try:
        req = urllib.request.Request(
            RELEASES_URL,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "larvling"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        latest = data.get("tag_name", "").lstrip("v")
    except Exception:
        return None

    if not latest or not local_version:
        return None

    try:
        remote = tuple(int(x) for x in latest.split("."))
        local = tuple(int(x) for x in local_version.split("."))
    except (ValueError, AttributeError):
        return None

    if remote > local:
        return (
            f"**Larvling update available:** v{local_version} -> v{latest}  \n"
            f"Update via the plugin manager or reinstall from `{GITHUB_REPO}`."
        )
    return None


def main():
    if os.environ.get("LARVLING_INTERNAL"):
        return
    reconfigure_stdout()

    # Skip context during schema migration (preflight printed migration instructions)
    with open_db() as conn:
        if get_schema_version(conn) != SCHEMA_VERSION:
            return

    print(get_session_context())

    update_notice = check_update()
    if update_notice:
        print(f"\n{update_notice}")


if __name__ == "__main__":
    main()
