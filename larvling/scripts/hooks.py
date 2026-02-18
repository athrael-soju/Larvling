"""
Larvling Hooks - unified handler for conversation lifecycle events.

Handles three hook events:
  - UserPromptSubmit: logs the user's prompt
  - Stop: reads transcript_path JSONL to extract the agent's last response
  - SessionEnd: finalizes encounter timing and records reflection
"""

import json
import os
import re
import sys
import time

from db import (
    get_db,
    ensure_encounter,
    record_imprint,
    finalize_encounter,
    record_reflection,
)


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
        "",
        text,
        flags=re.DOTALL,
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
    ensure_encounter(conn, session_id)
    record_imprint(conn, session_id, "user", prompt, meta)

    # Set title on first user message
    count = conn.execute(
        "SELECT COUNT(*) FROM imprints WHERE encounter_id = ? AND role = 'user'",
        (session_id,),
    ).fetchone()[0]
    if count == 1:
        record_reflection(conn, session_id, title=prompt)

    conn.close()


def handle_session_end(data):
    """Finalize encounter timing and record a reflection."""
    session_id = data.get("session_id")
    if not session_id:
        return

    conn = get_db()
    ensure_encounter(conn, session_id)
    finalize_encounter(conn, session_id)

    exchange_count = conn.execute(
        "SELECT COUNT(*) FROM imprints WHERE encounter_id = ? AND role = 'user'",
        (session_id,),
    ).fetchone()[0]

    record_reflection(
        conn, session_id,
        exchange_count=exchange_count or None,
    )
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
    ensure_encounter(conn, session_id)

    # Dedup: skip if we already logged this exact content for this encounter
    row = conn.execute(
        "SELECT content FROM imprints "
        "WHERE encounter_id = ? AND role = 'assistant' "
        "ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if row and row[0] == response:
        conn.close()
        return

    meta = {"tool_calls": tools} if tools else None
    record_imprint(conn, session_id, "assistant", response, meta)
    conn.close()


def _log_error(msg):
    """Append an error to .claude/larvling-errors.log for debugging silent failures."""
    try:
        log_path = os.path.join(os.getcwd(), ".claude", "larvling-errors.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def main():
    # Read stdin as bytes to avoid Windows text-mode encoding issues (cp1252)
    # that can corrupt or hang on large payloads exceeding the 4KB pipe buffer.
    try:
        raw = sys.stdin.buffer.read().decode("utf-8")
    except Exception as e:
        _log_error(f"stdin read failed: {e}")
        return

    if not raw.strip():
        return

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        _log_error(f"JSON parse failed ({len(raw)} bytes): {e}")
        return

    event = data.get("hook_event_name", "")

    if event == "UserPromptSubmit":
        handle_user_prompt(data)
    elif event == "Stop":
        handle_stop(data)
    elif event == "SessionEnd":
        handle_session_end(data)


if __name__ == "__main__":
    main()
