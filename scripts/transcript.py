"""
Larvling Transcript Logger — captures both sides of the conversation into the audit table.

Handles two hook events:
  - UserPromptSubmit: logs the user's prompt directly from stdin JSON
  - Stop: reads transcript_path JSONL to extract the agent's last response
"""

import json
import sqlite3
import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, ".claude", "larvling.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def log_audit(conn, session_id, event_type, content, metadata=None):
    conn.execute(
        "INSERT INTO audit (session_id, event_type, content, metadata) VALUES (?, ?, ?, ?)",
        (session_id, event_type, content, json.dumps(metadata) if metadata else None),
    )
    conn.commit()


def extract_last_assistant_turn(transcript_path):
    """Collect text from the last agent turn (everything after the last real user message)."""
    if not transcript_path or not os.path.exists(transcript_path):
        return None

    lines = []
    with open(transcript_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                lines.append(line)

    def is_real_user_message(entry):
        """Return True if this is a genuine user message, not a tool_result."""
        if entry.get("type") != "user":
            return False
        msg = entry.get("message", {})
        if not isinstance(msg, dict):
            return False
        content = msg.get("content", "")
        if isinstance(content, str):
            return True  # Plain string = real user message
        if isinstance(content, list):
            # If any block is a tool_result, this is a tool response, not a user turn
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    return False
            return True
        return False

    # Walk backwards to find the last real user message
    turn_start = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        try:
            entry = json.loads(lines[i])
        except json.JSONDecodeError:
            continue
        if is_real_user_message(entry):
            turn_start = i + 1
            break

    # Now collect all assistant text from turn_start to end
    all_text = []
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
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "").strip()
                    if text:
                        parts.append(text)
                elif isinstance(block, str) and block.strip():
                    parts.append(block.strip())
            if parts:
                all_text.append("\n".join(parts))
        elif content:
            all_text.append(str(content))

    return "\n\n".join(all_text) if all_text else None


def count_tool_calls(transcript_path):
    """Count tool uses in the latest assistant turn from the transcript."""
    if not transcript_path or not os.path.exists(transcript_path):
        return {}

    tools = {}
    with open(transcript_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") != "assistant":
                continue
            msg = entry.get("message", {})
            for block in (msg.get("content", []) if isinstance(msg, dict) else []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    name = block.get("name", "unknown")
                    tools[name] = tools.get(name, 0) + 1
    return tools


def handle_user_prompt(data):
    """Log the user's prompt from a UserPromptSubmit event."""
    session_id = data.get("session_id")
    prompt = data.get("prompt", "")

    if not prompt:
        return

    meta = {"cwd": data.get("cwd"), "permission_mode": data.get("permission_mode")}

    conn = get_db()
    log_audit(conn, session_id, "user_message", prompt, meta)
    conn.close()


def wait_for_transcript_stable(transcript_path, interval=0.3, max_wait=5):
    """Wait until the transcript file stops being written to."""
    if not transcript_path or not os.path.exists(transcript_path):
        return
    last_size = -1
    waited = 0
    while waited < max_wait:
        size = os.path.getsize(transcript_path)
        if size == last_size:
            return  # File hasn't changed — stable
        last_size = size
        time.sleep(interval)
        waited += interval


def handle_stop(data):
    """Log the agent's last response from a Stop event."""
    session_id = data.get("session_id")
    transcript_path = data.get("transcript_path")

    wait_for_transcript_stable(transcript_path)

    response = extract_last_assistant_turn(transcript_path)
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

    tools = count_tool_calls(transcript_path)
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
        print(f"Failed to parse hook input", file=sys.stderr)
        return

    event = data.get("hook_event_name", "")

    if event == "UserPromptSubmit":
        handle_user_prompt(data)
    elif event == "Stop":
        handle_stop(data)


if __name__ == "__main__":
    main()
