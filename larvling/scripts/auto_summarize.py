"""
Auto-summarization at SessionEnd via Claude Agent SDK.

Called as a SessionEnd command hook. Checks if the session has enough
exchanges and a stale/missing summary, then calls Sonnet to generate
a 2-3 sentence summary and stores it via record_summary().
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone

from db import open_db, reconfigure_stdout, record_summary


def needs_summary(conn, session_id):
    """Check if the session needs a summary.

    Returns (needs, exchange_count, pairs) where needs is True when
    exchange_count >= 6 AND (no summary OR summary is stale).
    """
    row = conn.execute(
        "SELECT exchange_count, agent_summary, summary_msg_count "
        "FROM sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if not row:
        return False, 0, []

    exchange_count = row["exchange_count"] or 0
    if exchange_count < 6:
        return False, exchange_count, []

    msg_count = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE session_id = ? "
        "AND role IN ('user', 'assistant')",
        (session_id,),
    ).fetchone()[0]

    has_summary = bool(row["agent_summary"])
    summary_msg_count = row["summary_msg_count"] or 0

    if has_summary and msg_count <= summary_msg_count + 4:
        return False, exchange_count, []

    # Fetch conversation pairs
    rows = conn.execute(
        "SELECT role, content FROM messages "
        "WHERE session_id = ? AND role IN ('user', 'assistant') "
        "ORDER BY id",
        (session_id,),
    ).fetchall()

    pairs = []
    i = 0
    while i < len(rows):
        user_msg = ""
        agent_msg = ""
        if rows[i]["role"] == "user":
            user_msg = rows[i]["content"] or ""
            i += 1
            if i < len(rows) and rows[i]["role"] == "assistant":
                agent_msg = rows[i]["content"] or ""
                i += 1
        else:
            agent_msg = rows[i]["content"] or ""
            i += 1
        pairs.append((user_msg, agent_msg))

    return True, exchange_count, pairs


def build_conversation_text(pairs):
    """Build a compact conversation representation."""
    lines = []
    for i, (user, agent) in enumerate(pairs, 1):
        u = (user or "").strip()
        a = (agent or "").strip()
        lines.append(f"[{i}] User: {u}")
        lines.append(f"    Agent: {a}")

    return "\n".join(lines)


SUMMARIZE_PROMPT = """\
Summarize this coding session. Focus on what was accomplished, \
key decisions made, and any unresolved items. Be specific about technologies, \
files, or features discussed.

Scale your summary length to the conversation: 2-3 sentences for short sessions, \
a paragraph for longer ones. Be concise but don't omit important details.

Conversation:
{conversation}

Return ONLY the summary text, no JSON, no markdown fences, no labels."""


async def call_sdk(conversation_text):
    """Call Sonnet via Agent SDK to generate a session summary."""
    from claude_code_sdk import query, ClaudeCodeOptions

    prompt = SUMMARIZE_PROMPT.format(conversation=conversation_text)

    options = ClaudeCodeOptions(
        model="claude-sonnet-4-6",
        max_turns=1,
        allowed_tools=[],
    )

    # Prevent the sub-agent from triggering Larvling hooks
    os.environ["LARVLING_INTERNAL"] = "1"

    from claude_code_sdk import AssistantMessage, TextBlock

    response_text = ""
    try:
        async for msg in query(prompt=prompt, options=options):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        response_text += block.text
    except Exception as e:
        if not response_text:
            raise e
    finally:
        os.environ.pop("LARVLING_INTERNAL", None)

    return response_text.strip()


def main():
    if os.environ.get("LARVLING_INTERNAL"):
        return
    reconfigure_stdout()

    try:
        raw = sys.stdin.buffer.read().decode("utf-8")
    except Exception as e:
        _log_error(f"stdin read failed: {e}")
        return

    if not raw.strip():
        return

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return

    session_id = data.get("session_id")
    if not session_id:
        return

    with open_db() as conn:
        needed, exchange_count, pairs = needs_summary(conn, session_id)

    if not needed:
        return

    conversation_text = build_conversation_text(pairs)

    try:
        summary = asyncio.run(call_sdk(conversation_text))
    except Exception as e:
        _log_error(f"Auto-summarize SDK call failed: {e}")
        return

    if not summary:
        return

    msg_count = sum(1 for u, a in pairs for _ in [u, a] if _)

    with open_db() as conn:
        record_summary(
            conn,
            session_id,
            agent_summary=summary,
            summary_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            summary_msg_count=msg_count,
        )
        conn.commit()

    _log_error(f"Auto-summarized session {session_id[:8]} ({exchange_count} exchanges)")


def _log_error(msg):
    try:
        log_path = os.path.join(os.getcwd(), ".claude", "larvling-errors.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


if __name__ == "__main__":
    main()
