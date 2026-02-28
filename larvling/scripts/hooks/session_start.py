"""SessionStart hook — injects session context and checks for updates."""

import json
import os
import subprocess
import sys
import time
import urllib.request

from config import get_config
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

CACHE_PATH = os.path.join(os.getcwd(), ".claude", "larvling-cache.json")
CACHE_TTL = 86400  # 24 hours


def _read_cache(key):
    """Read a cached value. Returns None if expired or missing."""
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            cache = json.load(f)
        entry = cache.get(key)
        if entry and time.time() - entry.get("ts", 0) < CACHE_TTL:
            return entry.get("data")
    except Exception:
        pass
    return None


def _write_cache(key, data):
    """Write a value to the file-based cache."""
    try:
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            cache = {}
        cache[key] = {"ts": time.time(), "data": data}
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except Exception:
        pass


def format_session_line(started_at, duration_min, summary):
    """Format a session as a markdown bullet line."""
    date = (started_at or "?")[:10]
    dur = f" ({duration_min}m)" if duration_min else ""
    return f"- **{date}**{dur}: {summary}"


def get_recent_summaries(conn, limit=5):
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

    return list(dict.fromkeys(f.strip() for f in files if f.strip()))


def find_relevant_sessions(conn, file_names, exclude_sids, limit=3):
    """Find sessions that reference any of the given file names."""
    if not file_names:
        return []

    session_hits = {}
    for fname in file_names:
        basename = os.path.basename(fname)
        if not basename:
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


def get_time_and_location(enable_geo=True):
    """Return a line with local datetime, UTC offset, and approximate location.

    Location comes from a free IP-geolocation API (cached for 24h).
    Falls back gracefully — time is always available, location is best-effort.
    Set enable_geo=False to skip the geolocation lookup entirely.
    """
    now = time.localtime()
    utc_offset_sec = time.timezone if now.tm_isdst == 0 else time.altzone
    utc_offset_h = -utc_offset_sec / 3600  # sign convention: west = positive timezone
    sign = "+" if utc_offset_h >= 0 else "-"
    offset_str = f"UTC{sign}{abs(utc_offset_h):g}"

    dt_str = time.strftime("%A, %B %d, %Y at %I:%M %p", now)
    parts = [f"{dt_str} ({offset_str})"]

    if not enable_geo:
        return " — ".join(parts)

    # Best-effort geolocation (cached 24h to avoid repeated API calls)
    geo = _read_cache("geolocation")
    if geo is None:
        try:
            req = urllib.request.Request(
                "https://ipinfo.io/json",
                headers={"User-Agent": "larvling", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                geo = json.loads(resp.read().decode("utf-8"))
            _write_cache("geolocation", geo)
        except Exception:
            geo = {}

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

    return " — ".join(parts)


def get_session_context():
    """Build curated session context from summaries and relevant sessions."""
    with open_db() as conn:
        lines = ["# Larvling Session Context", ""]

        # Time and location
        cfg = get_config()
        try:
            time_loc = get_time_and_location(enable_geo=cfg["geolocation"])
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
                ORDER BY started_at DESC LIMIT 5
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
        topic_count = 0
        stmt_count = 0
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
                    "SELECT t.id, t.title, s.id as sid, s.claim "
                    "FROM topics t JOIN statements s ON s.topic_id = t.id "
                    "ORDER BY s.updated DESC, s.created DESC LIMIT 10"
                ).fetchall()
                lines.append(f"## Stored Knowledge ({topic_count} topics, {stmt_count} statements)")
                lines.append(f"Domains: {domains}")
                for r in recent:
                    lines.append(f"- {r['sid']}: {r['claim']}")
                lines.append("")

        # Maintenance hint for large knowledge bases
        if topic_count >= 50 or stmt_count >= 100:
            lines.append("## Maintenance")
            lines.append(
                f"Knowledge base has grown ({topic_count} topics, {stmt_count} statements). "
                "Consider offering /maintain."
            )
            lines.append("")

        # Open tasks at session start
        if has_table(conn, "tasks"):
            total_open = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status = 'open'"
            ).fetchone()[0]
            open_tasks = conn.execute(
                "SELECT id, title, priority, horizon FROM tasks "
                "WHERE status = 'open' "
                "ORDER BY CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, "
                "CASE horizon WHEN 'now' THEN 1 WHEN 'soon' THEN 2 ELSE 3 END"
            ).fetchall()
            if open_tasks:
                lines.append(f"## Open Tasks ({total_open})")
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
                        content = row["content"] or ""
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
    Uses a 24h file cache to avoid repeated API calls.
    """
    local_version = get_plugin_version()
    if local_version == "?":
        return None

    latest = _read_cache("update_check")
    if latest is None:
        try:
            req = urllib.request.Request(
                RELEASES_URL,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "larvling"},
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            latest = data.get("tag_name", "").lstrip("v")
            if latest:
                _write_cache("update_check", latest)
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

    # Read hook payload for matcher differentiation
    payload = None
    try:
        raw = sys.stdin.buffer.read().decode("utf-8")
        if raw.strip():
            payload = json.loads(raw)
    except Exception:
        pass

    matcher = (payload or {}).get("matcher", "startup")

    # Skip context during schema migration (preflight printed migration instructions)
    with open_db() as conn:
        if get_schema_version(conn) != SCHEMA_VERSION:
            return

    # Skip full context injection during compaction
    if matcher == "compact":
        return

    print(get_session_context())

    update_notice = check_update()
    if update_notice:
        print(f"\n{update_notice}")


if __name__ == "__main__":
    main()
