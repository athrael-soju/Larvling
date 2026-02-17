"""
Larvling Stats — compute aggregate statistics from larvling.db.

Usage:
    python stats.py         # formatted text output
    python stats.py --json  # structured JSON output
"""

import json
import sys
from datetime import datetime, timedelta

from db import get_db, parse_meta, require_db, reconfigure_stdout


def compute_stats(conn):
    """Compute aggregate statistics from the database. Returns a dict."""
    stats = {}

    stats["total_sessions"] = conn.execute(
        "SELECT COUNT(DISTINCT session_id) FROM imprints WHERE session_id IS NOT NULL"
    ).fetchone()[0]

    stats["total_imprints"] = conn.execute(
        "SELECT COUNT(*) FROM imprints"
    ).fetchone()[0]

    stats["total_messages"] = conn.execute(
        "SELECT COUNT(*) FROM imprints WHERE event_type IN ('user_message', 'agent_message')"
    ).fetchone()[0]

    stats["avg_messages_per_session"] = round(
        stats["total_messages"] / max(stats["total_sessions"], 1), 1
    )

    # Parse session_end metadata for duration and summary stats
    rows = conn.execute(
        "SELECT metadata FROM imprints WHERE event_type = 'session_end' AND metadata IS NOT NULL"
    ).fetchall()

    durations = []
    with_summary = 0
    without_summary = 0
    for row in rows:
        meta = parse_meta(row[0])
        if not meta:
            continue
        d = meta.get("duration_min")
        if d is not None:
            try:
                durations.append(float(d))
            except (ValueError, TypeError):
                pass
        if meta.get("llm_summary"):
            with_summary += 1
        else:
            without_summary += 1

    stats["avg_duration_min"] = round(sum(durations) / len(durations), 1) if durations else 0
    stats["sessions_with_summary"] = with_summary
    stats["sessions_without_summary"] = without_summary

    # Tool usage from agent_message metadata
    tool_counts = {}
    rows = conn.execute(
        "SELECT metadata FROM imprints WHERE event_type = 'agent_message' AND metadata IS NOT NULL"
    ).fetchall()
    for row in rows:
        meta = parse_meta(row[0])
        for name, count in meta.get("tool_calls", {}).items():
            tool_counts[name] = tool_counts.get(name, 0) + count

    stats["tool_usage"] = dict(
        sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    )

    # Activity by day (last 14 days)
    today = datetime.now().date()
    day_counts = {}
    for i in range(13, -1, -1):
        day_counts[(today - timedelta(days=i)).isoformat()] = 0

    rows = conn.execute(
        "SELECT DATE(timestamp) as day, COUNT(*) as cnt FROM imprints "
        "WHERE timestamp >= DATE('now', '-14 days') GROUP BY DATE(timestamp)"
    ).fetchall()
    for row in rows:
        if row[0] in day_counts:
            day_counts[row[0]] = row[1]

    stats["activity_by_day"] = day_counts


    return stats


def format_bar(value, max_val, width=20):
    """Render a simple bar using block chars."""
    if max_val == 0:
        return ""
    filled = int((value / max_val) * width)
    return "\u2588" * filled + "\u2591" * (width - filled)


def format_stats(stats):
    """Format stats as human-readable text."""
    lines = [
        "# Larvling Stats",
        "",
        f"Sessions:       {stats['total_sessions']}",
        f"Imprints:       {stats['total_imprints']}",
        f"Messages:       {stats['total_messages']}",
        f"Avg duration:   {stats['avg_duration_min']} min",
        f"Avg msgs/sess:  {stats['avg_messages_per_session']}",
        f"Summarized:     {stats['sessions_with_summary']}/{stats['sessions_with_summary'] + stats['sessions_without_summary']}",
        "",
    ]

    if stats["tool_usage"]:
        lines.append("## Top Tools")
        max_count = max(stats["tool_usage"].values())
        for name, count in stats["tool_usage"].items():
            bar = format_bar(count, max_count)
            lines.append(f"  {name:<20} {bar} {count}")
        lines.append("")

    if stats["activity_by_day"]:
        lines.append("## Activity (14 days)")
        max_day = max(stats["activity_by_day"].values()) or 1
        for day, count in stats["activity_by_day"].items():
            bar = format_bar(count, max_day)
            lines.append(f"  {day[5:]} {bar} {count}")
        lines.append("")

    return "\n".join(lines)


def main():
    reconfigure_stdout()

    require_db()
    conn = get_db()
    stats = compute_stats(conn)
    conn.close()

    if "--json" in sys.argv:
        print(json.dumps(stats, indent=2))
    else:
        print(format_stats(stats))


if __name__ == "__main__":
    main()
