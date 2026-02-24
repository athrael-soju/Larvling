"""Stop hook — logs the agent's last response and computes quality signals."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db import (
    open_db,
    reconfigure_stdout,
    ensure_session,
    record_message,
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
            sess = conn.execute(
                "SELECT quality_signals FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if sess:
                existing = {}
                if sess["quality_signals"]:
                    try:
                        existing = json.loads(sess["quality_signals"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                for key, val in signals.items():
                    existing[key] = existing.get(key, 0) + val
                conn.execute(
                    "UPDATE sessions SET quality_signals = ? WHERE id = ?",
                    (json.dumps(existing), session_id),
                )

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
    if os.environ.get("LARVLING_INTERNAL"):
        sys.exit(0)
    reconfigure_stdout()
    try:
        raw = sys.stdin.buffer.read().decode("utf-8")
    except Exception as e:
        log(f"stdin read failed: {e}")
        sys.exit(0)
    if not raw.strip():
        sys.exit(0)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        log(f"JSON parse failed ({len(raw)} bytes): {e}")
        sys.exit(0)
    handle(data)
