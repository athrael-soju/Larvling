"""
Larvling Dashboard - generates a static HTML dashboard from larvling.db.
Two-panel layout: session list on left, conversation on right.
Zero dependencies: just sqlite3 + Python string templating.
"""

import os
import sys
from html import escape

from db import DB_PATH, get_db, parse_meta, require_db, reconfigure_stdout

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(SCRIPT_DIR, "dashboard.html.template")
LOGO_URL = "https://raw.githubusercontent.com/athrael-soju/Larvling/main/larvling.png"

HTML_PATH = os.path.join(os.path.dirname(DB_PATH), "dashboard.html")


def get_revision(conn):
    """Compute a revision number from table states."""
    imp = conn.execute("SELECT MAX(id) FROM imprints").fetchone()[0] or 0
    ref = conn.execute("SELECT MAX(id) FROM reflections").fetchone()[0] or 0
    enc = conn.execute("SELECT COUNT(*) FROM encounters").fetchone()[0] or 0
    return imp + ref + enc


def get_sessions(conn):
    """Get sessions with their messages and reflection data, newest first.

    Messages within each session are in reverse chronological order (DESC)
    so the conversation panel shows the most recent exchange at the top.
    """
    encounters = conn.execute(
        """
        SELECT e.id, e.started_at, e.ended_at, e.duration_min,
               r.title, r.agent_summary, r.exchange_count
        FROM encounters e
        LEFT JOIN reflections r ON r.encounter_id = e.id
        ORDER BY e.started_at DESC
        """
    ).fetchall()

    sessions = []
    for enc in encounters:
        messages = conn.execute(
            "SELECT * FROM imprints WHERE encounter_id = ? ORDER BY id DESC",
            (enc["id"],),
        ).fetchall()

        user_count = sum(1 for m in messages if m["role"] == "user")
        agent_count = sum(1 for m in messages if m["role"] == "assistant")
        if user_count + agent_count == 0:
            continue

        sessions.append(
            {
                "session_id": enc["id"],
                "started": enc["started_at"],
                "ended": enc["ended_at"],
                "msg_count": user_count + agent_count,
                "messages": messages,
                "end_meta": {
                    "duration_min": enc["duration_min"],
                    "title": enc["title"],
                    "agent_summary": enc["agent_summary"],
                },
            }
        )

    return sessions


def render_message(msg):
    """Render a single message as a chat bubble."""
    role = msg["role"]
    content = escape(msg["content"] or "")
    timestamp = msg["timestamp"] or ""
    time_short = timestamp.split(" ")[-1][:5] if " " in timestamp else timestamp[:5]

    meta = parse_meta(msg["metadata"])

    if role == "user":
        return f"""<div class="msg msg-user">
            <div class="msg-header"><span class="msg-role">You</span><span class="msg-time">{escape(time_short)}</span></div>
            <div class="msg-body">{content}</div>
        </div>"""
    elif role == "assistant":
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
    else:
        return f"""<div class="msg msg-system">
            <span class="msg-time">{escape(time_short)}</span> {escape(role)}: {content}
        </div>"""


def render_sidebar_item(session, index):
    """Render a compact sidebar entry for a session."""
    meta = session["end_meta"]
    started = session["started"] or "?"
    date_part = started.split(" ")[0] if " " in started else started
    time_part = started.split(" ")[-1][:5] if " " in started else ""

    duration = meta.get("duration_min") or 0
    duration_str = f"{duration}m" if duration else ""
    summary = escape(meta.get("title") or f"{session['msg_count']} messages")
    active = "active" if index == 0 else ""
    sid = escape(session["session_id"] or "")

    ended = session["ended"] or started
    agent_summary = meta.get("agent_summary") or ""
    summary_item = (
        f'<div class="menu-item si-summary-dl" data-summary="{escape(agent_summary)}">&#x1F4CB; Download summary</div>'
        if agent_summary
        else ""
    )
    return f"""<div class="sidebar-item {active}" data-sid="{sid}" data-started="{escape(started)}" data-ended="{escape(ended)}" data-msgs="{session['msg_count']}" data-duration="{duration}">
        <div class="si-top">
            <span class="si-date">{escape(date_part)}</span>
            <span class="si-time">{escape(time_part)}</span>
            <span class="si-menu-wrap">
                <span class="si-menu-btn" title="Actions">&#x22EF;</span>
                <div class="si-menu">
                    {summary_item}
                    <div class="menu-item si-export-dl">&#x1F4BE; Export session</div>
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


def render_page(sidebar_html, details_html, revision):
    """Load the HTML template and fill in placeholders."""
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = f.read()

    return (
        template.replace("{{LOGO_URL}}", LOGO_URL)
        .replace("{{SIDEBAR}}", sidebar_html)
        .replace("{{DETAILS}}", details_html)
        .replace("{{REVISION}}", str(revision))
    )


def main():
    require_db()
    reconfigure_stdout()

    conn = get_db()
    revision = get_revision(conn)

    # Skip regeneration if dashboard is already current AND the template hasn't changed
    if os.path.exists(HTML_PATH):
        with open(HTML_PATH, "r", encoding="utf-8") as f:
            head = f.read(1024)
        template_modified = os.path.getmtime(TEMPLATE_PATH) > os.path.getmtime(
            HTML_PATH
        )
        script_modified = os.path.getmtime(__file__) > os.path.getmtime(HTML_PATH)
        if (
            f'content="{revision}"' in head
            and not template_modified
            and not script_modified
        ):
            conn.close()
            print(f"Dashboard up to date: {HTML_PATH}")
            return

    sessions = get_sessions(conn)

    sidebar_html = "\n".join(render_sidebar_item(s, i) for i, s in enumerate(sessions))
    details_html = "\n".join(render_detail_panel(s) for s in sessions)

    conn.close()

    html = render_page(sidebar_html, details_html, revision)
    os.makedirs(os.path.dirname(HTML_PATH), exist_ok=True)
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Dashboard generated: {HTML_PATH}")


if __name__ == "__main__":
    main()
