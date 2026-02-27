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


def _read_transcript_lines(transcript_path):
    """Read non-empty stripped lines from a transcript file."""
    lines = []
    with open(transcript_path, "r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if raw:
                lines.append(raw)
    return lines


def parse_last_turn(transcript_path):
    """Extract text and tool call counts from the last assistant turn.

    Reads the transcript once, finds the boundary after the last real user
    message, and collects text blocks and tool_use counts from that point
    forward.

    Returns (text, tools) where text is the concatenated assistant response
    and tools is a dict of {tool_name: count}.
    """
    if not transcript_path or not os.path.exists(transcript_path):
        return None, {}

    lines = _read_transcript_lines(transcript_path)

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

    all_text = []
    tools = {}
    for line in lines[turn_start:]:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant":
            continue
        msg = entry.get("message", {})
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

    return text, tools


def parse_last_user_text(transcript_path):
    """Return the last real user message text from the transcript."""
    if not transcript_path or not os.path.exists(transcript_path):
        return None

    lines = _read_transcript_lines(transcript_path)

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
