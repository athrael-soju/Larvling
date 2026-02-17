"""
Larvling Dashboard — generates a static HTML dashboard from larvling.db.
Two-panel layout: session list on left, conversation on right.
Zero dependencies: just sqlite3 + Python string templating.
"""

import json
import os
import sys
from html import escape

from db import DB_PATH, get_db, parse_meta, require_db, reconfigure_stdout

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(SCRIPT_DIR, "dashboard.html.template")
LOGO_URL = "https://raw.githubusercontent.com/athrael-soju/Larvling/main/larvling.png"

HTML_PATH = os.path.join(os.path.dirname(DB_PATH), "dashboard.html")


def get_sessions(conn):
    """Get imprints grouped by session, newest first."""
    rows = conn.execute(
        "SELECT * FROM imprints WHERE session_id IS NOT NULL ORDER BY id DESC"
    ).fetchall()

    by_session = {}
    for row in rows:
        by_session.setdefault(row["session_id"], []).append(row)

    sessions = []
    for sid, messages in by_session.items():
        end_meta = {}
        for m in messages:
            if m["event_type"] == "session_end" and m["metadata"]:
                candidate = parse_meta(m["metadata"])
                if not candidate:
                    continue
                if candidate.get("summary") or not end_meta:
                    end_meta = candidate
                if end_meta.get("summary"):
                    break
        user_count = sum(1 for m in messages if m["event_type"] == "user_message")
        agent_count = sum(1 for m in messages if m["event_type"] == "agent_message")
        if user_count + agent_count == 0:
            continue
        timestamps = [m["timestamp"] for m in messages if m["timestamp"]]
        sessions.append(
            {
                "session_id": sid,
                "started": min(timestamps) if timestamps else None,
                "ended": max(timestamps) if timestamps else None,
                "msg_count": user_count + agent_count,
                "messages": messages,
                "end_meta": end_meta,
            }
        )

    sessions.sort(key=lambda s: s["started"] or "", reverse=True)
    return sessions


def render_message(msg):
    """Render a single message as a chat bubble."""
    event = msg["event_type"]
    content = escape(msg["content"] or "")
    timestamp = msg["timestamp"] or ""
    time_short = timestamp.split(" ")[-1][:5] if " " in timestamp else timestamp[:5]

    meta = parse_meta(msg["metadata"])

    if event == "user_message":
        return f"""<div class="msg msg-user">
            <div class="msg-header"><span class="msg-role">You</span><span class="msg-time">{escape(time_short)}</span></div>
            <div class="msg-body">{content}</div>
        </div>"""
    elif event == "agent_message":
        tools_html = ""
        tool_calls = meta.get("tool_calls", {})
        if tool_calls:
            badges = " ".join(
                f'<span class="tool-badge">{escape(name)} x{count}</span>'
                for name, count in tool_calls.items()
            )
            tools_html = f'<div class="msg-tools">{badges}</div>'
        return f"""<div class="msg msg-agent">
            <div class="msg-header"><span class="msg-role">Agent</span><span class="msg-time">{escape(time_short)}</span></div>
            <div class="msg-body">{content}</div>
            {tools_html}
        </div>"""
    elif event == "session_end":
        return ""
    else:
        return f"""<div class="msg msg-system">
            <span class="msg-time">{escape(time_short)}</span> {escape(event)}: {content}
        </div>"""


def render_sidebar_item(session, index):
    """Render a compact sidebar entry for a session."""
    meta = session["end_meta"]
    started = session["started"] or "?"
    date_part = started.split(" ")[0] if " " in started else started
    time_part = started.split(" ")[-1][:5] if " " in started else ""

    duration = meta.get("duration_min") or 0
    duration_str = f"{duration}m" if duration else ""
    summary = escape(meta.get("summary") or f"{session['msg_count']} messages")
    active = "active" if index == 0 else ""
    sid = escape(session["session_id"] or "")

    ended = session["ended"] or started
    llm_summary = meta.get("llm_summary") or ""
    summary_item = f'<div class="menu-item si-summary-dl" data-summary="{escape(llm_summary)}">&#x1F4CB; Download summary</div>' if llm_summary else ""
    return f"""<div class="sidebar-item {active}" data-sid="{sid}" data-started="{escape(started)}" data-ended="{escape(ended)}" data-msgs="{session['msg_count']}" data-duration="{duration}">
        <div class="si-top">
            <span class="si-date">{escape(date_part)}</span>
            <span class="si-time">{escape(time_part)}</span>
            <span class="si-menu-wrap">
                <span class="si-menu-btn" title="Actions">&#x22EF;</span>
                <div class="si-menu">
                    {summary_item}
                    <div class="menu-item si-export-dl">&#x1F4BE; Export conversation</div>
                </div>
            </span>
        </div>
        <div class="si-summary">{summary}</div>
        <div class="si-meta">
            <span>{session['msg_count']} msgs</span>
            {f'<span>{duration_str}</span>' if duration_str else ''}
        </div>
    </div>"""


