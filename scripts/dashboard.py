"""
Larvling Dashboard — generates a static HTML dashboard from larvling.db.
Two-panel layout: session list on left, conversation on right.
Zero dependencies: just sqlite3 + Python string templating.
"""

import json
import os
import sqlite3
import sys
from html import escape

from db import DB_PATH, get_db

HTML_PATH = os.path.join(os.path.dirname(DB_PATH), "dashboard.html")


def get_sessions(conn):
    """Get audit entries grouped by session, newest first."""
    cur = conn.execute(
        """
        SELECT session_id, MIN(timestamp) as started, MAX(timestamp) as ended,
               COUNT(*) as msg_count
        FROM audit
        WHERE session_id IS NOT NULL
        GROUP BY session_id
        ORDER BY started DESC
    """
    )
    sessions = []
    for row in cur.fetchall():
        sid = row["session_id"]
        messages = conn.execute(
            "SELECT * FROM audit WHERE session_id = ? ORDER BY id DESC",
            (sid,),
        ).fetchall()
        end_meta = {}
        for m in messages:
            if m["event_type"] == "session_end" and m["metadata"]:
                try:
                    end_meta = json.loads(m["metadata"])
                except (json.JSONDecodeError, TypeError):
                    pass
        user_count = sum(1 for m in messages if m["event_type"] == "user_message")
        agent_count = sum(1 for m in messages if m["event_type"] == "agent_message")
        if user_count + agent_count == 0:
            continue  # Skip sessions with no conversation messages
        sessions.append(
            {
                "session_id": sid,
                "started": row["started"],
                "ended": row["ended"],
                "msg_count": user_count + agent_count,
                "messages": messages,
                "end_meta": end_meta,
            }
        )
    return sessions


def render_message(msg):
    """Render a single message as a chat bubble."""
    event = msg["event_type"]
    content = escape(msg["content"] or "")
    timestamp = msg["timestamp"] or ""
    time_short = timestamp.split(" ")[-1][:5] if " " in timestamp else timestamp[:5]

    meta = {}
    if msg["metadata"]:
        try:
            meta = json.loads(msg["metadata"])
        except (json.JSONDecodeError, TypeError):
            pass

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
    summary = f"{session['msg_count']} messages"
    active = "active" if index == 0 else ""
    sid = escape(session["session_id"] or "")

    return f"""<div class="sidebar-item {active}" data-sid="{sid}" data-started="{escape(started)}" data-msgs="{session['msg_count']}" data-duration="{duration}">
        <div class="si-top">
            <span class="si-date">{escape(date_part)}</span>
            <span class="si-time">{escape(time_part)}</span>
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


def render_page(sidebar_html, details_html):
    """Render the full two-panel dashboard page."""
    return (
        """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Larvling Dashboard</title>
