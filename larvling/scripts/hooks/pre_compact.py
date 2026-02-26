"""
PreCompact hook — auto-generates a session summary before compaction.

Spawns a detached background process so the parent exits immediately
(no latency added to compaction). The child queries conversation pairs
from the DB, calls the Agent SDK for a summary, and stores it in
sessions.agent_summary.
"""

import asyncio
import os
import sys
import time

from db import (
    open_db,
    build_message_pairs,
    record_summary,
    ensure_session,
    fetch_session_tags,
    run_detached_or_inline,
    log,
)
from sdk import call_model

# ---------------------------------------------------------------------------
# Summarization
# ---------------------------------------------------------------------------

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
}


def format_pairs(pairs):
    """Format message pairs as numbered text for the summarization prompt."""
    lines = []
    for i, p in enumerate(pairs, 1):
        lines.append(f"[{i}] User: {p['user']}")
        lines.append(f"    Agent: {p['agent']}")
        lines.append("")
    return "\n".join(lines)


def fetch_pairs(conn, session_id):
    """Fetch user/assistant message pairs for a session."""
    rows = conn.execute(
        """
        SELECT role, content, timestamp
        FROM messages
        WHERE session_id = ? AND role IN ('user', 'assistant')
        ORDER BY id
        """,
        (session_id,),
    ).fetchall()
    return build_message_pairs(rows)



def run_summary(session_id, trigger):
    """Query pairs, call the model, store the summary."""
    with open_db() as conn:
        ensure_session(conn, session_id)
        conn.commit()

        pairs = fetch_pairs(conn, session_id)
        if not pairs:
            log("auto_summary", session_id, trigger=trigger, skipped="no pairs")
            return

        tags = fetch_session_tags(conn, session_id)

    pairs_text = format_pairs(pairs)
    pair_count = len(pairs)

    prompt = (
        "Summarize this conversation session concisely. Cover:\n"
        "- What was accomplished\n"
        "- Key decisions made\n"
        "- Unresolved items or next steps\n"
        "\n"
        "Scale detail to conversation length.\n"
        "\n"
        f"Session tags: {tags}\n"
        f"Conversation ({pair_count} exchanges):\n"
        f"{pairs_text}"
    )

    try:
        result, usage_info = asyncio.run(
            call_model(
                prompt,
                output_format={"type": "json_schema", "schema": SUMMARY_SCHEMA},
            )
        )
    except Exception as e:
        log("auto_summary", session_id, trigger=trigger, error=str(e))
        return

    if not isinstance(result, dict) or "summary" not in result:
        log("auto_summary", session_id, trigger=trigger, error="bad result")
        return

    summary_text = result["summary"]

    with open_db() as conn:
        msg_count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ? AND role IN ('user', 'assistant')",
            (session_id,),
        ).fetchone()[0]

        record_summary(
            conn,
            session_id,
            agent_summary=summary_text,
            summary_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            summary_msg_count=msg_count,
        )
        conn.commit()

    log_data = {
        "trigger": trigger,
        "pairs": pair_count,
        "summary_len": len(summary_text),
    }
    if usage_info and isinstance(usage_info, dict):
        log_data["input_tokens"] = usage_info.get("input_tokens", 0)
        log_data["output_tokens"] = usage_info.get("output_tokens", 0)
    log("auto_summary", session_id, **log_data)


# ---------------------------------------------------------------------------
# Detached entry point
# ---------------------------------------------------------------------------


def _run(data):
    """Detached worker — called by run_detached_or_inline after payload parsing."""
    session_id = data.get("session_id")
    trigger = data.get("trigger", "unknown")

    if not session_id:
        log("auto_summary", error="no session_id in payload")
        return

    run_summary(session_id, trigger)


if __name__ == "__main__":
    run_detached_or_inline(__file__, _run)
