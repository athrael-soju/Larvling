"""Stop hook — logs the agent's last response and computes quality signals."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db import (
    open_db,
    ensure_session,
    record_message,
    accumulate_quality_signals,
    read_hook_payload,
    log,
)
from transcript import parse_last_turn, wait_for_transcript_stable


def compute_quality_signals(response_text, tools):
    """Compute quality signals from response text and tool counts.

    Returns a dict with error_count, retry_count, and total_tool_calls.
    Pure Python — no SDK call, no added latency.
    """
    signals = {}
    if response_text:
        text_lower = response_text.lower()
        error_keywords = ["error:", "failed", "exception", "traceback", "fatal"]
        signals["error_count"] = sum(
            text_lower.count(kw) for kw in error_keywords
        )
        retry_patterns = ["let me try again", "trying a different", "let me retry",
                          "try another approach", "try a different"]
        signals["retry_count"] = sum(
            text_lower.count(pat) for pat in retry_patterns
        )
    if tools:
        signals["total_tool_calls"] = sum(tools.values())
    return signals


def handle(data):
    session_id = data.get("session_id")
    if not session_id:
        return

    transcript_path = data.get("transcript_path")

    wait_for_transcript_stable(transcript_path)

    response, tools = parse_last_turn(transcript_path)

    with open_db() as conn:
        ensure_session(conn, session_id)

        # Log the response (if any and not a duplicate)
        is_dup = False
        if response:
            row = conn.execute(
                "SELECT content FROM messages "
                "WHERE session_id = ? AND role = 'assistant' "
                "ORDER BY id DESC LIMIT 1",
                (session_id,),
            ).fetchone()
            is_dup = bool(row and row[0] == response)
            if not is_dup:
                meta = {"tool_calls": tools} if tools else None
                record_message(conn, session_id, "assistant", response, meta)

        # Accumulate quality signals
        signals = compute_quality_signals(response, tools)
        if signals:
            accumulate_quality_signals(conn, session_id, signals)

        conn.commit()

    # Log stop details
    parts = [f"session={session_id[:8]}"]
    if response:
        parts.append(f"response={len(response)} chars")
        parts.append(f"dup={is_dup}")
    else:
        parts.append("response=none")
    if tools:
        total = sum(tools.values())
        parts.append(f"tools={total}")
    if signals.get("error_count"):
        parts.append(f"errors={signals['error_count']}")
    if signals.get("retry_count"):
        parts.append(f"retries={signals['retry_count']}")
    log(f"Stop: {', '.join(parts)}")


if __name__ == "__main__":
    data = read_hook_payload()
    handle(data)
