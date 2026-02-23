"""
Larvling Hooks - unified handler for conversation lifecycle events.

Handles four hook events:
  - UserPromptSubmit: logs the user's prompt, injects fact management + summary hints
  - Stop: logs the agent's last response
  - PostToolUseFailure: records tool failures as quality signals
  - SessionEnd: finalizes session timing and exchange count
"""

import json
import os
import re
import sys
import time

from db import (
    open_db,
    has_table,
    reconfigure_stdout,
    ensure_session,
    record_message,
    finalize_session,
    record_summary,
    _log,
)


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
        if is_real_user_message(entry):
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


def inject_context(conn, session_id):
    """Print context hints (fact lookup, summary staleness) for the agent."""
    if has_table(conn, "facts"):
        fact_count = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        query_script = os.path.join(
            scripts_dir, "query.py"
        ).replace("\\", "/")
        print(f'\n## Fact Context\n{fact_count} stored fact(s). '
              f'query: python "{query_script}" "<SQL>"\n'
              f'Search for facts relevant to this prompt '
              f'(e.g. WHERE claim LIKE \'%topic%\') and weave '
              f'them into your response naturally.')

    session = conn.execute(
        "SELECT summary_msg_count, agent_summary FROM sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if session:
        msg_count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ? "
            "AND role IN ('user', 'assistant')",
            (session_id,),
        ).fetchone()[0]
        summarized = session["summary_msg_count"] or 0

        if not session["agent_summary"] and msg_count >= 10:
            print(f'\n## Summary\nNo summary yet ({msg_count} messages). '
                  f'Offer /summarize via AskUserQuestion.')
        elif session["agent_summary"] and msg_count > summarized + 4:
            print(f'\n## Summary\nStale summary '
                  f'(covers {summarized}/{msg_count} messages). '
                  f'Offer /summarize via AskUserQuestion.')


def handle_user_prompt(data):
    """Log the user's prompt and inject context."""
    session_id = data.get("session_id")
    if not session_id:
        return

    prompt = strip_ide_tags(data.get("prompt", ""))
    if not prompt:
        return

    meta = {"cwd": data.get("cwd"), "permission_mode": data.get("permission_mode")}

    with open_db() as conn:
        ensure_session(conn, session_id)
        record_message(conn, session_id, "user", prompt, meta)

        count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ? AND role = 'user'",
            (session_id,),
        ).fetchone()[0]
        if count == 1:
            record_summary(conn, session_id, title=prompt)

        conn.commit()
        try:
            inject_context(conn, session_id)
        except Exception:
            pass  # Context injection is non-critical


def handle_session_end(data):
    """Finalize session timing and record exchange count."""
    session_id = data.get("session_id")
    if not session_id:
        return

    with open_db() as conn:
        ensure_session(conn, session_id)
        finalize_session(conn, session_id)

        exchange_count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ? AND role = 'user'",
            (session_id,),
        ).fetchone()[0]

        record_summary(
            conn,
            session_id,
            exchange_count=exchange_count or None,
        )
        conn.commit()


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


def handle_stop(data):
    """Log the agent's last response from a Stop event."""
    session_id = data.get("session_id")
    if not session_id:
        return

    transcript_path = data.get("transcript_path")

    wait_for_transcript_stable(transcript_path)

    response, tools = parse_last_turn(transcript_path)

    with open_db() as conn:
        ensure_session(conn, session_id)

        # Log the response (if any and not a duplicate)
        if response:
            row = conn.execute(
                "SELECT content FROM messages "
                "WHERE session_id = ? AND role = 'assistant' "
                "ORDER BY id DESC LIMIT 1",
                (session_id,),
            ).fetchone()
            if not (row and row[0] == response):
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


def handle_tool_failure(data):
    """Record a tool failure as a quality signal."""
    session_id = data.get("session_id")
    if not session_id:
        return

    tool_name = data.get("tool_name", "unknown")
    error = data.get("error", "")

    with open_db() as conn:
        ensure_session(conn, session_id)
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
            existing["tool_failures"] = existing.get("tool_failures", 0) + 1
            failures_by_tool = existing.get("failures_by_tool", {})
            failures_by_tool[tool_name] = failures_by_tool.get(tool_name, 0) + 1
            existing["failures_by_tool"] = failures_by_tool
            conn.execute(
                "UPDATE sessions SET quality_signals = ? WHERE id = ?",
                (json.dumps(existing), session_id),
            )
        conn.commit()


def main():
    if os.environ.get("LARVLING_INTERNAL"):
        return
    reconfigure_stdout()
    # Read stdin as bytes to avoid Windows text-mode encoding issues (cp1252)
    # that can corrupt or hang on large payloads exceeding the 4KB pipe buffer.
    try:
        raw = sys.stdin.buffer.read().decode("utf-8")
    except Exception as e:
        _log(f"stdin read failed: {e}")
        return

    if not raw.strip():
        return

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        _log(f"JSON parse failed ({len(raw)} bytes): {e}")
        return

    event = data.get("hook_event_name", "")

    if event == "UserPromptSubmit":
        handle_user_prompt(data)
    elif event == "Stop":
        handle_stop(data)
    elif event == "PostToolUseFailure":
        handle_tool_failure(data)
    elif event == "SessionEnd":
        handle_session_end(data)


if __name__ == "__main__":
    main()
