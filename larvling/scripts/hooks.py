"""
Larvling Hooks - unified handler for conversation lifecycle events.

Handles three hook events:
  - UserPromptSubmit: logs the user's prompt
  - Stop: reads transcript_path JSONL to extract the agent's last response
  - SessionEnd: finalizes session timing and exchange count
"""

import json
import os
import re
import sys
import time

from db import (
    open_db,
    escape_like,
    ensure_session,
    record_message,
    finalize_session,
    record_summary,
    get_active_loop,
    increment_loop,
    end_loop,
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
    if not session_id:
        return

    prompt = strip_ide_tags(data.get("prompt", ""))
    if not prompt:
        return

    meta = {"cwd": data.get("cwd"), "permission_mode": data.get("permission_mode")}

    with open_db() as conn:
        ensure_session(conn, session_id)
        record_message(conn, session_id, "user", prompt, meta)

        # Set title on first user message
        count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ? AND role = 'user'",
            (session_id,),
        ).fetchone()[0]
        if count == 1:
            record_summary(conn, session_id, title=prompt)

        conn.commit()


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
            conn, session_id,
            exchange_count=exchange_count or None,
        )
        conn.commit()


def _check_loop_completion(loop, response):
    """Check if a loop should end based on its conditions.

    Returns (status, outcome) if done, or None if the loop should continue.
    """
    # Completion promise found in response (checked first — fulfilling the
    # promise on the last iteration should count as "completed", not "exhausted").
    # Uses regex to tolerate whitespace and case differences around the tag.
    if loop["completion_promise"] and response:
        import re
        pattern = r"<promise>\s*" + re.escape(loop["completion_promise"]) + r"\s*</promise>"
        if re.search(pattern, response, re.IGNORECASE):
            return "completed", loop["completion_promise"]

    # No response at all — only exhaust if we've been running for a while.
    # On iteration 1, a missing transcript is likely a timing issue, not a
    # genuine failure, so let the loop continue.
    if not response and loop["iteration"] > 1:
        return "exhausted", "No response from agent"

    # Max iterations reached
    if loop["max_iterations"] > 0 and loop["iteration"] >= loop["max_iterations"]:
        return "exhausted", f"Reached max iterations ({loop['max_iterations']})"

    return None


