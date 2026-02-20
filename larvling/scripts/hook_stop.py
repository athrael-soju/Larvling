"""Larvling Stop hook.

Logs the agent's last response, manages loop iteration/completion.
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
    get_active_loop,
    increment_loop,
    end_loop,
)
from transcript import parse_last_turn, wait_for_transcript_stable


def _check_loop_completion(loop, response):
    """Check if a loop should end based on its conditions.

    Returns (status, outcome) if done, or None if the loop should continue.
    """
    # Completion promise found in response (checked first — fulfilling the
    # promise on the last iteration should count as "completed", not "exhausted").
    # Uses regex to tolerate whitespace and case differences around the tag.
    if loop["completion_promise"] and response:
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

    Queries four sources:
    1. Facts created by this loop (source='loop-{id}') — always included
    2. Facts whose claim/domain/tags match words from the prompt
    3. Assistant messages from this session since the loop started
    4. Past session summaries that reference similar terms
    """
    sections = []
    # Use significant words from the prompt as search terms (5+ chars, deduped)
    prompt_words = list(dict.fromkeys(
        w for w in re.findall(r"[a-zA-Z_]{5,}", loop["prompt"])
    ))[:8]

    # 1. Facts created by this loop (always surfaced regardless of keyword match)
    loop_source = f"loop-{loop['id']}"
    seen_fact_ids = set()
    loop_facts = conn.execute(
        "SELECT id, claim FROM facts WHERE source = ? ORDER BY id",
        (loop_source,),
    ).fetchall()
    if loop_facts:
        lines = [f"- [{f['id']}] {f['claim']}" for f in loop_facts]
        seen_fact_ids = {f["id"] for f in loop_facts}
        sections.append("Loop facts:\n" + "\n".join(lines))

    # 2. Keyword-matched facts (excluding already-shown loop facts)
    if prompt_words:
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
        extra = [f for f in facts if f["id"] not in seen_fact_ids]
        if extra:
            lines = [f"- [{f['id']}] {f['claim']}" for f in extra]
            sections.append("Relevant facts:\n" + "\n".join(lines))

    # 3. Loop progress — assistant messages from this session since loop started
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

    # 4. Related past session summaries (same pattern as preflight.py)
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
    if os.environ.get("LARVLING_AGENT"):
        return

    session_id = data.get("session_id")
    if not session_id:
        return

    transcript_path = data.get("transcript_path")

    wait_for_transcript_stable(transcript_path)

    response, tools = parse_last_turn(transcript_path)

    with open_db() as conn:
        ensure_session(conn, session_id)

        # Log the response (if any)
        logged = False
        if response:
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

    handle_stop(data)


if __name__ == "__main__":
    main()
