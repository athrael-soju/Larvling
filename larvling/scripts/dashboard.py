"""Larvling Dashboard - generates a static HTML dashboard from larvling.db."""

import os
import sys
from html import escape
from urllib.request import urlopen, Request
from urllib.error import URLError

from db import DB_PATH, get_plugin_version, open_db, has_table, parse_meta, require_db, reconfigure_stdout, log

TEMPLATE_URL = "https://raw.githubusercontent.com/athrael-soju/Larvling/main/dashboard.html.template"
TEMPLATE_CACHE = os.path.join(os.path.dirname(DB_PATH), "dashboard.html.template")
LOGO_URL = "https://raw.githubusercontent.com/athrael-soju/Larvling/main/larvling.png"

HTML_PATH = os.path.join(os.path.dirname(DB_PATH), "dashboard.html")


def get_revision(conn):
    """Revision = MAX(messages.id) + COUNT(sessions) + COUNT(topics) + COUNT(statements) + COUNT(tasks)."""
    msg = conn.execute("SELECT MAX(id) FROM messages").fetchone()[0] or 0
    sess = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] or 0
    topics = 0
    if has_table(conn, "topics"):
        topics = conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0] or 0
    stmts = 0
    if has_table(conn, "statements"):
        stmts = conn.execute("SELECT COUNT(*) FROM statements").fetchone()[0] or 0
    tasks = 0
    if has_table(conn, "tasks"):
        tasks = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] or 0
    return msg + sess + topics + stmts + tasks


def get_sessions(conn):
    """Get sessions with messages, newest first (messages DESC within each)."""
    sessions_rows = conn.execute(
        """
        SELECT id, started_at, ended_at, duration_min,
               title, agent_summary, exchange_count,
               tags, quality_signals
        FROM sessions
        ORDER BY started_at DESC
        """
    ).fetchall()

    sessions = []
    for sess in sessions_rows:
        messages = conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY id DESC",
            (sess["id"],),
        ).fetchall()

        user_count = sum(1 for m in messages if m["role"] == "user")
        agent_count = sum(1 for m in messages if m["role"] == "assistant")
        if user_count + agent_count == 0:
            continue

        sessions.append(
            {
                "session_id": sess["id"],
                "started": sess["started_at"],
                "ended": sess["ended_at"],
                "msg_count": user_count + agent_count,
                "messages": messages,
                "meta": {
                    "duration_min": sess["duration_min"],
                    "title": sess["title"],
                    "agent_summary": sess["agent_summary"],
                    "tags": sess["tags"],
                    "quality_signals": sess["quality_signals"],
                },
            }
        )

    return sessions


def render_message(msg):
    """Render a message as a chat bubble."""
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

        sentiment = meta.get("sentiment", "")
        sentiment_html = ""
        if sentiment:
            sentiment_class = {
                "satisfied": "positive", "curious": "positive",
                "focused": "neutral-s", "neutral": "neutral-s",
                "frustrated": "negative",
            }.get(sentiment, "neutral-s")
            sentiment_html = f'<span class="sentiment-dot {sentiment_class}" title="{escape(sentiment)}"></span>'

        action_items = meta.get("action_items", [])
        actions_html = ""
        if action_items:
            items = " ".join(
                f'<span class="action-badge">{escape(str(a))}</span>'
                for a in action_items[:5]
            )
            actions_html = f'<div class="msg-actions">{items}</div>'

        return f"""<div class="msg msg-agent">
            <div class="msg-header"><span class="msg-role">Agent</span>{sentiment_html}<span class="msg-time">{escape(time_short)}</span></div>
            <div class="msg-body">{content}</div>
            {tools_html}
            {actions_html}
        </div>"""
    else:
        return f"""<div class="msg msg-system">
            <span class="msg-time">{escape(time_short)}</span> {escape(role)}: {content}
        </div>"""


