"""
Larvling Dashboard - generates a static HTML dashboard from larvling.db.
Two-panel layout: session list on left, conversation on right.
Zero dependencies: just sqlite3 + Python string templating.
"""

import json
import os
import sys
from html import escape

from db import DB_PATH, open_db, parse_meta, require_db, reconfigure_stdout

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(SCRIPT_DIR, "dashboard.html.template")
LOGO_URL = "https://raw.githubusercontent.com/athrael-soju/Larvling/main/larvling.png"

HTML_PATH = os.path.join(os.path.dirname(DB_PATH), "dashboard.html")
REVISION_PATH = os.path.join(os.path.dirname(DB_PATH), "larvling-revision")


def get_revision(conn):
    """Compute a revision number from table states."""
    msg = conn.execute("SELECT MAX(id) FROM messages").fetchone()[0] or 0
    sess = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] or 0
    loop_rev = conn.execute(
        "SELECT COALESCE(MAX(id),0) + COALESCE(SUM(iteration),0) FROM loops"
    ).fetchone()[0] or 0
    return msg + sess + loop_rev


def get_sessions(conn):
    """Get sessions with their messages and summary data, newest first.

    Messages within each session are in reverse chronological order (DESC)
    so the conversation panel shows the most recent exchange at the top.
    """
    sessions_rows = conn.execute(
        """
        SELECT id, started_at, ended_at, duration_min,
               title, agent_summary, exchange_count
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
                },
            }
        )

    return sessions


def get_loops(conn):
    """Get all loops, newest first."""
    return conn.execute(
        """
        SELECT id, session_id, prompt, status, iteration,
               max_iterations, completion_promise, started_at,
               ended_at, outcome
        FROM loops
        ORDER BY started_at DESC
        """
    ).fetchall()


def render_loop_sidebar_item(loop, index):
    """Render a compact sidebar entry for a loop."""
    status = loop["status"]
    iteration = loop["iteration"]
    max_iter = loop["max_iterations"]
    iter_str = f"{iteration}/{max_iter}" if max_iter > 0 else str(iteration)
    prompt_preview = escape((loop["prompt"] or "")[:80])
    started = loop["started_at"] or "?"
    date_part = started.split(" ")[0] if " " in started else started
    time_part = started.split(" ")[-1][:5] if " " in started else ""
    lid = loop["id"]

    return f"""<div class="sidebar-item loop-entry" data-lid="{lid}" data-tab="loops">
        <div class="si-top">
            <span class="si-date">{escape(date_part)}</span>
            <span class="si-time">{escape(time_part)}</span>
            <span class="loop-status loop-status-{escape(status)}">{escape(status)}</span>
        </div>
        <div class="si-summary">{prompt_preview}</div>
        <div class="si-meta">
            <span>iter {iter_str}</span>
        </div>
    </div>"""


def render_loop_detail(loop):
    """Render the detail panel for a loop."""
    status = loop["status"]
    iteration = loop["iteration"]
    max_iter = loop["max_iterations"]
    iter_str = f"{iteration}/{max_iter}" if max_iter > 0 else str(iteration)
    started = loop["started_at"] or "?"
    date_part = started.split(" ")[0] if " " in started else started
    prompt = escape(loop["prompt"] or "")
    lid = loop["id"]

    # Duration
    duration_html = ""
    if loop["ended_at"] and loop["started_at"]:
        duration_html = f'<span class="chip">ended {escape(loop["ended_at"][:16])}</span>'

    # Progress bar
    progress_html = ""
    if max_iter > 0:
        pct = min(100, int(iteration / max_iter * 100))
        pulse = " loop-progress-active" if status == "active" else ""
        progress_html = f"""<div class="loop-progress-wrap">
            <div class="loop-progress{pulse}" style="width:{pct}%"></div>
        </div>"""

    # Promise
    promise_html = ""
    if loop["completion_promise"]:
        promise_html = f'<div class="loop-section"><strong>Completion promise:</strong> <code>{escape(loop["completion_promise"])}</code></div>'

    # Outcome
    outcome_html = ""
    if loop["outcome"]:
        outcome_html = f'<div class="loop-section"><strong>Outcome:</strong> {escape(loop["outcome"])}</div>'

    return f"""<div class="detail-panel loop-detail" data-lid="{lid}" data-tab="loops">
        <div class="detail-header">
            <span class="detail-date">{escape(date_part)}</span>
            <span class="loop-status loop-status-{escape(status)}">{escape(status)}</span>
            <span class="chip">iter {iter_str}</span>
            {duration_html}
            <span class="detail-sid">loop #{lid}</span>
        </div>
        {progress_html}
        <div class="loop-body">
            <div class="loop-prompt">{prompt}</div>
            {promise_html}
            {outcome_html}
        </div>
    </div>"""


def render_loop_banner(loops):
    """Render a banner for any active loop."""
    active = [l for l in loops if l["status"] == "active"]
    if not active:
        return ""
    loop = active[0]
    iteration = loop["iteration"]
    max_iter = loop["max_iterations"]
    iter_str = f"{iteration}/{max_iter}" if max_iter > 0 else str(iteration)
    prompt_preview = escape((loop["prompt"] or "")[:60])
    return f"""<div class="loop-banner">
        <span class="loop-banner-pulse"></span>
        <span class="loop-banner-text">Loop active &mdash; iter {iter_str} &mdash; {prompt_preview}</span>
    </div>"""


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
    meta = session["meta"]
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


def get_plugin_version():
    """Read the plugin version from plugin.json. Returns '?' on failure."""
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    plugin_json = os.path.join(plugin_root, ".claude-plugin", "plugin.json")
    try:
        with open(plugin_json, "r", encoding="utf-8") as f:
            return json.load(f).get("version", "?")
    except Exception:
        return "?"


def render_page(sidebar_html, details_html, revision, **kwargs):
    """Load the HTML template and fill in placeholders."""
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = f.read()

    return (
        template.replace("{{LOGO_URL}}", LOGO_URL)
        .replace("{{VERSION}}", get_plugin_version())
        .replace("{{SIDEBAR}}", sidebar_html)
        .replace("{{DETAILS}}", details_html)
        .replace("{{LOOP_SIDEBAR}}", kwargs.get("loop_sidebar", ""))
        .replace("{{LOOP_DETAILS}}", kwargs.get("loop_details", ""))
        .replace("{{LOOP_BANNER}}", kwargs.get("loop_banner", ""))
        .replace("{{REVISION}}", str(revision))
    )


def main():
    require_db()
    reconfigure_stdout()

    with open_db() as conn:
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
                with open(REVISION_PATH, "w", encoding="utf-8") as f:
                    f.write(str(revision))
                print(f"Dashboard up to date: {HTML_PATH}", file=sys.stderr)
                return

        sessions = get_sessions(conn)
        loops = get_loops(conn)

        sidebar_html = "\n".join(
            render_sidebar_item(s, i) for i, s in enumerate(sessions)
        )
        details_html = "\n".join(render_detail_panel(s) for s in sessions)

        loop_sidebar = "\n".join(
            render_loop_sidebar_item(l, i) for i, l in enumerate(loops)
        )
        loop_details = "\n".join(render_loop_detail(l) for l in loops)
        loop_banner = render_loop_banner(loops)

    html = render_page(
        sidebar_html, details_html, revision,
        loop_sidebar=loop_sidebar,
        loop_details=loop_details,
        loop_banner=loop_banner,
    )
    os.makedirs(os.path.dirname(HTML_PATH), exist_ok=True)
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    with open(REVISION_PATH, "w", encoding="utf-8") as f:
        f.write(str(revision))

    print(f"Dashboard generated: {HTML_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
