"""Stop hook — logs the agent's last response, computes quality signals, and tracks token usage."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db import (
    open_db,
    parse_meta,
    ensure_session,
    record_message,
    accumulate_quality_signals,
    read_hook_payload,
    log,
)
from transcript import parse_last_turn, parse_last_user_text, wait_for_transcript_stable


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


def estimate_user_tokens(user_text):
    """Estimate token count for user message text.

    Uses the ~4 characters per token heuristic. This is an approximation —
    actual tokenization varies by content (code, URLs, non-English text
    may differ). Sufficient for relative comparisons across exchanges.

    Returns estimated token count (int) or None if no text.
    """
    if not user_text:
        return None
    return max(1, len(user_text) // 4)


def store_usage_on_message(conn, session_id, role, usage_data, expected_content=None):
    """Store usage data in the metadata of the last message with the given role."""
    if not usage_data:
        return

    row = conn.execute(
        "SELECT id, content, metadata FROM messages "
        "WHERE session_id = ? AND role = ? "
        "ORDER BY id DESC LIMIT 1",
        (session_id, role),
    ).fetchone()
    if not row:
        return

    if expected_content and row["content"] != expected_content:
        return

    meta = parse_meta(row["metadata"])
    meta["usage"] = usage_data
    conn.execute(
        "UPDATE messages SET metadata = ? WHERE id = ?",
        (json.dumps(meta), row["id"]),
    )


def handle(data):
    session_id = data.get("session_id")
    if not session_id:
        return

    transcript_path = data.get("transcript_path")

    wait_for_transcript_stable(transcript_path)

    response, tools, usage = parse_last_turn(transcript_path)
    user_text = parse_last_user_text(transcript_path)

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
                meta = {"tool_calls": tools} if tools else {}
                if usage:
                    meta["usage"] = usage
                record_message(conn, session_id, "assistant", response, meta or None)
            elif usage:
                # Response was a dup (already stored), but still attach usage
                store_usage_on_message(conn, session_id, "assistant", usage, expected_content=response)

        # Store estimated user message token count (~4 chars/token heuristic)
        user_tokens = estimate_user_tokens(user_text)
        if user_tokens is not None:
            store_usage_on_message(
                conn, session_id, "user",
                {"input_tokens_estimate": user_tokens},
            )

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

    # Log token usage
    if usage:
        in_tok = usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0) + usage.get("cache_creation_input_tokens", 0)
        out_tok = usage.get("output_tokens", 0)
        parts.append(f"tokens={in_tok}in/{out_tok}out")
    if user_tokens is not None:
        parts.append(f"user_tokens=~{user_tokens}")

    log(f"Stop: {', '.join(parts)}")


if __name__ == "__main__":
    data = read_hook_payload()
    handle(data)
