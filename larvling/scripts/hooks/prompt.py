"""UserPromptSubmit hook — logs the user's prompt and injects context hints."""

import json
import os
import re
import sys

from config import get_config
from db import (
    open_db,
    has_table,
    ensure_session,
    record_message,
    record_summary,
    log,
    PROJECT_ROOT,
)
from hooks_util import read_hook_payload


def strip_ide_tags(text):
    """Remove leading IDE context tags (opened files, selections) prepended by VSCode."""
    return re.sub(
        r"^(?:<ide_(?:opened_file|selection)>.*?</ide_(?:opened_file|selection)>\s*)+",
        "",
        text,
        flags=re.DOTALL,
    ).strip()


def _last_context_counts():
    """Read the last context event from the JSONL log and return (topics, stmts)."""
    try:
        log_path = os.path.join(PROJECT_ROOT, ".claude", "larvling.jsonl")
        last = None
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if entry.get("event") == "context" and entry.get("injected"):
                    last = entry
        if last:
            for item in last["injected"]:
                m = re.match(r"(\d+)(?:\s*\([^)]*\))?\s*topics,\s*(\d+)(?:\s*\([^)]*\))?\s*statements", item)
                if m:
                    return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return None, None


def _fmt_delta(current, previous):
    """Format a count with optional delta suffix, e.g. '17 (+2)'."""
    if previous is None or current == previous:
        return str(current)
    diff = current - previous
    sign = "+" if diff > 0 else ""
    return f"{current} ({sign}{diff})"


def _recent_extraction(conn):
    """Build a brief summary of what was learned since the last prompt.

    Compares current topic/statement/task counts against the last context
    event and, when there's growth, fetches the most recently added items
    from the database so the agent can mention them naturally.
    """
    prev_topics, prev_stmts = _last_context_counts()
    if prev_topics is None:
        return None

    cur_topics = conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0] if has_table(conn, "topics") else 0
    cur_stmts = conn.execute("SELECT COUNT(*) FROM statements").fetchone()[0] if has_table(conn, "statements") else 0

    new_topics = cur_topics - (prev_topics or 0)
    new_stmts = cur_stmts - (prev_stmts or 0)

    if new_topics <= 0 and new_stmts <= 0:
        return None

    # Fetch recently added items for context
    parts = []
    if new_stmts > 0 and has_table(conn, "statements"):
        recent = conn.execute(
            "SELECT t.title, s.claim FROM topics t "
            "JOIN statements s ON s.topic_id = t.id "
            "ORDER BY s.id DESC LIMIT ?",
            (min(new_stmts, 3),),
        ).fetchall()
        for r in recent:
            claim = r["claim"]
            if len(claim) > 80:
                claim = claim[:77] + "..."
            parts.append(f"{r['title']}: {claim}")

    if not parts:
        counts = []
        if new_topics > 0:
            counts.append(f"+{new_topics} topic{'s' if new_topics != 1 else ''}")
        if new_stmts > 0:
            counts.append(f"+{new_stmts} statement{'s' if new_stmts != 1 else ''}")
        return ", ".join(counts)

    return "; ".join(parts)


def inject_context(conn, session_id):
    """Print context hints (knowledge lookup, summary staleness) for the agent."""
    cfg = get_config()
    injected = []

    if cfg["context_hints"] and has_table(conn, "topics"):
        topic_count = conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0]
        stmt_count = (
            conn.execute("SELECT COUNT(*) FROM statements").fetchone()[0]
            if has_table(conn, "statements")
            else 0
        )
        scripts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
        query_script = os.path.normpath(os.path.join(scripts_dir, "query.py")).replace(
            "\\", "/"
        )
        py = os.path.basename(sys.executable)
        text = (
            f"\n## Knowledge Context\n"
            f"{topic_count} topic(s), {stmt_count} statement(s). "
            f'query: {py} "{query_script}" "<SQL>"\n'
            f"Search for relevant knowledge and weave it into your response naturally."
        )
        print(text)

        # Show what was learned from the last exchange (extraction feedback)
        extraction = _recent_extraction(conn)
        if extraction:
            print(f"Last learned: {extraction}")
            injected.append(f"learned: {extraction}")

        prev_topics, prev_stmts = _last_context_counts()
        t_str = _fmt_delta(topic_count, prev_topics)
        s_str = _fmt_delta(stmt_count, prev_stmts)
        injected.append(f"{t_str} topics, {s_str} statements")

    if not cfg["summary_hints"]:
        if injected:
            log("context", session_id, injected=injected)
        return

    session = conn.execute(
        "SELECT summary_msg_count, agent_summary, summary_offered FROM sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if session:
        msg_count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ? "
            "AND role IN ('user', 'assistant')",
            (session_id,),
        ).fetchone()[0]
        summarized = session["summary_msg_count"] or 0
        already_offered = session["summary_offered"] or 0

        if not already_offered and not session["agent_summary"] and msg_count >= 10:
            text = f"\n## Summary\nNo summary yet ({msg_count} messages)."
            print(text)
            conn.execute(
                "UPDATE sessions SET summary_offered = 1 WHERE id = ?",
                (session_id,),
            )
            conn.commit()
            injected.append("summary hint")
        elif not already_offered and session["agent_summary"] and msg_count > summarized + 4:
            text = (
                f"\n## Summary\nStale summary "
                f"(covers {summarized}/{msg_count} messages)."
            )
            print(text)
            conn.execute(
                "UPDATE sessions SET summary_offered = 1 WHERE id = ?",
                (session_id,),
            )
            conn.commit()
            injected.append("stale summary hint")

    if injected:
        log("context", session_id, injected=injected)


def handle(data):
    session_id = data.get("session_id")
    if not session_id:
        return

    prompt = strip_ide_tags(data.get("prompt", ""))
    if not prompt:
        return

    meta = {
        "cwd": data.get("cwd"),
        "permission_mode": data.get("permission_mode"),
    }

    # System-injected messages (e.g. task-notification) arrive through the
    # UserPromptSubmit hook but are not actual user input.
    role = "system" if prompt.startswith("<task-notification>") else "user"

    with open_db() as conn:
        ensure_session(conn, session_id)
        record_message(conn, session_id, role, prompt, meta)

        if role == "user":
            count = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id = ? AND role = 'user'",
                (session_id,),
            ).fetchone()[0]
            if count == 1:
                record_summary(conn, session_id, title=prompt)

        conn.commit()

        if role != "user":
            log("system-passthrough", session_id)
        else:
            # Detect skill/command invocations:
            # - Raw slash command: "/status", "/recall"
            # - XML tags: <command-message>plugin:skill</command-message>
            cmd_match = re.search(
                r"<command-(?:message|name)>\s*/?(.+?)\s*</command-(?:message|name)>",
                prompt,
            )
            if not cmd_match and re.fullmatch(r"/[\w:/-]+", prompt.strip()):
                cmd_match = re.fullmatch(r"/([\w:/-]+)", prompt.strip())
            if cmd_match:
                log("skill", session_id, name=f"/{cmd_match.group(1)}")
            else:
                log("prompt", session_id, n=count)

        if role == "user":
            try:
                inject_context(conn, session_id)
            except Exception:
                pass  # Context injection is non-critical


if __name__ == "__main__":
    data = read_hook_payload()
    if data:
        handle(data)