def render_sidebar_item(session, index):
    """Sidebar entry for a session."""
    meta = session["meta"]
    started = session["started"] or "?"
    date_part = started.split(" ")[0] if " " in started else started
    time_part = started.split(" ")[-1][:5] if " " in started else ""

    duration = meta.get("duration_min") or 0
    duration_str = f"{duration}m" if duration else ""
    summary = escape(meta.get("title") or f"{session['msg_count']} messages")
    active = "active" if index == 0 else ""
    sid = escape(session["session_id"] or "")

    ended = session["ended"] or started

    topics = meta.get("tags") or ""
    topics_html = ""
    if topics:
        topic_list = [t.strip() for t in topics.split(",") if t.strip()][:4]
        topic_chips = " ".join(
            f'<span class="topic-chip">{escape(t)}</span>' for t in topic_list
        )
        topics_html = f'<div class="si-topics">{topic_chips}</div>'

    topics_attr = f' data-topics="{escape(topics)}"' if topics else ""

    return f"""<div class="sidebar-item {active}" data-sid="{sid}" data-started="{escape(started)}" data-ended="{escape(ended)}" data-msgs="{session['msg_count']}" data-duration="{duration}"{topics_attr}>
        <div class="si-top">
            <span class="si-date">{escape(date_part)}</span>
            <span class="si-time">{escape(time_part)}</span>
        </div>
        <div class="si-summary">{summary}</div>
        {topics_html}
        <div class="si-meta">
            <span>{session['msg_count']} msgs</span>
            {f'<span>{duration_str}</span>' if duration_str else ''}
        </div>
    </div>"""


def render_detail_panel(session):
    """Full conversation panel for a session."""
    meta = session["meta"]
    started = session["started"] or "?"
    date_part = started.split(" ")[0] if " " in started else started

    duration = meta.get("duration_min")
    duration_str = f"{duration} min" if duration else ""
    sid = escape(session["session_id"] or "")

    chips = []
    if duration_str:
        chips.append(f'<span class="chip">{duration_str}</span>')

    topics = meta.get("tags") or ""
    if topics:
        topic_list = [t.strip() for t in topics.split(",") if t.strip()][:6]
        for t in topic_list:
            chips.append(f'<span class="chip topic-chip">{escape(t)}</span>')

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


def get_template():
    """Fetch template from GitHub, cache locally. Fall back to cache if fetch fails."""
    os.makedirs(os.path.dirname(TEMPLATE_CACHE), exist_ok=True)

    try:
        req = Request(TEMPLATE_URL, headers={"User-Agent": "Larvling"})
        with urlopen(req, timeout=10) as resp:
            template = resp.read().decode("utf-8")
        with open(TEMPLATE_CACHE, "w", encoding="utf-8") as f:
            f.write(template)
        return template
    except (URLError, OSError, TimeoutError) as e:
        log("template_error", error=str(e))

    if os.path.exists(TEMPLATE_CACHE):
        with open(TEMPLATE_CACHE, "r", encoding="utf-8") as f:
            return f.read()

    raise RuntimeError("No template available — fetch failed and no cached copy exists")


def render_page(sidebar_html, details_html, revision):
    """Fill template placeholders."""
    template = get_template()

    return (
        template.replace("{{LOGO_URL}}", LOGO_URL)
        .replace("{{VERSION}}", get_plugin_version())
        .replace("{{SIDEBAR}}", sidebar_html)
        .replace("{{DETAILS}}", details_html)
        .replace("{{REVISION}}", str(revision))
    )


def main():
    if os.environ.get("LARVLING_INTERNAL"):
        return
    require_db()
    reconfigure_stdout()

    with open_db() as conn:
        revision = get_revision(conn)
        sessions = get_sessions(conn)

        sidebar_html = "\n".join(
            render_sidebar_item(s, i) for i, s in enumerate(sessions)
        )
        details_html = "\n".join(render_detail_panel(s) for s in sessions)

    html = render_page(sidebar_html, details_html, revision)
    os.makedirs(os.path.dirname(HTML_PATH), exist_ok=True)
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Dashboard generated: {HTML_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