<style>
    :root { --bg: #1a1610; --surface: #2a2318; --border: #3d3428; --text: #f5f0e6; --muted: #a09282; --accent: #f5a623; --accent2: #f0c850; --red: #e86530; --pink: #e8668a; --user: #2e2215; --agent: #241f15; --sidebar-w: 260px; }
    * { margin: 0; padding: 0; box-sizing: border-box; scrollbar-width: thin; scrollbar-color: var(--border) transparent; }
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: var(--muted); }
    html, body { height: 100%; overflow: hidden; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; background: var(--bg); color: var(--text); display: flex; flex-direction: column; }

    /* Top bar */
    .topbar { display: flex; align-items: center; gap: 1rem; padding: 0.75rem 1.25rem; border-bottom: 2px solid var(--accent); background: linear-gradient(180deg, #2a2318 0%, var(--bg) 100%); flex-shrink: 0; }
    .logo { width: 32px; height: 32px; border-radius: 6px; }
    .topbar h1 { font-size: 1.1rem; color: var(--accent); }
    .topbar .meta { color: var(--muted); font-size: 0.75rem; }
    .topbar-right { margin-left: auto; }
    .topbar-right input { width: 220px; padding: 0.35rem 0.75rem; background: var(--surface); border: 1px solid var(--border); border-radius: 5px; color: var(--text); font-size: 0.8rem; outline: none; }
    .topbar-right input:focus { border-color: var(--accent); }
    .topbar-right input::placeholder { color: var(--muted); }

    /* Layout */
    .layout { display: flex; flex: 1; min-height: 0; }

    /* Sidebar */
    .sidebar { width: var(--sidebar-w); border-right: 1px solid var(--border); display: flex; flex-direction: column; flex-shrink: 0; }
    .sidebar-controls { padding: 0.5rem 0.6rem; border-bottom: 1px solid var(--border); display: flex; gap: 0.35rem; flex-shrink: 0; }
    .sidebar-controls select { flex: 1; padding: 0.25rem 0.3rem; background: var(--surface); border: 1px solid var(--border); border-radius: 4px; color: var(--text); font-size: 0.7rem; outline: none; cursor: pointer; appearance: none; -webkit-appearance: none; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='8' height='5'%3E%3Cpath d='M0 0l4 5 4-5z' fill='%239a9090'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 0.4rem center; padding-right: 1.2rem; }
    .sidebar-controls select:focus { border-color: var(--accent); }
    .sidebar-controls select option { background: var(--surface); color: var(--text); }
    .sidebar-list { overflow-y: auto; flex: 1; }
    .sidebar-item { padding: 0.65rem 1rem; border-bottom: 1px solid var(--border); cursor: pointer; }
    .sidebar-item:hover { background: var(--surface); }
    .sidebar-item.active { background: var(--surface); border-left: 3px solid var(--accent); }
    .si-top { display: flex; justify-content: space-between; align-items: center; }
    .si-date { font-weight: 600; font-size: 0.85rem; }
    .si-time { color: var(--muted); font-size: 0.75rem; }
    .si-summary { color: var(--muted); font-size: 0.8rem; margin-top: 0.2rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .si-meta { display: flex; gap: 0.5rem; margin-top: 0.2rem; font-size: 0.7rem; color: var(--muted); }

    /* Detail panel */
    .main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
    .detail-panel { flex: 1; display: none; flex-direction: column; min-height: 0; }
    .detail-panel.active { display: flex; }
    .detail-header { display: flex; align-items: center; gap: 0.5rem; padding: 0.65rem 1.25rem; border-bottom: 1px solid var(--border); flex-shrink: 0; }
    .detail-date { font-weight: 600; font-size: 0.95rem; }
    .detail-sid { color: var(--muted); font-size: 0.75rem; font-family: monospace; margin-left: auto; }
    .chip { background: rgba(245, 166, 35, 0.1); border: 1px solid rgba(245, 166, 35, 0.2); border-radius: 12px; padding: 0.1rem 0.5rem; font-size: 0.7rem; color: var(--accent2); }

    .no-session { flex: 1; display: flex; align-items: center; justify-content: center; color: var(--muted); font-size: 0.9rem; }

    /* Messages */
    .messages { flex: 1; display: flex; flex-direction: column; gap: 0.5rem; overflow-y: auto; padding: 1rem 1.25rem; }
    .msg { padding: 0.5rem 0.75rem; border-radius: 8px; max-width: 95%; flex-shrink: 0; transition: opacity 0.15s; }
    .msg.search-dim { display: none; }
    .msg.search-hit { border-left: 2px solid var(--accent); }
    .msg.search-hit mark { background: rgba(245, 166, 35, 0.3); color: inherit; border-radius: 2px; padding: 0 1px; }
    .msg-user { background: var(--user); align-self: flex-end; }
    .msg-agent { background: var(--agent); align-self: flex-start; }
    .msg-system { color: var(--muted); font-size: 0.8rem; align-self: center; font-style: italic; padding: 0.25rem 0; }
    .msg-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.25rem; }
    .msg-role { font-weight: 600; font-size: 0.8rem; }
    .msg-user .msg-role { color: var(--accent); }
    .msg-user .msg-header { flex-direction: row-reverse; }
    .msg-agent .msg-role { color: var(--accent2); }
    .msg-time { color: var(--muted); font-size: 0.7rem; }
    .msg-body { font-size: 0.85rem; line-height: 1.5; word-break: break-word; max-height: 200px; overflow: hidden; position: relative; cursor: pointer; }
    .msg-body.expanded { max-height: none; }
    .msg-body.truncated::after { content: ''; position: absolute; bottom: 0; left: 0; right: 0; height: 3rem; background: linear-gradient(transparent 0%, var(--agent) 80%); pointer-events: none; }
    .msg-body.truncated::before { content: '\u25bc  Show more'; position: absolute; bottom: 0; left: 0; right: 0; z-index: 1; text-align: center; font-size: 0.7rem; color: var(--accent); padding: 0.3rem 0; pointer-events: none; opacity: 0; transition: opacity 0.15s; }
    .msg-body.truncated:hover::before { opacity: 1; }
    .msg-body.truncated:hover { box-shadow: 0 0 0 1px var(--accent) inset; border-radius: 4px; }
    .msg-body.expanded::after, .msg-body.expanded::before { display: none; }
    .msg-body p { margin: 0 0 0.4rem 0; }
    .msg-body p:last-child { margin-bottom: 0; }
    .msg-body code { font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace; font-size: 0.8rem; background: rgba(0,0,0,0.3); padding: 0.1rem 0.3rem; border-radius: 3px; }
    .msg-body pre { background: rgba(0,0,0,0.35); border: 1px solid var(--border); border-radius: 6px; padding: 0.6rem 0.8rem; overflow-x: auto; margin: 0.4rem 0; }
    .msg-body pre code { background: none; padding: 0; font-size: 0.78rem; }
    .msg-body h1, .msg-body h2, .msg-body h3, .msg-body h4 { margin: 0.5rem 0 0.3rem; font-size: 0.9rem; color: var(--accent2); }
    .msg-body h1 { font-size: 1rem; }
    .msg-body ul, .msg-body ol { margin: 0.3rem 0; padding-left: 1.4rem; }
    .msg-body li { margin: 0.15rem 0; }
    .msg-body blockquote { border-left: 3px solid var(--border); padding-left: 0.6rem; margin: 0.3rem 0; color: var(--muted); }
    .msg-body a { color: var(--accent); text-decoration: none; }
    .msg-body a:hover { text-decoration: underline; }
    .msg-body hr { border: none; border-top: 1px solid var(--border); margin: 0.5rem 0; }
    .msg-body table { border-collapse: collapse; margin: 0.4rem 0; font-size: 0.8rem; }
    .msg-body th, .msg-body td { border: 1px solid var(--border); padding: 0.25rem 0.5rem; }
    .msg-body th { background: var(--surface); }
    .msg-tools { display: flex; gap: 0.35rem; margin-top: 0.4rem; flex-wrap: wrap; }
    .tool-badge { font-size: 0.7rem; padding: 0.1rem 0.4rem; background: rgba(245, 166, 35, 0.08); border: 1px solid rgba(245, 166, 35, 0.25); border-radius: 4px; color: var(--accent2); font-family: monospace; }
</style>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
</head>
<body data-revision="__REVISION__">

<div class="topbar">
    <img src="../larvling.png" alt="Larvling" class="logo">
    <div><h1>Larvling</h1></div>
    <div class="topbar-right">
        <input type="text" id="search" placeholder="Search...">
    </div>
</div>

<div class="layout">
    <div class="sidebar" id="sidebar">
        <div class="sidebar-controls">
            <select id="sort-select">
                <option value="newest">Newest</option>
                <option value="oldest">Oldest</option>
                <option value="most-msgs">Most msgs</option>
                <option value="longest">Longest</option>
            </select>
            <select id="filter-select">
                <option value="all">All</option>
                <option value="today">Today</option>
                <option value="week">This week</option>
            </select>
        </div>
        <div class="sidebar-list" id="sidebar-list">
"""
        + sidebar_html
        + """
        </div>
    </div>
    <div class="main" id="main">
        <div class="no-session" id="no-session">Select a session</div>
"""
        + details_html
        + """
    </div>
</div>

<script>
var list = document.getElementById('sidebar-list');

// Render markdown in all message bodies
marked.setOptions({ breaks: true, gfm: true });
document.querySelectorAll('.msg-body').forEach(function(body) {
    var raw = body.textContent;
    body.dataset.raw = raw;
    body.innerHTML = marked.parse(raw);
    // Mark truncated bodies so the "click to expand" hint shows
    if (body.scrollHeight > body.clientHeight) body.classList.add('truncated');
});

function selectSession(sid) {
    document.querySelectorAll('.sidebar-item').forEach(function(el) {
        el.classList.toggle('active', el.dataset.sid === sid);
    });
    document.querySelectorAll('.detail-panel').forEach(function(el) {
        el.classList.toggle('active', el.dataset.sid === sid);
    });
    var ns = document.getElementById('no-session');
    if (ns) ns.style.display = sid ? 'none' : '';
}

function applySort(value) {
    var items = Array.from(list.querySelectorAll('.sidebar-item'));
    items.sort(function(a, b) {
        switch (value) {
            case 'oldest': return a.dataset.started.localeCompare(b.dataset.started);
            case 'most-msgs': return (parseInt(b.dataset.msgs) || 0) - (parseInt(a.dataset.msgs) || 0);
            case 'longest': return (parseFloat(b.dataset.duration) || 0) - (parseFloat(a.dataset.duration) || 0);
            default: return b.dataset.started.localeCompare(a.dataset.started);
        }
    });
    items.forEach(function(el) { list.appendChild(el); });
}

function applyFilter(value) {
    var now = new Date();
    var todayStr = now.toISOString().slice(0, 10);
    var weekAgo = new Date(now - 7 * 86400000).toISOString().slice(0, 10);

    document.querySelectorAll('.sidebar-item').forEach(function(el) {
        var show = true;
        var started = el.dataset.started || '';
        var dateStr = started.split(' ')[0] || '';
        switch (value) {
            case 'today': show = dateStr === todayStr; break;
            case 'week': show = dateStr >= weekAgo; break;
        }
        el.style.display = show ? '' : 'none';
    });
}

function highlightMessages(q) {
    // Clear previous highlights — restore rendered markdown
    document.querySelectorAll('.msg').forEach(function(msg) {
        msg.classList.remove('search-hit', 'search-dim');
        var body = msg.querySelector('.msg-body');
        if (body && body.dataset.raw) {
            body.innerHTML = marked.parse(body.dataset.raw);
        }
    });
    if (!q) return;
    var escaped = q.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&');
    var re = new RegExp('(' + escaped + ')', 'gi');
    document.querySelectorAll('.detail-panel').forEach(function(panel) {
        panel.querySelectorAll('.msg').forEach(function(msg) {
            var body = msg.querySelector('.msg-body');
            if (!body) return;
            if (body.textContent.toLowerCase().indexOf(q) !== -1) {
                msg.classList.add('search-hit');
                // Walk text nodes to insert <mark> without breaking HTML
                var walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
                var nodes = [];
                while (walker.nextNode()) nodes.push(walker.currentNode);
                nodes.forEach(function(node) {
                    if (re.test(node.nodeValue)) {
                        re.lastIndex = 0;
                        var span = document.createElement('span');
                        span.innerHTML = node.nodeValue.replace(re, '<mark>$1</mark>');
                        node.parentNode.replaceChild(span, node);
                    }
                });
            } else {
                msg.classList.add('search-dim');
            }
        });
    });
}

function applyAll() {
    applySort(document.getElementById('sort-select').value);
    applyFilter(document.getElementById('filter-select').value);
    var q = document.getElementById('search').value.toLowerCase();
    // Filter sessions in sidebar
    if (q) {
        document.querySelectorAll('.sidebar-item').forEach(function(el) {
            if (el.style.display === 'none') return;
            var sid = el.dataset.sid;
            var panel = document.querySelector('.detail-panel[data-sid="' + sid + '"]');
            var match = el.textContent.toLowerCase().indexOf(q) !== -1
                || (panel && panel.textContent.toLowerCase().indexOf(q) !== -1);
            if (!match) el.style.display = 'none';
        });
    }
    // Highlight matching messages in detail panels
    highlightMessages(q);
}

// Persist UI state to localStorage on every change
function saveState(key, val) { localStorage.setItem('larvling-' + key, val); }

document.getElementById('sort-select').addEventListener('change', function() { saveState('sort', this.value); applyAll(); });
document.getElementById('filter-select').addEventListener('change', function() { saveState('filter', this.value); applyAll(); });
document.getElementById('search').addEventListener('input', function() { saveState('search', this.value); applyAll(); });

list.addEventListener('click', function(e) {
    var item = e.target.closest('.sidebar-item');
    if (item) {
        selectSession(item.dataset.sid);
        saveState('active', item.dataset.sid);
    }
});

document.addEventListener('click', function(e) {
    var body = e.target.closest('.msg-body');
    if (body) {
        body.classList.toggle('expanded');
        body.classList.remove('truncated');
    }
});

// Restore UI state from localStorage
(function() {
    var sort = localStorage.getItem('larvling-sort');
    var filter = localStorage.getItem('larvling-filter');
    var search = localStorage.getItem('larvling-search');
    var sid = localStorage.getItem('larvling-active');

    if (sort) document.getElementById('sort-select').value = sort;
    if (filter) document.getElementById('filter-select').value = filter;
    if (search) document.getElementById('search').value = search;

    applyAll();

    if (sid && document.querySelector('.sidebar-item[data-sid="' + sid + '"]')) {
        selectSession(sid);
    } else {
        var first = list.querySelector('.sidebar-item:not([style*="display: none"])');
        if (first) selectSession(first.dataset.sid);
    }

    // Restore scroll position
    var savedScroll = localStorage.getItem('larvling-scroll');
    if (savedScroll) {
        setTimeout(function() {
            var msgs = document.querySelector('.detail-panel.active .messages');
            if (msgs) msgs.scrollTop = parseInt(savedScroll);
        }, 50);
    }
})();

// Save scroll position periodically
setInterval(function() {
    var msgs = document.querySelector('.detail-panel.active .messages');
    if (msgs) saveState('scroll', msgs.scrollTop);
}, 1000);

// Poll for changes — detect when dashboard.html is regenerated with new data
(function() {
    var currentRev = document.body.dataset.revision;
    setInterval(function() {
        var xhr = new XMLHttpRequest();
        xhr.open('GET', location.href, true);
        xhr.onload = function() {
            if (xhr.status === 200 || xhr.status === 0) {
                var match = xhr.responseText.match(/data-revision="(\\d+)"/);
                if (match && match[1] !== currentRev) {
                    location.reload();
                }
            }
        };
        xhr.send();
    }, 3000);
})();
</script>
</body>
</html>"""
    )


def main():
    if not os.path.exists(DB_PATH):
        print("No database found at", DB_PATH, file=sys.stderr)
        sys.exit(1)

    conn = get_db()
    conn.row_factory = sqlite3.Row
    sessions = get_sessions(conn)
    revision = conn.execute("SELECT MAX(id) FROM audit").fetchone()[0] or 0

    sidebar_html = "\n".join(render_sidebar_item(s, i) for i, s in enumerate(sessions))
    details_html = "\n".join(render_detail_panel(s) for s in sessions)

    conn.close()

    html = render_page(sidebar_html, details_html)
    html = html.replace("__REVISION__", str(revision))
    os.makedirs(os.path.dirname(HTML_PATH), exist_ok=True)
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Dashboard generated: {HTML_PATH}")


if __name__ == "__main__":
    main()
