"""
Fact extraction via Claude Agent SDK.

Called as a Stop command hook. Reads the transcript, extracts the last
exchange, calls Haiku to identify storable facts, and writes them
directly to SQLite.
"""

import asyncio
import json
import os
import sys
import time

from db import open_db, has_table, reconfigure_stdout

# ---------------------------------------------------------------------------
# Transcript parsing (lightweight copy — avoids importing hooks.py)
# ---------------------------------------------------------------------------


def _is_real_user_message(entry):
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


def parse_last_exchange(transcript_path):
    """Return (user_text, assistant_text) for the last exchange."""
    if not transcript_path or not os.path.exists(transcript_path):
        return None, None

    lines = []
    with open(transcript_path, "r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if raw:
                lines.append(raw)

    # Find last real user message
    user_text = None
    turn_start = 0
    for i in range(len(lines) - 1, -1, -1):
        try:
            entry = json.loads(lines[i])
        except json.JSONDecodeError:
            continue
        if _is_real_user_message(entry):
            msg = entry.get("message", {})
            content = msg.get("content", "")
            if isinstance(content, str):
                user_text = content
            elif isinstance(content, list):
                parts = [
                    b.get("text", "") if isinstance(b, dict) else str(b)
                    for b in content
                    if not (isinstance(b, dict) and b.get("type") == "tool_result")
                ]
                user_text = " ".join(p for p in parts if p).strip()
            turn_start = i + 1
            break

    # Collect assistant text after that
    assistant_parts = []
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
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    t = block.get("text", "").strip()
                    if t:
                        assistant_parts.append(t)
        elif content:
            assistant_parts.append(str(content))

    assistant_text = "\n".join(assistant_parts) if assistant_parts else None
    return user_text, assistant_text


# ---------------------------------------------------------------------------
# Fact extraction via Agent SDK
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT = """\
Extract storable facts from this conversation exchange. Return ONLY valid JSON.

USER said: {user_text}

AGENT responded: {agent_text}

Extract:
- From USER: personal info, professional info, preferences, interests \
(asking about ANY topic = an interest), decisions, opinions
- From AGENT: key knowledge facts shared with the user

Return JSON: {{"facts": [
  {{"claim": "...", "domain": "...", "tags": "..."}},
  ...
]}}

Domains: personal, professional, preferences, interests, knowledge, technical
Tags: short topic label (e.g. "octopuses", "physics", "python")
If nothing to extract, return {{"facts": []}}
JSON only, no markdown fences."""


async def call_sdk(user_text, agent_text):
    """Call Haiku via Agent SDK to extract facts."""
    from claude_code_sdk import query, ClaudeCodeOptions

    prompt = EXTRACTION_PROMPT.format(
        user_text=user_text or "(no user text)",
        agent_text=(agent_text or "(no agent text)")[:2000],  # cap length
    )

    options = ClaudeCodeOptions(
        model="claude-haiku-4-5-20251001",
        max_turns=1,
        allowed_tools=[],
    )

    response_text = ""
    try:
        async for msg in query(prompt=prompt, options=options):
            if hasattr(msg, "content"):
                for block in msg.content:
                    if hasattr(block, "text"):
                        response_text += block.text
    except Exception as e:
        # SDK may raise on unknown message types (rate_limit_event, etc.)
        # If we already have partial response text, use it
        if not response_text:
            raise e

    return response_text


# ---------------------------------------------------------------------------
# DB insertion
# ---------------------------------------------------------------------------


def get_next_id(conn):
    """Get the next M-NNN id."""
    row = conn.execute("SELECT id FROM facts ORDER BY id DESC LIMIT 1").fetchone()
    if row:
        try:
            num = int(row["id"].split("-")[1])
            return num + 1
        except (IndexError, ValueError):
            pass
    return 1


def store_facts(facts_list):
    """Insert extracted facts into the DB."""
    if not facts_list:
        return 0

    with open_db() as conn:
        if not has_table(conn, "facts"):
            return 0

        next_id = get_next_id(conn)
        count = 0

        for fact in facts_list:
            claim = fact.get("claim", "").strip()
            if not claim:
                continue
            domain = fact.get("domain", "knowledge").strip()
            tags = fact.get("tags", "").strip()

            fid = f"M-{next_id:03d}"
            next_id += 1

            # Skip duplicates
            existing = conn.execute(
                "SELECT 1 FROM facts WHERE claim = ?", (claim,)
            ).fetchone()
            if existing:
                continue

            conn.execute(
                "INSERT INTO facts (id, claim, domain, tags, confidence, "
                "source, established) VALUES (?, ?, ?, ?, 'observed', "
                "'conversation', date('now'))",
                (fid, claim, domain, tags or None),
            )
            count += 1

        if count:
            conn.commit()
        return count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    reconfigure_stdout()

    try:
        raw = sys.stdin.buffer.read().decode("utf-8")
    except Exception:
        return

    if not raw.strip():
        return

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return

    transcript_path = data.get("transcript_path")
    user_text, agent_text = parse_last_exchange(transcript_path)

    if not user_text and not agent_text:
        return

    try:
        response = asyncio.run(call_sdk(user_text, agent_text))
    except Exception as e:
        _log_error(f"SDK call failed: {e}")
        return

    # Parse JSON from response
    try:
        # Strip markdown fences if present
        clean = response.strip()
        if clean.startswith("```"):
            clean = "\n".join(clean.split("\n")[1:])
        if clean.endswith("```"):
            clean = clean.rsplit("```", 1)[0]
        result = json.loads(clean.strip())
    except json.JSONDecodeError as e:
        _log_error(f"JSON parse failed: {e}\nResponse: {response[:500]}")
        return

    facts = result.get("facts", [])
    stored = store_facts(facts)
    if stored:
        _log_error(f"Stored {stored} fact(s)")


def _log_error(msg):
    try:
        log_path = os.path.join(os.getcwd(), ".claude", "larvling-errors.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


if __name__ == "__main__":
    main()
