"""Larvling Dashboard - generates a static HTML dashboard from larvling.db."""

import asyncio
import json
import os
import sys
from html import escape

from db import DB_PATH, get_plugin_version, open_db, has_table, parse_meta, require_db, reconfigure_stdout, call_model, _log

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(SCRIPT_DIR, "dashboard.html.template")
LOGO_URL = "https://raw.githubusercontent.com/athrael-soju/Larvling/main/larvling.png"

HTML_PATH = os.path.join(os.path.dirname(DB_PATH), "dashboard.html")


def get_revision(conn):
    """Revision = MAX(messages.id) + COUNT(sessions) + COUNT(facts)."""
    msg = conn.execute("SELECT MAX(id) FROM messages").fetchone()[0] or 0
    sess = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] or 0
    facts = 0
    if has_table(conn, "facts"):
        facts = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] or 0
    return msg + sess + facts


def get_sessions(conn):
    """Get sessions with messages, newest first (messages DESC within each)."""
    sessions_rows = conn.execute(
        """
        SELECT id, started_at, ended_at, duration_min,
               title, agent_summary, exchange_count,
               topics, quality_signals
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
                    "topics": sess["topics"],
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

    topics = meta.get("topics") or ""
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

    topics = meta.get("topics") or ""
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


# ---------------------------------------------------------------------------
# Knowledge Graph data structuring via Agent SDK
# ---------------------------------------------------------------------------

GRAPH_PROMPT = """\
You are structuring knowledge facts into a graph. Each fact becomes a node.
Connect facts that share semantic relationships (same topic, related concepts,
same domain, causal links, etc.).

## Facts
{facts_text}

## Instructions
- Every fact MUST appear as a node (use the fact's DB id as node id).
- Create edges between semantically related facts. Label each edge with the
  relationship type (e.g. "same topic", "related", "preference", "builds on").
- Weight edges 1-3 (1=weak, 3=strong relationship).
- If there are no meaningful connections, return nodes with an empty edges array.

Return the graph structure as JSON."""

GRAPH_SCHEMA = {
    "type": "object",
    "properties": {
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "label": {"type": "string"},
                    "domain": {"type": "string"},
                    "claim": {"type": "string"},
                },
                "required": ["id", "label", "domain", "claim"],
            },
        },
        "edges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "integer"},
                    "target": {"type": "integer"},
                    "label": {"type": "string"},
                    "weight": {"type": "integer"},
                },
                "required": ["source", "target", "label", "weight"],
            },
        },
    },
    "required": ["nodes", "edges"],
}

EMPTY_GRAPH = {"nodes": [], "edges": []}


def get_graph_data(conn):
    """Structure facts into graph nodes and edges via Agent SDK."""
    if not has_table(conn, "facts"):
        return EMPTY_GRAPH

    rows = conn.execute(
        "SELECT id, claim, domain, tags FROM facts ORDER BY id"
    ).fetchall()

    if not rows:
        return EMPTY_GRAPH

    facts_text = "\n".join(
        f"- [id={r['id']}] ({r['domain']}) {r['claim']} (tags: {r['tags']})"
        for r in rows
    )

    try:
        prompt = GRAPH_PROMPT.format(facts_text=facts_text)
        result = asyncio.run(
            call_model(
                prompt,
                output_format={"type": "json_schema", "schema": GRAPH_SCHEMA},
            )
        )
    except Exception as e:
        _log(f"Graph structuring failed: {e}")
        return EMPTY_GRAPH

    if not isinstance(result, dict):
        _log(f"Unexpected graph result type: {type(result)}")
        return EMPTY_GRAPH

    return result


def render_page(sidebar_html, details_html, revision, graph_json="{}"):
    """Fill template placeholders."""
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = f.read()

    return (
        template.replace("{{LOGO_URL}}", LOGO_URL)
        .replace("{{VERSION}}", get_plugin_version())
        .replace("{{SIDEBAR}}", sidebar_html)
        .replace("{{DETAILS}}", details_html)
        .replace("{{REVISION}}", str(revision))
        .replace("{{GRAPH_JSON}}", graph_json)
    )


def main():
    if os.environ.get("LARVLING_INTERNAL"):
        return
    require_db()
    reconfigure_stdout()

    with open_db() as conn:
        revision = get_revision(conn)

        # Skip regeneration if dashboard is already current AND the template hasn't changed
        if os.path.exists(HTML_PATH):
            with open(HTML_PATH, "r", encoding="utf-8") as f:
                head = f.read(2048)
            template_modified = os.path.getmtime(TEMPLATE_PATH) > os.path.getmtime(
                HTML_PATH
            )
            script_modified = os.path.getmtime(__file__) > os.path.getmtime(HTML_PATH)
            if (
                f'content="{revision}"' in head
                and not template_modified
                and not script_modified
            ):
                print(f"Dashboard up to date: {HTML_PATH}", file=sys.stderr)
                return

        sessions = get_sessions(conn)

        sidebar_html = "\n".join(
            render_sidebar_item(s, i) for i, s in enumerate(sessions)
        )
        details_html = "\n".join(render_detail_panel(s) for s in sessions)

        graph_data = get_graph_data(conn)

    graph_json = json.dumps(graph_data)
    html = render_page(sidebar_html, details_html, revision, graph_json)
    os.makedirs(os.path.dirname(HTML_PATH), exist_ok=True)
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Dashboard generated: {HTML_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
