"""Transcript parsing utilities for Larvling hook scripts."""

import json
import os
import time


def is_real_user_message(entry):
    """Return True if this is a genuine user message, not a tool_result."""
    if entry.get("type") != "user":
        return False
    msg = entry.get("message", {})
    if not isinstance(msg, dict):
        return False
    content = msg.get("content", "")
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                return False
        return True
    return False


def parse_last_turn(transcript_path):
    """Extract text, tool call counts, and usage from the last assistant turn.

    Reads the transcript once, finds the boundary after the last real user
    message, and collects text blocks, tool_use counts, and token usage
    from that point forward.

    Usage is accumulated from deduplicated entries in the turn.
    Output tokens are summed from "real" API responses (entries with
    a `speed` field).  For text-only turns with no real entry, the
    caller can detect the `output_tokens_estimated` flag in the
    returned usage dict.  Input tokens come from the last entry
    (largest context window).

    Returns (text, tool_counts, usage) where text is the concatenated
    assistant response, tool_counts is a dict of {tool_name: count}, and
    usage is the combined usage dict (or None).
    """
    if not transcript_path or not os.path.exists(transcript_path):
        return None, {}, None

    lines = []
    with open(transcript_path, "r", encoding="utf-8") as f:
        for raw_line in f:
            raw_line = raw_line.strip()
            if raw_line:
                lines.append(raw_line)

    # Find where the last turn starts (after the last real user message)
    turn_start = 0
    for i in range(len(lines) - 1, -1, -1):
        try:
            entry = json.loads(lines[i])
        except json.JSONDecodeError:
            continue
        if is_real_user_message(entry):
            turn_start = i + 1
            break

    # Collect text, tool counts, and usage from the last turn only.
    # The transcript has two kinds of usage entries:
    #   - "real" API responses: include `speed` field, accurate output_tokens.
    #   - streaming metadata: lack `speed`, report small placeholder values.
    # We sum output_tokens from real (speed) entries. For text-only turns
    # there may be no real entry — the caller can estimate from text length.
    # Input tokens are taken from the last entry (largest context window).
    all_text = []
    tools = {}
    last_usage = None
    real_output_tokens = 0
    prev_usage = None
    for line in lines[turn_start:]:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant":
            continue
        msg = entry.get("message", {})
        if isinstance(msg, dict):
            msg_usage = msg.get("usage")
            if msg_usage and msg_usage != prev_usage:
                last_usage = msg_usage
                prev_usage = msg_usage
                if "speed" in msg_usage:
                    real_output_tokens += msg_usage.get("output_tokens", 0)
        content = msg.get("content", "") if isinstance(msg, dict) else ""
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text = block.get("text", "").strip()
                        if text:
                            parts.append(text)
                    elif block.get("type") == "tool_use":
                        name = block.get("name", "unknown")
                        tools[name] = tools.get(name, 0) + 1
                elif isinstance(block, str) and block.strip():
                    parts.append(block.strip())
            if parts:
                all_text.append("\n".join(parts))
        elif content:
            all_text.append(str(content))

    text = "\n\n".join(all_text) if all_text else None

    # Combined usage: last entry's input tokens + best available output tokens.
    # real_output_tokens comes from `speed` entries (accurate API totals).
    # If zero (text-only turn), estimate from response text (~4 chars/token).
    usage = None
    if last_usage:
        usage = dict(last_usage)
        if real_output_tokens:
            usage["output_tokens"] = real_output_tokens
        elif text:
            usage["output_tokens"] = max(1, len(text) // 4)
            usage["output_tokens_estimated"] = True
        else:
            usage["output_tokens"] = 0

    return text, tools, usage


def parse_last_user_text(transcript_path):
    """Return the last real user message text from the transcript."""
    if not transcript_path or not os.path.exists(transcript_path):
        return None

    lines = []
    with open(transcript_path, "r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if raw:
                lines.append(raw)

    for i in range(len(lines) - 1, -1, -1):
        try:
            entry = json.loads(lines[i])
        except json.JSONDecodeError:
            continue
        if is_real_user_message(entry):
            msg = entry.get("message", {})
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = [
                    b.get("text", "") if isinstance(b, dict) else str(b)
                    for b in content
                    if not (isinstance(b, dict) and b.get("type") == "tool_result")
                ]
                return " ".join(p for p in parts if p).strip()

    return None


def wait_for_transcript_stable(transcript_path, interval=0.1, max_wait=2):
    """Wait until the transcript file stops being written to."""
    if not transcript_path or not os.path.exists(transcript_path):
        return
    last_size = os.path.getsize(transcript_path)
    waited = 0
    while waited < max_wait:
        time.sleep(interval)
        waited += interval
        size = os.path.getsize(transcript_path)
        if size == last_size:
            return
        last_size = size
