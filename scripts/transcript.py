"""
Larvling Transcript Logger — captures both sides of the conversation into the audit table.

Handles two hook events:
  - UserPromptSubmit: logs the user's prompt directly from stdin JSON
  - Stop: reads transcript_path JSONL to extract the agent's last response
"""

import json
import os
import re
import sys
import time

from db import get_db, log_audit


def _is_real_user_message(entry):
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
    """Extract text and tool call counts from the last assistant turn.

    Reads the transcript once, finds the boundary after the last real user
    message, and collects both text blocks and tool_use counts from that
    point forward.

    Returns (text, tool_counts) where text is the concatenated assistant
    response and tool_counts is a dict of {tool_name: count}.
    """
    if not transcript_path or not os.path.exists(transcript_path):
        return None, {}

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
        if _is_real_user_message(entry):
            turn_start = i + 1
            break

    # Collect text and tool counts from the last turn only
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


def strip_ide_tags(text):
    """Remove leading IDE context tags (opened files, selections) prepended by VSCode."""
    return re.sub(
        r"^(?:<ide_(?:opened_file|selection)>.*?</ide_(?:opened_file|selection)>\s*)+",
        "", text, flags=re.DOTALL,
    ).strip()


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


def handle_user_prompt(data):
    """Log the user's prompt from a UserPromptSubmit event."""
    session_id = data.get("session_id")
    prompt = strip_ide_tags(data.get("prompt", ""))

    if not prompt:
        return

    meta = {"cwd": data.get("cwd"), "permission_mode": data.get("permission_mode")}

    conn = get_db()
    log_audit(conn, session_id, "user_message", prompt, meta)
    conn.close()


def handle_stop(data):
    """Log the agent's last response from a Stop event."""
    session_id = data.get("session_id")
    transcript_path = data.get("transcript_path")

    wait_for_transcript_stable(transcript_path)

    response, tools = parse_last_turn(transcript_path)
    if not response:
        return

    conn = get_db()
    # Dedup: skip if we already logged this exact content for this session
    row = conn.execute(
        "SELECT content FROM audit WHERE session_id = ? AND event_type = 'agent_message' ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if row and row[0] == response:
        conn.close()
        return

    meta = {"tool_calls": tools} if tools else None
    log_audit(conn, session_id, "agent_message", response, meta)
    conn.close()


def main():
    raw = sys.stdin.read()
    if not raw.strip():
        return

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print("Failed to parse hook input", file=sys.stderr)
        return

    event = data.get("hook_event_name", "")

    if event == "UserPromptSubmit":
        handle_user_prompt(data)
    elif event == "Stop":
        handle_stop(data)


if __name__ == "__main__":
    main()