def render_detail_panel(session):
    """Render the full conversation panel for a session."""
    meta = session["end_meta"]
    started = session["started"] or "?"
    date_part = started.split(" ")[0] if " " in started else started

    duration = meta.get("duration_min")
    duration_str = f"{duration} min" if duration else ""
    sid = escape(session["session_id"] or "")

    chips = []
    if duration_str:
        chips.append(f'<span class="chip">{duration_str}</span>')
    chips_html = " ".join(chips)

    msgs = [render_message(m) for m in session["messages"]]
    msgs_html = "\n".join(m for m in msgs if m)

    return f"""<div class="detail-panel" data-sid="{sid}">
        <div class="detail-header">
            <span class="detail-date">{escape(date_part)}</span>
            {chips_html}
            <span class="detail-sid">{sid[:8]}</span>
        </div>
        <div class="messages">{msgs_html}</div>
    </div>"""


def render_stats_bar(conn):
    """Generate HTML for the collapsible stats bar."""
    from stats import compute_stats

    stats = compute_stats(conn)
    total_end = stats["sessions_with_summary"] + stats["sessions_without_summary"]
    pct_summarized = round(100 * stats["sessions_with_summary"] / max(total_end, 1))

    cards = (
        '<div class="stats-cards">'
        f'<div class="stat-card"><div class="stat-value">{stats["total_sessions"]}</div><div class="stat-label">Sessions</div></div>'
        f'<div class="stat-card"><div class="stat-value">{stats["total_messages"]}</div><div class="stat-label">Messages</div></div>'
        f'<div class="stat-card"><div class="stat-value">{stats["avg_duration_min"]}m</div><div class="stat-label">Avg Duration</div></div>'
        f'<div class="stat-card"><div class="stat-value">{pct_summarized}%</div><div class="stat-label">Summarized</div></div>'
        '</div>'
    )

    # Top 5 tools — horizontal bars
    top_tools = dict(list(stats["tool_usage"].items())[:5])
    tools_html = ""
    if top_tools:
        max_tool = max(top_tools.values())
        bars = ""
        for name, count in top_tools.items():
            pct = round(100 * count / max(max_tool, 1))
            bars += (
                f'<div class="tool-row"><span class="tool-name">{escape(name)}</span>'
                f'<div class="tool-bar-track"><div class="tool-bar-fill" style="width:{pct}%"></div></div>'
                f'<span class="tool-count">{count}</span></div>'
            )
        tools_html = f'<div class="stats-chart"><div class="chart-title">Top Tools</div>{bars}</div>'

    # 14-day activity — vertical bars
    days = stats["activity_by_day"]
    max_day = max(days.values()) if any(days.values()) else 1
    day_bars = ""
    for day, count in days.items():
        pct = round(100 * count / max(max_day, 1))
        day_bars += (
            f'<div class="day-col"><div class="day-bar" style="height:{max(pct, 2)}%"'
            f' title="{day}: {count}"></div><span class="day-label">{day[8:]}</span></div>'
        )
    activity_html = (
        f'<div class="stats-chart"><div class="chart-title">Activity (14 days)</div>'
        f'<div class="day-chart">{day_bars}</div></div>'
    )

    return (
        f'<div class="stats-bar" id="stats-bar">{cards}'
        f'<div class="stats-charts">{tools_html}{activity_html}</div></div>'
    )


def render_page(sidebar_html, details_html, stats_html, revision):
    """Load the HTML template and fill in placeholders."""
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = f.read()

    return (
        template
        .replace("{{LOGO_URL}}", LOGO_URL)
        .replace("{{STATS_BAR}}", stats_html)
        .replace("{{SIDEBAR}}", sidebar_html)
        .replace("{{DETAILS}}", details_html)
        .replace("{{REVISION}}", str(revision))
    )


def main():
    require_db()
    reconfigure_stdout()

    conn = get_db()
    revision = conn.execute("SELECT MAX(id) FROM imprints").fetchone()[0] or 0

    # Skip regeneration if dashboard is already current AND the template hasn't changed
    if os.path.exists(HTML_PATH):
        with open(HTML_PATH, "r", encoding="utf-8") as f:
            head = f.read(1024)
        template_modified = os.path.getmtime(TEMPLATE_PATH) > os.path.getmtime(HTML_PATH)
        script_modified = os.path.getmtime(__file__) > os.path.getmtime(HTML_PATH)
        stats_path = os.path.join(SCRIPT_DIR, "stats.py")
        stats_modified = os.path.exists(stats_path) and os.path.getmtime(stats_path) > os.path.getmtime(HTML_PATH)
        if f'content="{revision}"' in head and not template_modified and not script_modified and not stats_modified:
            conn.close()
            print(f"Dashboard up to date: {HTML_PATH}")
            return

    sessions = get_sessions(conn)

    sidebar_html = "\n".join(render_sidebar_item(s, i) for i, s in enumerate(sessions))
    details_html = "\n".join(render_detail_panel(s) for s in sessions)
    stats_html = render_stats_bar(conn)

    conn.close()

    html = render_page(sidebar_html, details_html, stats_html, revision)
    os.makedirs(os.path.dirname(HTML_PATH), exist_ok=True)
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Dashboard generated: {HTML_PATH}")


if __name__ == "__main__":
    main()
