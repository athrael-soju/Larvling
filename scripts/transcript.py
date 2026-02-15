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
    """Read the transcript JSONL backwards to find the last assistant content."""
    if not transcript_path or not os.path.exists(transcript_path):
        return None

    # Read all lines and walk backwards to find the last assistant message
    lines = []
    with open(transcript_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                lines.append(line)

    # Walk backwards to find the last assistant message
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        # Claude Code transcript format: look for assistant role messages
        role = entry.get("role") or entry.get("type")
        if role == "assistant":
            # Content can be a string or a list of content blocks
            content = entry.get("content", "")
            if isinstance(content, list):
                # Extract text from content blocks
                parts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            parts.append(block.get("text", ""))
                        elif block.get("type") == "tool_use":
                            parts.append(f"[tool_use: {block.get('name', '?')}]")
                    elif isinstance(block, str):
                        parts.append(block)
                return "\n".join(parts)
            return str(content)

    return None


def handle_user_prompt(data):
    """Log the user's prompt from a UserPromptSubmit event."""
    session_id = data.get("session_id")
    prompt = data.get("prompt", "")

    if not prompt:
        return

    conn = get_db()
    log_audit(conn, session_id, "user_message", prompt)
    conn.close()


def handle_stop(data):
    """Log the agent's last response from a Stop event."""
    session_id = data.get("session_id")
    transcript_path = data.get("transcript_path")

    response = extract_last_assistant_turn(transcript_path)
    if response:
        conn = get_db()
        log_audit(conn, session_id, "agent_message", response)
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