def _build_loop_context(conn, loop, session_id):
    """Build a rich context string from Larvling's DB for loop iteration.

    Queries three sources using the same simple LIKE patterns that
    preflight.py and /query already use — no custom NLP needed:
    1. Facts whose claim/domain/tags match words from the prompt
    2. Assistant messages from this session since the loop started
    3. Past session summaries that reference similar terms
    """
    sections = []
    # Use significant words from the prompt as search terms (5+ chars, deduped)
    prompt_words = list(dict.fromkeys(
        w for w in re.findall(r"[a-zA-Z_]{5,}", loop["prompt"])
    ))[:8]

    # 1. Relevant facts
    if prompt_words:
        # Build OR clauses: (claim LIKE '%word%' OR domain LIKE '%word%' OR tags LIKE '%word%')
        clauses = []
        params = []
        for w in prompt_words:
            safe = escape_like(w.lower())
            clauses.append(
                "(LOWER(claim) LIKE ? ESCAPE '\\' "
                "OR LOWER(domain) LIKE ? ESCAPE '\\' "
                "OR LOWER(tags) LIKE ? ESCAPE '\\')"
            )
            params.extend([f"%{safe}%"] * 3)
        sql = f"SELECT id, claim FROM facts WHERE {' OR '.join(clauses)} LIMIT 8"
        facts = conn.execute(sql, params).fetchall()
        if facts:
            lines = [f"- [{f['id']}] {f['claim']}" for f in facts]
            sections.append("Relevant facts:\n" + "\n".join(lines))

    # 2. Loop progress — assistant messages from this session since loop started
    progress = conn.execute(
        "SELECT content FROM messages "
        "WHERE session_id = ? AND role = 'assistant' AND timestamp >= ? "
        "ORDER BY id DESC LIMIT 3",
        (session_id, loop["started_at"]),
    ).fetchall()
    if progress:
        lines = []
        for r in progress:
            first_line = (r["content"] or "").split("\n")[0][:200]
            if first_line:
                lines.append(f"- {first_line}")
        if lines:
            sections.append("Recent progress (newest first):\n" + "\n".join(lines))

    # 3. Related past session summaries (same pattern as preflight.py)
    if prompt_words:
        clauses = []
        params = [session_id]
        for w in prompt_words[:5]:
            safe = escape_like(w.lower())
            clauses.append(
                "(LOWER(agent_summary) LIKE ? ESCAPE '\\' "
                "OR LOWER(title) LIKE ? ESCAPE '\\')"
            )
            params.extend([f"%{safe}%"] * 2)
        sql = (
            f"SELECT id, agent_summary, title, started_at FROM sessions "
            f"WHERE id != ? AND ({' OR '.join(clauses)}) "
            f"ORDER BY started_at DESC LIMIT 3"
        )
        sessions = conn.execute(sql, params).fetchall()
        if sessions:
            lines = []
            for s in sessions:
                summary = s["agent_summary"] or s["title"] or ""
                if summary:
                    date = (s["started_at"] or "?")[:10]
                    lines.append(f"- [{date}] {summary[:150]}")
            if lines:
                sections.append("Related past sessions:\n" + "\n".join(lines))

    return "\n\n".join(sections) if sections else ""


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
        logged = False
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
                logged = True

        # Loop check
        loop = get_active_loop(conn, session_id)
        if not loop:
            if logged:
                conn.commit()
            return  # Normal exit

        result = _check_loop_completion(loop, response)
        if result:
            status, outcome = result
            end_loop(conn, loop["id"], status, outcome)
            conn.commit()  # commits message + loop end together
            return  # Allow exit

        # Loop continues — increment and block exit
        increment_loop(conn, loop["id"])
        conn.commit()  # commits message + increment together

        # Re-read to get updated iteration
        updated = conn.execute(
            "SELECT iteration, max_iterations, prompt FROM loops WHERE id = ?",
            (loop["id"],),
        ).fetchone()

        iteration = updated["iteration"]
        max_iter = updated["max_iterations"]
        prompt = updated["prompt"]
        iter_str = f"{iteration}/{max_iter}" if max_iter > 0 else str(iteration)

        # Build rich context from Larvling's memory
        context = _build_loop_context(conn, loop, session_id)
        system_parts = [f"Loop iteration {iter_str}"]
        if context:
            system_parts.append(context)
        lid = loop['id']
        system_parts.append(
            "Continue working on the task. Review your previous work in files and git, then proceed.\n\n"
            "**Before doing any work**, update your progress tracker using `/query`:\n"
            f"```\n"
            f"/query \"INSERT OR REPLACE INTO facts (id, claim, domain, tags, source) "
            f"VALUES ('L{lid}-progress', 'DONE: <completed items> | REMAINING: <remaining items>', "
            f"'loop-progress', 'loop,progress', 'loop-{lid}')\"\n"
            f"```\n"
            "This fact is surfaced each iteration so you know exactly where to pick up.\n\n"
            "**Manage your iteration knowledge** using `/query`:\n"
            f"- **Insert** discoveries, challenges, decisions, or blockers as facts\n"
            f"- **Update** facts that are incomplete or need refinement\n"
            f"- **Delete** facts that turned out to be wrong or irrelevant\n"
            f"- ID convention: `L{lid}-I{iteration}-a`, `L{lid}-I{iteration}-b`, etc.\n"
            f"- domain='loop-discovery', source='loop-{lid}'\n"
            "- All facts are surfaced automatically in subsequent iterations"
        )

        block = {
            "decision": "block",
            "reason": prompt,
            "systemMessage": "\n\n".join(system_parts),
        }
        print(json.dumps(block))


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
